"""Step 4 - Compare each bundle's price with the sum of its components' prices (review only).

Input  : raw/sku_bundle/bundling_master.csv  (bundle -> component SKU + qty per bundle)
         raw/sku_bundle/bundling_price.csv   (price of every SKU, bundles and components alike)
Output : sku_master/bundle_price_check.csv     one row per bundle
         sku_master/bundle_price_mismatch.csv  flagged bundles with their components beside them

components_sum = sum(component price x component qty)
diff_pct       = (a ratio, 0.10 = 10%) |bundle_price - components_sum| / min(bundle_price, components_sum)
status         = price_gap when diff_pct > --threshold (default 10%) else ok;
                 pass when the gap is on a single-component bundle (PCS of a BOX: unit conversion, reviewed);
                 bundle_price_missing | component_price_missing | price_zero when it cannot be compared.
Bundles are broken down one level only (a component that is a bundle itself is priced as that bundle).
A blank / unlisted price counts as 0 in components_sum (as in step 5), but the bundle is still marked
component_price_missing / bundle_price_missing for review.
Free-gift components (code 37/B..., "B - ...") have price 0 (common/bundle.py), so a bundle's value is that of its other components.
Master data is not changed here; step 5 carries `price_gap` into m_sku_bundle.dq_flag.
"""
import argparse
import logging
import os

import numpy as np
import pandas as pd

from common import bundle
from common.config import SKU_MASTER

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("step4")


def build_check(master, prices, threshold):
    comp = master.copy()
    comp["unit_price"], _, comp["price_missing"] = bundle.price_of(prices, comp["component_sku"], comp["component_name"])
    comp["line_total"] = comp["unit_price"] * comp["qty"]
    g = comp.groupby("bundle_sku", sort=False)
    chk = g.agg(bundle_name=("bundle_name", "first"), component_count=("component_sku", "size"),
                components_sum=("line_total", "sum"), missing_components=("price_missing", "sum"),
                zero_components=("unit_price", lambda s: (s == 0).sum()),
                notes=("notes", lambda s: ",".join(sorted({x for v in s for x in v.split(",") if x})))).reset_index()
    chk["bundle_price"], is_gift, bundle_missing = bundle.price_of(prices, chk["bundle_sku"], chk["bundle_name"])
    chk["diff"] = chk["bundle_price"] - chk["components_sum"]
    low = np.minimum(chk["bundle_price"], chk["components_sum"])
    chk["diff_pct"] = (chk["diff"].abs() / low).where(low > 0)
    chk["direction"] = np.where(chk["diff"] > 0, "bundle_higher", np.where(chk["diff"] < 0, "bundle_lower", "equal"))

    status = pd.Series("ok", index=chk.index)
    status[chk["diff_pct"] > threshold] = "price_gap"
    # single-component bundle = PCS SKU of a BOX SKU (unit conversion, not a pricing error) -> pass
    status[(status == "price_gap") & (chk["component_count"] == 1)] = "pass"
    one_zero = (chk["bundle_price"] == 0) != (chk["components_sum"] == 0)       # both 0 = free-gift bundle, consistent
    status[one_zero & (chk["missing_components"] == 0)] = "price_zero"
    status[chk["missing_components"] > 0] = "component_price_missing"
    status[bundle_missing] = "bundle_price_missing"
    status[is_gift] = "pass"            # the bundle itself is a free gift ("B - ...", price 0): not compared
    chk["status"] = status
    comparable = chk["status"].isin(["ok", "price_gap", "pass"]) & ~pd.Series(is_gift)
    chk.loc[~comparable, ["diff", "diff_pct", "direction"]] = [np.nan, np.nan, ""]
    cols = ["bundle_sku", "bundle_name", "component_count", "bundle_price", "components_sum", "diff",
            "diff_pct", "direction", "status", "missing_components", "notes"]
    return chk[cols], comp


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bundle-dir", default=bundle.BUNDLE_DIR)
    ap.add_argument("--out-dir", default=SKU_MASTER)
    ap.add_argument("--threshold", type=float, default=0.10)
    a = ap.parse_args()

    prices = bundle.load_prices(a.bundle_dir)
    master = bundle.load_master(a.bundle_dir)
    chk, comp = build_check(master, prices, a.threshold)
    order = chk["status"].map({"price_gap": 0, "pass": 1, "ok": 2}).fillna(3)
    chk = chk.assign(_o=order).sort_values(["_o", "diff_pct"], ascending=[True, False]).drop(columns="_o").reset_index(drop=True)

    flagged = chk[chk["status"] == "price_gap"]
    rows = []
    for _, b in flagged.iterrows():
        rows.append({"bundle_sku": b["bundle_sku"], "row_type": "bundle", "sku": b["bundle_sku"], "name": b["bundle_name"],
                     "qty": 1, "unit_price": b["bundle_price"], "line_total": b["bundle_price"],
                     "components_sum": b["components_sum"], "diff": b["diff"], "diff_pct": b["diff_pct"],
                     "direction": b["direction"]})
        for _, c in comp[comp["bundle_sku"] == b["bundle_sku"]].iterrows():
            rows.append({"bundle_sku": b["bundle_sku"], "row_type": "component", "sku": c["component_sku"],
                         "name": c["component_name"], "qty": c["qty"], "unit_price": c["unit_price"],
                         "line_total": c["line_total"]})
    mismatch = pd.DataFrame(rows, columns=["bundle_sku", "row_type", "sku", "name", "qty", "unit_price",
                                           "line_total", "components_sum", "diff", "diff_pct", "direction"])

    os.makedirs(a.out_dir, exist_ok=True)
    chk.to_csv(os.path.join(a.out_dir, "bundle_price_check.csv"), index=False, float_format="%.4f")
    mismatch.to_csv(os.path.join(a.out_dir, "bundle_price_mismatch.csv"), index=False, float_format="%.4f")
    vc = chk["status"].value_counts().to_dict()
    log.info("bundles checked: %d | status: %s", len(chk), vc)
    log.info("price_gap: bundle_higher=%d bundle_lower=%d (threshold %.0f%% of the lower price)",
             (flagged["direction"] == "bundle_higher").sum(), (flagged["direction"] == "bundle_lower").sum(),
             a.threshold * 100)
    log.info("written bundle_price_check.csv (%d), bundle_price_mismatch.csv (%d rows, %d bundles)",
             len(chk), len(mismatch), len(flagged))


if __name__ == "__main__":
    main()
