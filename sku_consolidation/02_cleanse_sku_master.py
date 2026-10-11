"""
Stage 2 - Cleanse the stage-1 output into a SKU master data model.

Input  : output/01_unique_products.csv
Outputs:
  output/02_sku_master.csv           one golden record per physical product (seller SKU),
                                     bundle_flag = defined as a bundle in the reference file
  output/02_platform_sku.csv         one row per merchant listing -> sku_master_id
  output/02_sku_master_history.csv   seller-SKU changes observed on the same listing
  output/02_bundle_component.csv     bill of materials: bundle sku_master_id -> component
                                     sku_master_id x qty
  output/02_dq_review.csv            records a data steward should confirm

Optional input: raw/bundle/*.xlsx  bundle reference ("Detail SKU Bundle Royal Canin.xlsx")
  sheet "product-item", columns: SKU Bundle | Product Name Bundle | SKU | Product Name | qty
  (component rows after the first leave the bundle columns blank)

Rules
-----
R1  Standardise seller SKU (sku_clean):
      - trim / collapse whitespace, upper-case
      - drop channel prefixes added per marketplace (TKP_, TTS_, LZD_, SHP_, BLI_)
      - multiplier notation in lower-case: "6X1X40570002" -> "6x1x40570002"
    TikTok "25220040" and Tokopedia "TKP_25220040" therefore become one SKU:
    the 1-N relation seller SKU -> merchant SKU.

R2  Same listing, different seller SKU over time = SKU change.
    A listing is (merchant, merchant_sku). Its distinct sku_clean values,
    ordered by first order date, give the change history
    (e.g. Lazada 30041000 -> 37/010500102A on the same lazadaSku).

R3  Identity resolution: every sku_clean seen on the same listing belongs to the
    same product. Connected components (union-find) over those links form one
    SKU master. Links chain across merchants: Shopee's "37/..." code joins the
    Lazada listing that moved from the old code to it.

R4  Survivorship (golden record):
      master_sku   = most recently introduced sku_clean in the component
                     (latest first_order_date; ties -> used by more merchants)
      product_name = most common name of master_sku listings (ties -> latest)
      first_order_date = earliest across all aliases / merchants

R5  Data-quality flags (sent to 02_dq_review.csv, not auto-fixed):
      missing_seller_sku    listing has no seller SKU -> standalone master
      size_mismatch         SKU change where old/new product names state different pack sizes
      low_name_similarity   SKU change where old/new names share < 50% of their words
                            (token overlap, sizes normalised to grams)
      sku_type_change       SKU change that switches type (e.g. multipack -> bundle)
      large_cluster         master merged from > 4 distinct seller SKUs

R6  Bundles (reference file is the source of truth):
      - components are forward-filled under their bundle SKU; bundle and
        component SKUs are standardised with R1
      - bundle and component SKUs resolve to sku_master_id through every alias,
        so a reference bundle "2x25520040" is found under its new "37/..." code.
        A component "1x40570002" also tries "40570002" (and vice versa).
      - sku_master.bundle_flag = master is a bundle in the reference
      - bundle_component is keyed by the bundle's sku_master_id
      - DQ: bom_code_mismatch       reference BOM disagrees with its own SKU code
            duplicate_bundle        same bundle SKU defined more than once
            multiple_bom_for_master two reference bundle codes resolve to one master
            invalid_qty             qty missing / not a positive number
            bundle_not_in_master    reference bundle never ordered Jan-Sep
            bundle_not_in_reference bundle/multipack sold but not in the reference
                                    (single-unit case packs excluded)
            component_not_in_master component never sold as its own SKU (info only)

Usage:
    python 02_cleanse_sku_master.py [--inp output/01_unique_products.csv] [--out output]
                                    [--bundle raw/bundle]
"""

import argparse
import glob
import logging
import os
import re

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("stage2")

CHANNEL_PREFIX = re.compile(r"^(TKP|TTS|LZD|SHP|BLI)[_\-]", re.I)
MULTIPLIER = re.compile(r"^((?:\d+X)+)")
# "2X Royal ...", "Wet 3x85gr", "(85g x 6 pouches)", "Set Of 12" - but not "1x85gr (PCS)"
MULTIPACK_NAME = re.compile(r"^([2-9]|\d{2,})\s*x\s|(^|\s)([2-9]|\d{2,})\s*x\s*\d"
                            r"|\d\s*(g|gr|kg)\s*x\s*([2-9]|\d{2,})(?!\d)|set of \d+")
LARGE_CLUSTER = 4
LOW_SIMILARITY = 0.5
SIZE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|gr|g)\b")


# --------------------------------------------------------------------------- #
# R1 - standardisation
# --------------------------------------------------------------------------- #
def clean_sku(s):
    if pd.isna(s) or not str(s).strip():
        return None
    s = re.sub(r"\s+", " ", str(s)).strip().upper()
    s = CHANNEL_PREFIX.sub("", s)
    parts = [MULTIPLIER.sub(lambda m: m.group(1).lower(), p.strip()) for p in s.split("+")]
    return "+".join(parts)


def sku_type(s, name=""):
    """Classify from the SKU code; "37/..." codes carry no pattern, so fall back to the name."""
    name = str(name or "").lower()
    if s is None:
        return "unknown"
    if "+" in s or s.startswith("BUND") or " + " in name:
        return "bundle"
    if "NEAREXPIRED" in s or "expired" in name:
        return "near_expired"
    if s.endswith("FG") or "for gift" in name or "not for sale" in name:
        return "free_gift"
    if (MULTIPLIER.match(s.upper()) and not s.upper().startswith("1X")) or MULTIPACK_NAME.search(name):
        return "multipack"
    return "single"


def _grams(qty, unit):
    return "%gg" % (float(qty.replace(",", ".")) * (1000 if unit == "kg" else 1))


def sizes(n):
    """Pack sizes in grams: "0.4kg", "400gr", "400 g" -> {"400g"}."""
    return {_grams(q, u) for q, u in SIZE.findall(str(n).lower())}


def name_tokens(n):
    n = SIZE.sub(lambda m: " " + _grams(*m.groups()) + " ", str(n).lower())
    n = re.sub(r"[^a-z0-9.]+", " ", n.replace("royal canin", " "))
    return set(n.split())


def similarity(a, b):
    """Overlap coefficient of name tokens: word order and naming-template
    suffixes (e.g. "- Feline Health Nutrition") do not lower the score."""
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return 0.0
    return round(len(ta & tb) / min(len(ta), len(tb)), 3)


def size_mismatch(a, b):
    sa, sb = sizes(a), sizes(b)
    return bool(sa and sb and not sa & sb)


# --------------------------------------------------------------------------- #
# R6 - bundles
# --------------------------------------------------------------------------- #
PRODUCT_CODE = re.compile(r"^R?\d{6,8}$")
BUNDLE_COLS = {"sku bundle": "bundle_sku", "product name bundle": "bundle_name",
               "sku": "component_sku", "product name": "component_name", "qty": "qty"}


def parse_bom(sku):
    """{base_code: qty} from a SKU code, or None when a part is not a product code.
    "3x1x20430010" -> {"20430010": 3}; "25220040+6x1x41500010" -> {..: 1, ..: 6}"""
    if not sku:
        return None
    bom = {}
    for part in sku.split("+"):
        m = re.match(r"^((?:\d+x)*)(.+)$", part)
        qty = 1
        for n in re.findall(r"(\d+)x", m.group(1)):
            qty *= int(n)
        base = m.group(2)
        if not PRODUCT_CODE.match(base):
            return None
        bom[base] = bom.get(base, 0) + qty
    return bom


def base_code(sku):
    return re.sub(r"^(?:1x)+", "", sku) if sku else sku


def load_bundle_reference(folder):
    paths = sorted(glob.glob(os.path.join(folder, "*.xlsx")))
    if not paths:
        log.warning("no bundle reference in %s - bundle_flag will be all False", folder)
        return pd.DataFrame(columns=list(BUNDLE_COLS.values()) + ["source_file", "source_row"])
    frames = []
    for path in paths:
        ref = pd.read_excel(path, dtype=str, engine="calamine")
        ref.columns = [str(c).strip().lower() for c in ref.columns]
        ref = ref.rename(columns={"product-item sku bundle": "sku bundle"})  # older header variant
        missing = set(BUNDLE_COLS) - set(ref.columns)
        if missing:
            raise ValueError("%s: missing columns %s" % (path, sorted(missing)))
        ref = ref[list(BUNDLE_COLS)].rename(columns=BUNDLE_COLS)
        ref = ref.apply(lambda c: c.str.strip()).replace("", pd.NA)
        ref = ref.dropna(how="all")
        ref["source_file"] = os.path.basename(path)
        ref["source_row"] = ref.index + 2  # 1-based + header row
        ref[["bundle_sku", "bundle_name"]] = ref[["bundle_sku", "bundle_name"]].ffill()
        frames.append(ref)
        log.info("bundle reference %s: %d component rows", os.path.basename(path), len(ref))
    return pd.concat(frames, ignore_index=True)


def build_bundles(df, master, ref):
    """Bill of materials keyed by the bundle's sku_master_id, from the reference file only."""
    sku_to_master = df.dropna(subset=["sku_clean"]).drop_duplicates("sku_clean").set_index("sku_clean")["sku_master_id"]
    m = master.set_index("sku_master_id")

    def resolve(sku):
        for cand in (sku, base_code(sku), "1x" + base_code(sku) if sku else None):
            if cand and cand in sku_to_master.index:
                return sku_to_master[cand]
        return pd.NA

    comp = ref.copy()
    comp["bundle_sku_clean"] = comp["bundle_sku"].map(clean_sku)
    comp["component_sku_clean"] = comp["component_sku"].map(clean_sku)
    comp["qty"] = pd.to_numeric(comp["qty"], errors="coerce")
    comp["bundle_sku_master_id"] = comp["bundle_sku_clean"].map(resolve)
    comp["component_sku_master_id"] = comp["component_sku_clean"].map(resolve)
    comp["bundle_master_sku"] = comp["bundle_sku_master_id"].map(m["master_sku"])
    comp["component_master_sku"] = comp["component_sku_master_id"].map(m["master_sku"])
    comp["component_seq"] = comp.groupby("bundle_sku_clean").cumcount() + 1

    # ---- DQ (a row can carry several flags)
    flags = {i: [] for i in comp.index}

    def flag(mask, name):
        for i in comp.index[mask]:
            flags[i].append(name)

    flag(comp["bundle_sku_master_id"].isna(), "bundle_not_in_master")
    flag(comp["component_sku_master_id"].isna(), "component_not_in_master")
    flag(~(comp["qty"] > 0), "invalid_qty")
    for bsku, rows in comp.groupby("bundle_sku_clean"):
        if rows["source_row"].diff().gt(1).any() or rows["source_file"].nunique() > 1:
            flag(comp.index.isin(rows.index), "duplicate_bundle")
        code_bom = parse_bom(bsku)
        ref_bom = {}
        for c, q in zip(rows["component_sku_clean"], rows["qty"]):
            ref_bom[base_code(c)] = ref_bom.get(base_code(c), 0) + (q if pd.notna(q) else 0)
        if code_bom is not None and code_bom != ref_bom:
            flag(comp.index.isin(rows.index), "bom_code_mismatch")
    # Two reference bundle codes resolving to the same master (old + new code) = conflicting BOMs.
    per_master = comp.dropna(subset=["bundle_sku_master_id"]).groupby("bundle_sku_master_id")["bundle_sku_clean"].nunique()
    flag(comp["bundle_sku_master_id"].isin(per_master[per_master > 1].index), "multiple_bom_for_master")
    comp["dq_flag"] = [",".join(flags[i]) for i in comp.index]

    comp = comp.sort_values(["bundle_sku_master_id", "bundle_sku_clean", "component_seq"],
                            na_position="last").reset_index(drop=True)
    bundle_component = comp[["bundle_sku_master_id", "bundle_master_sku", "bundle_sku", "bundle_name",
                             "component_seq", "component_sku", "component_sku_clean",
                             "component_sku_master_id", "component_master_sku", "component_name",
                             "qty", "dq_flag"]]

    # Sold bundle / multipack masters the reference does not cover (case packs excluded:
    # e.g. 10930010 "12x85gr - 1 Box" is one unit under its own code).
    in_ref = set(comp["bundle_sku_master_id"].dropna())
    missing = []
    for mid, row in m[m["sku_type"].isin(["bundle", "multipack"])].iterrows():
        if mid in in_ref:
            continue
        boms = [parse_bom(x) for x in str(row["alias_skus"]).split("|") if x]
        if any(b and sum(b.values()) == 1 for b in boms):
            continue
        missing.append(mid)
    not_in_ref = m.loc[missing, ["master_sku", "product_name", "alias_skus"]].reset_index()
    return bundle_component, in_ref, not_in_ref


# --------------------------------------------------------------------------- #
# R3 - union-find
# --------------------------------------------------------------------------- #
class DSU:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inp", default="output/01_unique_products.csv")
    ap.add_argument("--out", default="output")
    ap.add_argument("--bundle", default="raw/bundle")
    a = ap.parse_args()

    df = pd.read_csv(a.inp, dtype=str)
    df["first_order_date"] = pd.to_datetime(df["first_order_date"], format="%Y-%m-%d %H:%M:%S")
    log.info("input rows: %d", len(df))

    df["sku_clean"] = df["seller_sku"].map(clean_sku)
    # Listings without a seller SKU get their own node so they still reach the master.
    df["node"] = df["sku_clean"].where(df["sku_clean"].notna(),
                                       "NOSKU::" + df["merchant"] + "::" + df["merchant_sku"])

    # ---- R3: link every node used on the same listing ----------------------
    dsu = DSU()
    for _, nodes in df.groupby(["merchant", "merchant_sku"])["node"]:
        nodes = nodes.unique()
        dsu.find(nodes[0])
        for n in nodes[1:]:
            dsu.union(nodes[0], n)
    df["cluster"] = df["node"].map(dsu.find)

    # ---- R4: survivorship -------------------------------------------------
    alias = (df.groupby(["cluster", "node"])
               .agg(first_seen=("first_order_date", "min"), merchants=("merchant", "nunique"))
               .reset_index())
    alias["is_nosku"] = alias["node"].str.startswith("NOSKU::")
    alias = alias.sort_values(["cluster", "is_nosku", "first_seen", "merchants"],
                              ascending=[True, True, False, False])
    golden = alias.drop_duplicates("cluster").set_index("cluster")["node"]
    df["master_sku"] = df["cluster"].map(golden)

    def pick_name(g):
        g = g[g["node"] == g["master_sku"].iloc[0]] if (g["node"] == g["master_sku"].iloc[0]).any() else g
        cnt = g.groupby("product_name").agg(n=("merchant", "size"), last=("first_order_date", "max"))
        return cnt.sort_values(["n", "last"], ascending=False).index[0]

    names = df.groupby("cluster").apply(pick_name)

    master = (df.groupby("cluster")
                .agg(first_order_date=("first_order_date", "min"),
                     merchants=("merchant", lambda s: ",".join(sorted(s.unique()))),
                     merchant_count=("merchant", "nunique"),
                     listing_count=("merchant_sku", lambda s: s.nunique()),
                     alias_skus=("sku_clean", lambda s: "|".join(sorted(s.dropna().unique()))),
                     alias_count=("sku_clean", lambda s: s.dropna().nunique()))
                .reset_index())
    master["master_sku"] = master["cluster"].map(golden)
    master["product_name"] = master["cluster"].map(names)
    # agg() mixing datetime min with string lambdas degrades datetimes to int ns; recompute.
    master["first_order_date"] = master["cluster"].map(df.groupby("cluster")["first_order_date"].min())
    master["sku_type"] = [sku_type(sku, name) if pd.notna(sku) and not str(sku).startswith("NOSKU::")
                          else "unknown" for sku, name in zip(master["master_sku"], master["product_name"])]
    master["dq_flag"] = ""
    nosku = master["master_sku"].str.startswith("NOSKU::")
    master.loc[nosku, "dq_flag"] = "missing_seller_sku"
    master.loc[nosku, "master_sku"] = pd.NA
    master.loc[master["alias_count"] > LARGE_CLUSTER, "dq_flag"] = "large_cluster"

    master = master.sort_values(["master_sku", "product_name"], na_position="last").reset_index(drop=True)
    master["sku_master_id"] = ["SKU-%05d" % (i + 1) for i in range(len(master))]
    cluster_to_id = master.set_index("cluster")["sku_master_id"]
    df["sku_master_id"] = df["cluster"].map(cluster_to_id)

    sku_master = master[["sku_master_id", "master_sku", "product_name", "sku_type", "first_order_date",
                         "merchant_count", "merchants", "listing_count", "alias_count", "alias_skus",
                         "dq_flag"]]

    # ---- platform SKU: one row per listing --------------------------------
    df = df.sort_values("first_order_date")
    lst = df.groupby(["merchant", "merchant_sku"])
    platform = lst.agg(sku_master_id=("sku_master_id", "first"),
                       first_order_date=("first_order_date", "min"),
                       current_seller_sku=("seller_sku", "last"),
                       current_seller_sku_clean=("sku_clean", "last"),
                       product_name=("product_name", "last"),
                       seller_sku_versions=("sku_clean", lambda s: s.dropna().nunique()),
                       name_versions=("product_name", "nunique")).reset_index()
    platform["master_sku"] = platform["sku_master_id"].map(master.set_index("sku_master_id")["master_sku"])
    platform["is_on_master_sku"] = platform["current_seller_sku_clean"] == platform["master_sku"]
    platform = platform.sort_values(["sku_master_id", "merchant", "merchant_sku"]).reset_index(drop=True)
    platform["platform_sku_id"] = ["PSK-%05d" % (i + 1) for i in range(len(platform))]
    platform = platform[["platform_sku_id", "sku_master_id", "master_sku", "merchant", "merchant_sku",
                         "current_seller_sku", "current_seller_sku_clean", "is_on_master_sku",
                         "product_name", "first_order_date", "seller_sku_versions", "name_versions"]]

    # ---- R2: history of seller SKU changes per listing --------------------
    ver = (df.dropna(subset=["sku_clean"])
             .groupby(["merchant", "merchant_sku", "sku_clean"])
             .agg(first_seen=("first_order_date", "min"),
                  seller_sku=("seller_sku", "first"),
                  product_name=("product_name", "first"),
                  sku_master_id=("sku_master_id", "first"))
             .reset_index()
             .sort_values(["merchant", "merchant_sku", "first_seen"]))
    hist_rows = []
    for (m, msku), g in ver.groupby(["merchant", "merchant_sku"], sort=False):
        g = g.reset_index(drop=True)
        for i in range(1, len(g)):
            o, n = g.iloc[i - 1], g.iloc[i]
            hist_rows.append({
                "sku_master_id": n["sku_master_id"], "merchant": m, "merchant_sku": msku,
                "version": i + 1,
                "old_seller_sku": o["seller_sku"], "new_seller_sku": n["seller_sku"],
                "old_sku_clean": o["sku_clean"], "new_sku_clean": n["sku_clean"],
                "valid_from_old": o["first_seen"], "changed_at": n["first_seen"],
                "old_product_name": o["product_name"], "new_product_name": n["product_name"],
                "name_similarity": similarity(o["product_name"], n["product_name"]),
            })
    hist = pd.DataFrame(hist_rows, columns=[
        "sku_master_id", "merchant", "merchant_sku", "version", "old_seller_sku", "new_seller_sku",
        "old_sku_clean", "new_sku_clean", "valid_from_old", "changed_at",
        "old_product_name", "new_product_name", "name_similarity"])
    type_change = [sku_type(o, on) != sku_type(n, nn) for o, on, n, nn in
                   zip(hist["old_sku_clean"], hist["old_product_name"], hist["new_sku_clean"], hist["new_product_name"])]
    hist["dq_flag"] = ""
    hist.loc[type_change, "dq_flag"] = "sku_type_change"
    hist.loc[hist["name_similarity"] < LOW_SIMILARITY, "dq_flag"] = "low_name_similarity"
    sz = [size_mismatch(o, n) for o, n in zip(hist["old_product_name"], hist["new_product_name"])]
    hist.loc[sz, "dq_flag"] = "size_mismatch"
    hist = hist.sort_values(["sku_master_id", "merchant", "changed_at"]).reset_index(drop=True)
    hist.insert(0, "history_id", ["HIS-%05d" % (i + 1) for i in range(len(hist))])

    # ---- R6: bundles -------------------------------------------------------
    bundle_component, bundle_masters, not_in_ref = build_bundles(
        df, master.drop(columns="cluster"), load_bundle_reference(a.bundle))
    sku_master.insert(sku_master.columns.get_loc("sku_type") + 1, "bundle_flag",
                      sku_master["sku_master_id"].isin(bundle_masters))
    REVIEW_BUNDLE = {"bom_code_mismatch", "duplicate_bundle", "invalid_qty", "bundle_not_in_master",
                     "multiple_bom_for_master"}
    comp_review = bundle_component[bundle_component["dq_flag"].str.split(",").map(
        lambda f: bool(REVIEW_BUNDLE & set(f)))].drop_duplicates(["bundle_sku", "dq_flag"])

    # ---- DQ review --------------------------------------------------------
    review = pd.concat([
        sku_master[sku_master["dq_flag"] != ""].assign(source="sku_master")[
            ["source", "dq_flag", "sku_master_id", "master_sku", "product_name", "alias_skus"]],
        hist[hist["dq_flag"] != ""].assign(source="sku_master_history").rename(
            columns={"new_product_name": "product_name"})[
            ["source", "dq_flag", "sku_master_id", "merchant", "merchant_sku", "old_seller_sku",
             "new_seller_sku", "old_product_name", "product_name", "name_similarity"]],
        comp_review.assign(source="bundle_component").rename(
            columns={"bundle_sku_master_id": "sku_master_id", "bundle_master_sku": "master_sku",
                     "bundle_name": "product_name"})[
            ["source", "dq_flag", "sku_master_id", "master_sku", "product_name", "bundle_sku"]],
        not_in_ref.assign(source="sku_master", dq_flag="bundle_not_in_reference")[
            ["source", "dq_flag", "sku_master_id", "master_sku", "product_name", "alias_skus"]],
    ], ignore_index=True)

    # ---- write ------------------------------------------------------------
    os.makedirs(a.out, exist_ok=True)
    fmt = "%Y-%m-%d %H:%M:%S"
    outputs = {
        "02_sku_master.csv": sku_master,
        "02_platform_sku.csv": platform,
        "02_sku_master_history.csv": hist,
        "02_bundle_component.csv": bundle_component,
        "02_dq_review.csv": review,
    }
    for fn, frame in outputs.items():
        frame.to_csv(os.path.join(a.out, fn), index=False, date_format=fmt)
        log.info("written %-28s %6d rows", fn, len(frame))

    # ---- reconciliation checks -------------------------------------------
    assert platform["sku_master_id"].notna().all(), "listing without master"
    assert platform.groupby(["merchant", "merchant_sku"]).size().max() == 1, "listing maps to >1 master"
    assert df.groupby(["merchant", "merchant_sku"])["sku_master_id"].nunique().max() == 1
    log.info("distinct cleaned seller SKUs: %d -> SKU masters: %d", df["sku_clean"].nunique(), len(sku_master))
    log.info("listings per merchant:\n%s", platform["merchant"].value_counts().to_string())
    log.info("history rows per merchant:\n%s", hist["merchant"].value_counts().to_string())
    assert not bundle_component.duplicated(["bundle_sku_master_id", "bundle_sku", "component_seq"]).any()
    log.info("bundle masters (bundle_flag): %d, component rows: %d", sku_master["bundle_flag"].sum(),
             len(bundle_component))
    log.info("bundle component dq flags: %s", bundle_component["dq_flag"].str.split(",").explode()
             .replace("", pd.NA).dropna().value_counts().to_dict())
    log.info("dq review rows: %d", len(review))


if __name__ == "__main__":
    main()
