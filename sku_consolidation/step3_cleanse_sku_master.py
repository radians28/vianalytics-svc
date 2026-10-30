"""Step 3 - Cleanse the unique SKU list into the SKU master tables.

Input  : stg/stg_unique_sku.csv
Output : sku_master/m_channel.csv, m_sku.csv, m_sku_alias.csv, m_platform_sku.csv,
         m_sku_history.csv, sku_dq_review.csv      (columns follow ddl_royal_canin.sql)

Rules (same as the earlier 02_cleanse_sku_master.py)
  R1 standardise seller SKU (sku_clean: trim, upper-case, drop TKP_/TTS_/LZD_/SHP_/BLI_ prefix)
  R2 same listing (channel + marketplace SKU) sold under different seller SKUs = SKU change history
  R3 identity resolution: all SKUs seen on one listing are one product (union-find, chains across channels),
     except a bundle and its own (first-level) component in the bundling master: the one with fewer order lines
     on that listing stays a separate SKU, otherwise step 5 would lose the component
     (dq_flag bundle_component_split in sku_dq_review; the listing's sku_id is its busiest SKU)
  R4 survivorship: master_sku = most recently introduced SKU of the cluster; name = most common name
  R5 DQ flags: missing_seller_sku, large_cluster, size_mismatch, low_name_similarity, sku_type_change
IDs: sku_id / platform_sku_id are integers assigned in first-order order (stable for the same input).
bundle_flag is False here; step 5 flags bundles.
"""
import argparse
import logging
import os

import pandas as pd

from common import bundle
from common.config import CHANNELS, GMV2_DEDUP, SKU_MASTER, STG, TS_OUT, TZ_SUFFIX
from common.parsers import clean_sku, fmt_ts, read_ts
from common.skutils import DSU, similarity, size_mismatch, sku_type

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("step3")

LARGE_CLUSTER = 4
LOW_SIMILARITY = 0.5


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inp", default=os.path.join(STG, "stg_unique_sku.csv"))
    ap.add_argument("--out-dir", default=SKU_MASTER)
    ap.add_argument("--bundle-dir", default=bundle.BUNDLE_DIR)
    a = ap.parse_args()

    df = pd.read_csv(a.inp, dtype=str, keep_default_na=False)
    df = df.rename(columns={"marketplace": "merchant", "marketplace_sku": "merchant_sku"})
    df["first_order_date"] = read_ts(df["first_order_at"])
    for c in ("seller_sku", "sku_clean", "merchant_sku"):
        df[c] = df[c].replace("", pd.NA)
    assert df["merchant_sku"].notna().all(), "listing without marketplace SKU"
    log.info("input rows: %d", len(df))

    df["node"] = df["sku_clean"].where(df["sku_clean"].notna(),
                                       "NOSKU::" + df["merchant"] + "::" + df["merchant_sku"])

    # ---- R3 identity resolution -------------------------------------------
    bom = bundle.load_master(a.bundle_dir)
    bom_pairs = {frozenset((clean_sku(b), clean_sku(c))) for b, c in zip(bom["bundle_sku"], bom["component_sku"])}
    node_lines = df["order_line_count"].astype(int).groupby(df["node"]).sum()
    dsu, split = DSU(), []
    for (m, ms), nodes in df.groupby(["merchant", "merchant_sku"])["node"]:
        nodes = list(nodes.unique())
        # a bundle and its own component on one listing: the code with fewer order lines stays out of the merge
        out = {min(x, y, key=lambda n: (node_lines[n], n)) for i, x in enumerate(nodes) for y in nodes[i + 1:]
               if frozenset((x, y)) in bom_pairs}
        for n in out:
            split.append({"source": "m_sku", "dq_flag": "bundle_component_split", "master_sku": n,
                          "product_name": "listing %s %s: kept apart from %s (bundle / component)"
                                          % (m, ms, ",".join(x for x in nodes if frozenset((x, n)) in bom_pairs))})
        keep = [n for n in nodes if n not in out] or nodes[:1]
        for n in nodes:
            dsu.find(n)
        for n in keep[1:]:
            dsu.union(keep[0], n)
    df["cluster"] = df["node"].map(dsu.find)
    seen = set(df["node"])
    merged = [tuple(p) for p in bom_pairs if len(p) == 2 and p <= seen and len({dsu.find(x) for x in p}) == 1]
    if merged:
        log.warning("bundle and component still in one SKU through other listings: %s", merged)
    log.info("bundle/component links kept apart: %d", len(split))

    # ---- R4 survivorship ---------------------------------------------------
    alias = (df.groupby(["cluster", "node"])
               .agg(first_seen=("first_order_date", "min"), merchants=("merchant", "nunique"))
               .reset_index())
    alias["is_nosku"] = alias["node"].str.startswith("NOSKU::")
    alias = alias.sort_values(["cluster", "is_nosku", "first_seen", "merchants"],
                              ascending=[True, True, False, False])
    golden = alias.drop_duplicates("cluster").set_index("cluster")["node"]
    df["master_sku"] = df["cluster"].map(golden)

    def pick_name(g):
        top = g["master_sku"].iloc[0]
        g = g[g["node"] == top] if (g["node"] == top).any() else g
        cnt = g.groupby("product_name").agg(n=("order_line_count", "size"), last=("first_order_date", "max"))
        return cnt.sort_values(["n", "last"], ascending=False).index[0]

    names = df.groupby("cluster").apply(pick_name, include_groups=False)
    g = df.groupby("cluster")
    master = pd.DataFrame({
        "first_order_at": g["first_order_date"].min(),
        "alias_count": g["sku_clean"].nunique(),
    }).reset_index()
    master["master_sku"] = master["cluster"].map(golden)
    master["product_name"] = master["cluster"].map(names)
    master["sku_type"] = [sku_type(s, n) if not str(s).startswith("NOSKU::") else "unknown"
                          for s, n in zip(master["master_sku"], master["product_name"])]
    master["dq_flag"] = ""
    nosku = master["master_sku"].str.startswith("NOSKU::")
    master.loc[nosku, "dq_flag"] = "missing_seller_sku"
    master.loc[nosku, "master_sku"] = pd.NA
    master.loc[master["alias_count"] > LARGE_CLUSTER, "dq_flag"] = "large_cluster"
    master = master.sort_values(["first_order_at", "master_sku"], kind="stable", na_position="last").reset_index(drop=True)
    master["sku_id"] = range(1, len(master) + 1)
    master["sku_master_code"] = master["sku_id"].map("SKU-{:05d}".format)
    master["bundle_flag"] = False
    cluster_to_id = master.set_index("cluster")["sku_id"]
    df["sku_id"] = df["cluster"].map(cluster_to_id)

    # ---- m_sku_alias -------------------------------------------------------
    al = (alias[~alias["is_nosku"]].assign(sku_id=lambda x: x["cluster"].map(cluster_to_id))
          .rename(columns={"node": "sku_code", "first_seen": "first_seen_at"}))
    al["is_master_code"] = al["sku_code"] == al["cluster"].map(golden)
    al = al.sort_values(["sku_id", "sku_code"])[["sku_code", "sku_id", "is_master_code", "first_seen_at"]]
    assert al["sku_code"].is_unique

    # ---- m_platform_sku ----------------------------------------------------
    df = df.sort_values("first_order_date", kind="stable")
    busiest = (df.assign(n=df["order_line_count"].astype(int)).groupby(["merchant", "merchant_sku", "sku_id"])["n"]
                 .sum().reset_index().sort_values("n", ascending=False, kind="stable")
                 .drop_duplicates(["merchant", "merchant_sku"]).set_index(["merchant", "merchant_sku"])["sku_id"])
    plat = (df.groupby(["merchant", "merchant_sku"], sort=False)
              .agg(first_order_at=("first_order_date", "min"),
                   current_seller_sku=("seller_sku", "last"), current_clean=("sku_clean", "last"),
                   product_name=("product_name", "last")).reset_index())
    plat["sku_id"] = [busiest[k] for k in zip(plat["merchant"], plat["merchant_sku"])]
    plat["master_sku"] = plat["sku_id"].map(master.set_index("sku_id")["master_sku"])
    plat["is_on_master_sku"] = plat["current_clean"] == plat["master_sku"]
    plat = plat.sort_values(["first_order_at", "merchant", "merchant_sku"], kind="stable").reset_index(drop=True)
    plat["platform_sku_id"] = range(1, len(plat) + 1)
    plat["channel_id"] = plat["merchant"].map(lambda c: CHANNELS[c]["channel_id"])
    plat_key = plat.set_index(["merchant", "merchant_sku"])["platform_sku_id"]

    # ---- R2 history --------------------------------------------------------
    ver = (df.dropna(subset=["sku_clean"])
             .groupby(["merchant", "merchant_sku", "sku_clean"], sort=False)
             .agg(first_seen=("first_order_date", "min"), seller_sku=("seller_sku", "first"),
                  product_name=("product_name", "first"), sku_id=("sku_id", "first")).reset_index()
             .sort_values(["merchant", "merchant_sku", "first_seen"], kind="stable"))
    rows = []
    for (m, ms), grp in ver.groupby(["merchant", "merchant_sku"], sort=False):
        grp = grp.reset_index(drop=True)
        for i in range(1, len(grp)):
            o, n = grp.iloc[i - 1], grp.iloc[i]
            rows.append({"platform_sku_id": plat_key[(m, ms)], "sku_id": n["sku_id"], "version": i + 1,
                         "old_seller_sku": o["seller_sku"], "new_seller_sku": n["seller_sku"],
                         "valid_from": o["first_seen"], "changed_at": n["first_seen"],
                         "_old_clean": o["sku_clean"], "_new_clean": n["sku_clean"],
                         "_old_name": o["product_name"], "_new_name": n["product_name"]})
    hist = pd.DataFrame(rows)
    hist["_sim"] = [similarity(o, n) for o, n in zip(hist["_old_name"], hist["_new_name"])]
    hist["dq_flag"] = ""
    hist.loc[[sku_type(o, on) != sku_type(n, nn) for o, on, n, nn in
              zip(hist["_old_clean"], hist["_old_name"], hist["_new_clean"], hist["_new_name"])], "dq_flag"] = "sku_type_change"
    hist.loc[hist["_sim"] < LOW_SIMILARITY, "dq_flag"] = "low_name_similarity"
    hist.loc[[size_mismatch(o, n) for o, n in zip(hist["_old_name"], hist["_new_name"])], "dq_flag"] = "size_mismatch"
    hist = hist.sort_values(["changed_at", "platform_sku_id", "version"], kind="stable").reset_index(drop=True)
    hist.insert(0, "history_id", range(1, len(hist) + 1))
    assert (hist["changed_at"] >= hist["valid_from"]).all() and (hist["version"] >= 2).all()

    # ---- DQ review ---------------------------------------------------------
    review = pd.concat([
        master[master["dq_flag"] != ""].assign(source="m_sku")[["source", "dq_flag", "sku_id", "master_sku", "product_name"]],
        hist[hist["dq_flag"] != ""].assign(source="m_sku_history").rename(columns={"_new_name": "product_name"})[
            ["source", "dq_flag", "sku_id", "platform_sku_id", "old_seller_sku", "new_seller_sku", "_old_name", "product_name", "_sim"]],
        pd.DataFrame(split, columns=["source", "dq_flag", "master_sku", "product_name"]),
    ], ignore_index=True).rename(columns={"_old_name": "old_product_name", "_sim": "name_similarity"})

    # ---- write -------------------------------------------------------------
    os.makedirs(a.out_dir, exist_ok=True)
    chan = pd.DataFrame([{"channel_id": v["channel_id"], "channel_code": k, "channel_name": v["name"],
                          "sku_source_column": v["sku_source_column"], "order_ts_format": v["ts_format"],
                          "gmv2_dedup_by_order": GMV2_DEDUP[k], "is_active": True}
                         for k, v in CHANNELS.items()])
    ts = lambda s: fmt_ts(s)
    out = {
        "m_channel.csv": chan,
        "m_sku.csv": master.assign(first_order_at=ts(master["first_order_at"]))[
            ["sku_id", "sku_master_code", "master_sku", "product_name", "sku_type", "bundle_flag", "first_order_at", "dq_flag"]],
        "m_sku_alias.csv": al.assign(first_seen_at=ts(al["first_seen_at"])),
        "m_platform_sku.csv": plat.assign(first_order_at=ts(plat["first_order_at"]))[
            ["platform_sku_id", "channel_id", "merchant_sku", "sku_id", "current_seller_sku", "product_name",
             "is_on_master_sku", "first_order_at"]],
        "m_sku_history.csv": hist.assign(valid_from=ts(hist["valid_from"]), changed_at=ts(hist["changed_at"]))[
            ["history_id", "platform_sku_id", "sku_id", "version", "old_seller_sku", "new_seller_sku",
             "valid_from", "changed_at", "dq_flag"]],
        "sku_dq_review.csv": review,
    }
    for fn, frame in out.items():
        frame.to_csv(os.path.join(a.out_dir, fn), index=False)
        log.info("written %-22s %6d rows", fn, len(frame))
    log.info("distinct cleaned seller SKUs: %d -> SKU masters: %d; listings: %d",
             df["sku_clean"].nunique(), len(master), len(plat))


if __name__ == "__main__":
    main()
