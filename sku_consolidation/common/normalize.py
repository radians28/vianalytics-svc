"""Map a stg_* frame (text) to one standard line-level frame, whatever the marketplace."""
import logging

import numpy as np
import pandas as pd

from .config import PY_TS, STG_MAP, STG
from .parsers import clean_text, parse_money, parse_ts, shopee_listing_key

log = logging.getLogger("normalize")

STG_FILES = {                       # channel_code -> (stg csv, STG_MAP key)
    "SHOPEE": ("stg_shopee.csv", "SHOPEE"),
    "TOKOPEDIA": ("stg_tokopedia.csv", "TIKTOK_TOKOPEDIA"),
    "TIKTOK": ("stg_tiktok.csv", "TIKTOK_TOKOPEDIA"),
    "LAZADA": ("stg_lazada.csv", "LAZADA"),
    "BLIBLI": ("stg_blibli.csv", "BLIBLI"),
}


def load_stg(channel, stg_dir=STG):
    import os
    fn, _ = STG_FILES[channel]
    return pd.read_csv(os.path.join(stg_dir, fn), dtype=str, keep_default_na=False)


def _col(df, name):
    if name is None or name not in df.columns:
        return pd.Series(pd.NA, index=df.index, dtype="string")
    return df[name].astype("string")


def normalize(df, channel):
    m = STG_MAP[STG_FILES[channel][1]]
    fmt = PY_TS[channel]
    n = pd.DataFrame(index=df.index)
    n["order_no"] = clean_text(_col(df, m["order_no"]))
    for k, src in (("created_at", "created"), ("paid_at", "paid"),
                   ("shipped_at", "shipped"), ("completed_at", "completed")):
        n[k] = parse_ts(_col(df, m[src]), fmt)
    n["status"] = clean_text(_col(df, m["status"]))
    n["item_status"] = clean_text(_col(df, m["item_status"]))
    n["seller_sku"] = clean_text(_col(df, m["seller_sku"]))
    n["product_name"] = clean_text(_col(df, m["product_name"]))
    n["variation"] = clean_text(_col(df, m["variation"]))
    if channel == "SHOPEE":     # no platform item id in the export
        n["platform_sku"] = shopee_listing_key(n["product_name"], n["variation"])
    else:
        n["platform_sku"] = clean_text(_col(df, m["platform_sku"]))

    money = lambda key: parse_money(_col(df, m[key]), m["money"])
    if m["qty"]:
        q = pd.to_numeric(_col(df, m["qty"]), errors="coerce")
        if q.isna().any():
            log.warning("%s: %d lines with non-numeric quantity -> 0", channel, q.isna().sum())
        n["quantity"] = q.fillna(0).astype(int)
    else:
        n["quantity"] = 1                     # Lazada: one export row per unit
    ret = pd.to_numeric(_col(df, m["return_qty"]), errors="coerce") if m["return_qty"] else 0
    n["return_quantity"] = pd.Series(ret, index=df.index).fillna(0).clip(lower=0).astype(int)
    n["unit_price"] = money("unit_price").abs()
    n["seller_discount"] = money("seller_discount").abs() if m["seller_discount"] else np.nan
    n["platform_discount"] = money("platform_discount").abs() if m["platform_discount"] else np.nan
    n["gmv_1"] = (n["unit_price"] * n["quantity"]).round(2)       # gross line value, before discounts
    n["buyer"] = clean_text(_col(df, m["buyer"]))
    n["warehouse"] = clean_text(_col(df, m["warehouse"]))
    n["delivery_option"] = clean_text(_col(df, m["delivery"]))
    n["payment_method"] = clean_text(_col(df, m["payment"]))
    n["city"] = clean_text(_col(df, m["city"]))
    n["province"] = clean_text(_col(df, m["province"]))
    n["shipping_fee"] = money("shipping_fee") if m["shipping_fee"] else np.nan
    n["order_total"] = money("order_total")
    n["source_file"] = df["source_file"]
    n["source_row_no"] = df["source_row_no"]

    # line key: marketplace line id, else <platform sku or seller sku>:<n-th occurrence in order>
    if m["line_key"]:
        n["line_key"] = clean_text(_col(df, m["line_key"]))
    else:
        base = n["platform_sku"].fillna(n["seller_sku"]).fillna("NA")
        n["line_key"] = base + ":" + (base.groupby([n["order_no"], base]).cumcount() + 1).astype(str)
    return n
