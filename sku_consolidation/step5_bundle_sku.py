"""Step 5 - Flag bundle SKUs in the SKU master and build m_sku_bundle.

Input  : sku_master/m_sku.csv, m_sku_alias.csv            (step 3)
         sku_master/bundle_price_check.csv                (step 4, for the price_gap flag)
         raw/sku_bundle/bundling_master.csv, bundling_price.csv
Output : sku_master/m_sku.csv, m_sku_alias.csv            (rewritten: bundle_flag, extra SKUs)
         sku_master/m_sku_bundle.csv                      (DDL columns + component_price)
         sku_master/bundle_dq_review.csv

a. every bundle code of the bundling master (a code with at least one component other than itself)
   is resolved to m_sku through m_sku_alias and flagged bundle_flag=true, sku_type='bundle'
b. bundle / component codes unknown to the master are added as new SKUs
   (dq_flag='from_bundle_master', no first_order_at)
c. m_sku_bundle: one row per (bundle sku, component) with qty, component_price (bundling_price.csv; a blank or
   unlisted price is 0) and price_ratio = price x qty / sum(price x qty) of the bundle (quantity ratio + dq_flag
   equal_split only when every component of the bundle is priced 0)
   Recursive PCS<->BOX pairs are resolved and a bundle is broken down one level only (common/bundle.py): a
   component that is a bundle itself is kept as that bundle SKU and not expanded further.
   dq_flag: free_gift (price 0, component is a "B - ..." gimmick/sampling item), qty_missing (blank/0 -> 1), dup_component, nested_bundle (component is a bundle itself), component_price_missing (blank price -> 0), price_gap
Re-running is safe: SKUs added earlier are found again through m_sku_alias.
"""
import argparse
import logging
import os
import re

import pandas as pd

from common import bundle
from common.config import SKU_MASTER
from common.parsers import clean_sku

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("step5")


class SkuBook:
    """m_sku + m_sku_alias with resolve-or-create."""

    def __init__(self, sku, alias):
        self.sku, self.alias = sku, alias
        self.code2id = dict(zip(alias["sku_code"], alias["sku_id"]))
        self.next_id = int(sku["sku_id"].max()) + 1
        self.new_sku, self.new_alias = [], []

    def lookup(self, code):
        c = clean_sku(code)
        for cand in (c, re.sub(r"^(?:1X)+", "", c or "", flags=re.I)):
            if cand and cand in self.code2id:
                return self.code2id[cand], cand
        return None, c

    def resolve_or_create(self, code, name, sku_type):
        sid, c = self.lookup(code)
        if sid is not None:
            return sid, c, False
        sid = self.next_id
        self.next_id += 1
        self.new_sku.append({"sku_id": sid, "sku_master_code": "SKU-{:05d}".format(sid), "master_sku": c,
                             "product_name": name, "sku_type": sku_type, "bundle_flag": False,
                             "first_order_at": "", "dq_flag": "from_bundle_master"})
        self.new_alias.append({"sku_code": c, "sku_id": sid, "is_master_code": True, "first_seen_at": ""})
        self.code2id[c] = sid
        return sid, c, True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--master-dir", default=SKU_MASTER)
    ap.add_argument("--bundle-dir", default=bundle.BUNDLE_DIR)
    a = ap.parse_args()
    p = lambda f: os.path.join(a.master_dir, f)

    sku = pd.read_csv(p("m_sku.csv"), dtype={"dq_flag": str, "first_order_at": str}, keep_default_na=False)
    alias = pd.read_csv(p("m_sku_alias.csv"), dtype={"first_seen_at": str}, keep_default_na=False)
    check = pd.read_csv(p("bundle_price_check.csv"), keep_default_na=False).set_index("bundle_sku")["status"]
    prices = bundle.load_prices(a.bundle_dir)
    bom = bundle.load_master(a.bundle_dir)
    book = SkuBook(sku, alias)
    bom["unit_price"], bom["free_gift"], bom["price_missing"] = bundle.price_of(prices, bom["component_sku"],
                                                                                  bom["component_name"])

    rows, review, bundle_ids = [], list(bom.attrs.get("log", [])), {}
    for bsku, grp in bom.groupby("bundle_sku", sort=False):
        bid, bclean, created = book.resolve_or_create(bsku, grp["bundle_name"].iloc[0], "bundle")
        if bid in bundle_ids:   # two bundle codes collapsed into the same master by step 3
            review.append({"bundle_sku": bsku, "dq_flag": "multiple_bom_for_master",
                           "detail": "same sku as %s - BOM skipped" % bundle_ids[bid]})
            continue
        bundle_ids[bid] = bsku
        seq = 0
        for _, c in grp.iterrows():
            cid, cclean, _ = book.resolve_or_create(c["component_sku"], c["component_name"], "single")
            if cid == bid:
                review.append({"bundle_sku": bsku, "dq_flag": "component_is_bundle_itself", "detail": c["component_sku"]})
                continue
            seq += 1
            price = c["unit_price"]
            flags = [f for f in c["notes"].split(",") if f]
            if c["price_missing"]:
                flags.append("component_price_missing")
            elif c["free_gift"]:
                flags.append("free_gift")
            if check.get(bsku) == "price_gap":
                flags.append("price_gap")
            rows.append({"bundle_sku_id": bid, "component_seq": seq, "component_sku_id": cid,
                         "component_sku_code": cclean, "qty": int(c["qty"]),
                         "component_price": price, "dq_flag": ",".join(flags), "_bundle_code": bsku})
    sbundle = pd.DataFrame(rows)
    # price ratio of each component inside its bundle = price x qty / sum(price x qty) (blank price = 0); quantity
    # ratio when every price is 0 (flagged equal_split) - used by step 6 to split the order value
    w = sbundle["component_price"] * sbundle["qty"]
    ok = w.groupby(sbundle["bundle_sku_id"]).transform("sum") > 0
    weight = w.where(ok, sbundle["qty"]).astype(float)
    sbundle["price_ratio"] = (weight / weight.groupby(sbundle["bundle_sku_id"]).transform("sum")).round(8)
    sbundle.loc[~ok, "dq_flag"] = sbundle.loc[~ok, "dq_flag"].map(lambda f: ",".join([x for x in f.split(",") if x] + ["equal_split"]))

    # ---- a. flag bundles; b. add new SKUs
    sku = pd.concat([sku, pd.DataFrame(book.new_sku)], ignore_index=True)
    alias = pd.concat([alias, pd.DataFrame(book.new_alias)], ignore_index=True)
    is_b = sku["sku_id"].isin(bundle_ids)
    sku.loc[is_b, ["bundle_flag", "sku_type"]] = [True, "bundle"]
    gift = sku["sku_id"].isin(sbundle.loc[sbundle["dq_flag"].str.contains("free_gift"), "component_sku_id"]) & ~is_b
    sku.loc[gift, "sku_type"] = "free_gift"
    sku["bundle_flag"] = sku["bundle_flag"].astype(bool)

    for _, r in sbundle[sbundle["dq_flag"] != ""].iterrows():
        for f in r["dq_flag"].split(","):
            review.append({"bundle_sku": r["_bundle_code"], "dq_flag": f, "detail": r["component_sku_code"]})
    for b, s in check.items():
        if s in ("bundle_price_missing", "price_zero"):
            review.append({"bundle_sku": b, "dq_flag": s, "detail": ""})

    sbundle = sbundle.sort_values(["bundle_sku_id", "component_seq"])
    assert not sbundle.duplicated(["bundle_sku_id", "component_seq"]).any()
    assert (sbundle["qty"] > 0).all()
    assert sbundle["component_sku_id"].isin(sku["sku_id"]).all() and sbundle["bundle_sku_id"].isin(sku["sku_id"]).all()
    assert alias["sku_code"].is_unique and alias["sku_id"].isin(sku["sku_id"]).all()

    sku.to_csv(p("m_sku.csv"), index=False)
    alias.to_csv(p("m_sku_alias.csv"), index=False)
    cols = ["bundle_sku_id", "component_seq", "component_sku_id", "component_sku_code", "qty", "component_price",
            "price_ratio", "dq_flag"]
    sbundle[cols].to_csv(p("m_sku_bundle.csv"), index=False)
    pd.DataFrame(review, columns=["bundle_sku", "dq_flag", "detail"]).drop_duplicates().to_csv(
        p("bundle_dq_review.csv"), index=False)
    log.info("bundles flagged: %d | bundle components: %d | new SKUs added: %d (bundles %d)",
             int(sku["bundle_flag"].sum()), len(sbundle), len(book.new_sku),
             sum(1 for s in book.new_sku if s["sku_type"] == "bundle"))
    log.info("m_sku_bundle dq flags: %s", sbundle["dq_flag"].str.split(",").explode().replace("", pd.NA)
             .value_counts().to_dict())
    log.info("review rows: %d", len(review))


if __name__ == "__main__":
    main()
