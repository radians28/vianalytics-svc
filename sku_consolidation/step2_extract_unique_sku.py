"""Step 2 - Extract the unique product listings from all stg_{marketplace} files.

Input  : stg/stg_{shopee,tokopedia,tiktok,lazada,blibli}.csv
Output : stg/stg_unique_sku.csv

Grain  : one row per (marketplace, seller_sku, marketplace_sku)
Columns: marketplace, seller_sku, marketplace_sku, sku_clean, product_name, variation,
         first_order_at, last_order_at, order_line_count, dq_note
         (first_order_at = first time the combination occurs in an order;
          product_name = name on the latest order line)
Order  : first_order_at asc, then marketplace, seller_sku.

Metadata columns feeding step 3:
  sku_clean   seller SKU without channel prefix (TKP_, TTS_ ...) -> m_sku_alias.sku_code
  marketplace_sku -> m_platform_sku.merchant_sku (Shopee: SHP_ + md5(name|variation)[:12])
  dq_note     missing_seller_sku | missing_marketplace_sku
              seller_sku_changed  (the same marketplace_sku was sold under >1 seller SKU -> m_sku_history)
              shared_seller_sku   (the same cleaned seller SKU sits on >1 marketplace_sku -> m_sku_alias)
"""
import argparse
import logging
import os

import pandas as pd

from common import normalize as nz
from common.config import CHANNELS, STG
from common.parsers import clean_sku, fmt_ts

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("step2")

COLS = ["marketplace", "seller_sku", "marketplace_sku", "sku_clean", "product_name", "variation",
        "first_order_at", "last_order_at", "order_line_count", "dq_note"]


def unique_for(channel, stg_dir):
    lines = nz.normalize(nz.load_stg(channel, stg_dir), channel)
    lines = lines[lines["created_at"].notna()].sort_values("created_at", kind="stable")
    for c in ("seller_sku", "platform_sku", "product_name", "variation"):
        lines[c] = lines[c].fillna("")
    g = lines.groupby(["seller_sku", "platform_sku"], sort=False)
    out = g.agg(product_name=("product_name", "last"), variation=("variation", "last"),
                first_order_at=("created_at", "min"), last_order_at=("created_at", "max"),
                order_line_count=("order_no", "size")).reset_index()
    out = out.rename(columns={"platform_sku": "marketplace_sku"})
    out.insert(0, "marketplace", channel)
    log.info("%-9s %8d lines -> %6d unique", channel, len(lines), len(out))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stg-dir", default=STG)
    ap.add_argument("--out-dir", default=STG)
    a = ap.parse_args()

    df = pd.concat([unique_for(c, a.stg_dir) for c in CHANNELS], ignore_index=True)
    df["sku_clean"] = df["seller_sku"].map(lambda s: clean_sku(s) or "")

    notes = [[] for _ in range(len(df))]

    def flag(mask, name):
        for i in df.index[mask.values]:
            notes[i].append(name)

    flag(df["seller_sku"] == "", "missing_seller_sku")
    flag(df["marketplace_sku"] == "", "missing_marketplace_sku")
    has_msku = df["marketplace_sku"] != ""
    n_seller = df[has_msku].groupby(["marketplace", "marketplace_sku"])["sku_clean"].transform("nunique")
    flag(has_msku & (n_seller.reindex(df.index, fill_value=0) > 1), "seller_sku_changed")
    has_sku = df["sku_clean"] != ""
    n_listing = df[has_sku].groupby(["marketplace", "sku_clean"])["marketplace_sku"].transform("nunique")
    flag(has_sku & (n_listing.reindex(df.index, fill_value=0) > 1), "shared_seller_sku")
    df["dq_note"] = [",".join(n) for n in notes]

    df = df.sort_values(["first_order_at", "marketplace", "seller_sku"], kind="stable")
    for c in ("first_order_at", "last_order_at"):
        df[c] = fmt_ts(df[c])
    os.makedirs(a.out_dir, exist_ok=True)
    path = os.path.join(a.out_dir, "stg_unique_sku.csv")
    df[COLS].to_csv(path, index=False)
    assert not df.duplicated(["marketplace", "seller_sku", "marketplace_sku"]).any()
    log.info("written %s  %d rows", path, len(df))
    log.info("dq_note counts: %s", df["dq_note"].str.split(",").explode().replace("", pd.NA)
             .value_counts().to_dict())


if __name__ == "__main__":
    main()
