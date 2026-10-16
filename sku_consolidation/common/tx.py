"""Shared step-6 logic: stg_* -> t_order / t_order_detail with bundle explosion."""
import argparse
import logging
import os
import warnings

import numpy as np
import pandas as pd

from . import normalize as nz
from .config import CHANNELS, GMV2_DEDUP, SKU_MASTER, STG, TRANSACTION
from .parsers import clean_sku, fmt_ts

warnings.filterwarnings("ignore", category=UserWarning)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("tx")

ID_BASE = 10 ** 9           # ids are channel_id * 1e9 + sequence -> unique across channel files


def args(description):
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--stg-dir", default=STG)
    ap.add_argument("--master-dir", default=SKU_MASTER)
    ap.add_argument("--out-dir", default=os.path.join(TRANSACTION, "by_channel"))
    return ap.parse_args()


class Masters:
    def __init__(self, d):
        rd = lambda f, **k: pd.read_csv(os.path.join(d, f), keep_default_na=False, **k)
        self.platform = rd("m_platform_sku.csv", dtype={"merchant_sku": str})
        self.alias = rd("m_sku_alias.csv", dtype={"sku_code": str})
        self.sku = rd("m_sku.csv", dtype=str)
        bom = rd("m_sku_bundle.csv", dtype={"component_sku_code": str})
        bom["weight"] = pd.to_numeric(bom["price_ratio"], errors="coerce")        # price ratio from step 5
        bom["equal_split"] = bom["dq_flag"].str.contains("equal_split")
        bom["is_last"] = bom.groupby("bundle_sku_id")["component_seq"].transform("max") == bom["component_seq"]
        self.bom = bom
        self.bundle_ids = set(bom["bundle_sku_id"])


def resolve(lines, channel, ms):
    cid = CHANNELS[channel]["channel_id"]
    pl = ms.platform[ms.platform["channel_id"] == cid].set_index("merchant_sku")
    lines["platform_sku_id"] = lines["platform_sku"].map(pl["platform_sku_id"])
    lines["sku_id"] = lines["platform_sku"].map(pl["sku_id"])
    alias_id = lines["seller_sku"].map(lambda s: clean_sku(s)).map(ms.alias.set_index("sku_code")["sku_id"])
    lines["sku_id"] = lines["sku_id"].fillna(alias_id)
    miss = lines["sku_id"].isna().sum()
    if miss:
        log.warning("%s: %d lines could not be resolved to a SKU", channel, miss)
    lines["is_bundle"] = lines["sku_id"].isin(ms.bundle_ids)
    return lines


def explode_bundles(lines, ms):
    """Replace each bundle line by one line per component; gross value and discounts split by weight."""
    plain = lines[~lines["is_bundle"]].copy()
    plain["dq_flag"] = np.where(plain["sku_id"].isna(), "sku_not_resolved", "")
    b = lines[lines["is_bundle"]].copy()
    if b.empty:
        return plain
    b["_line"] = np.arange(len(b))
    bom = ms.bom[["bundle_sku_id", "component_seq", "component_sku_id", "qty", "weight", "equal_split", "is_last"]]
    e = b.merge(bom, left_on="sku_id", right_on="bundle_sku_id", how="left")
    e["share"] = e["weight"] / e.groupby("_line")["weight"].transform("sum")
    e["line_key"] = e["line_key"] + "#" + e["component_seq"].astype(str)
    e["quantity"] = e["quantity"] * e["qty"]
    e["return_quantity"] = e["return_quantity"] * e["qty"]
    for c in ("gmv_1", "seller_discount", "platform_discount"):
        part = (e[c] * e["share"]).round(2)
        rest = e[c] - part.groupby(e["_line"]).transform("sum")        # rounding remainder -> last component
        e[c] = (part + rest.where(e["is_last"], 0)).round(2)
    e["unit_price"] = (e["gmv_1"] / e["quantity"].where(e["quantity"] > 0)).round(2)
    e["sku_id"] = e["component_sku_id"]
    e["dq_flag"] = np.where(e["equal_split"], "equal_split", "")
    e = e.drop(columns=["bundle_sku_id", "component_seq", "component_sku_id", "qty", "weight",
                        "equal_split", "is_last", "share", "_line"])
    return pd.concat([plain, e], ignore_index=True)


def build_orders(lines, channel):
    g = lines.groupby("order_no", sort=False)
    first = lambda c: g[c].first()
    dedup = GMV2_DEDUP[channel]
    amount = (lambda c: g[c].first()) if dedup else (lambda c: g[c].sum(min_count=1))
    o = pd.DataFrame({
        "order_created_at": g["created_at"].min(),
        "order_status": first("status"), "order_paid_at": g["paid_at"].min(),
        "order_shipped_at": g["shipped_at"].min(), "order_completed_at": g["completed_at"].max(),
        "buyer_username": first("buyer"), "warehouse_name": first("warehouse"),
        "delivery_option": first("delivery_option"), "payment_method": first("payment_method"),
        "city_name": first("city"), "province_name": first("province"),
        "item_line_count": g.size(), "total_quantity": g["quantity"].sum(),
        "shipping_fee": amount("shipping_fee"), "gmv_2": amount("order_total"),
    })
    return o


def run(channel, a):
    cid = CHANNELS[channel]["channel_id"]
    ms = Masters(a.master_dir)
    raw = nz.load_stg(channel, a.stg_dir)
    lines = nz.normalize(raw, channel)
    bad = lines["created_at"].isna() | lines["order_no"].isna()
    if bad.any():
        log.warning("%s: %d lines without order no / created time dropped", channel, bad.sum())
        lines = lines[~bad]
    lines = lines.sort_values(["created_at", "order_no", "source_file", "source_row_no"], kind="stable")
    lines = resolve(lines.copy(), channel, ms)

    gmv_before = lines["gmv_1"].sum()
    qty_plain = lines.loc[~lines["is_bundle"], "quantity"].sum()
    n_bundle = int(lines["is_bundle"].sum())
    detail = explode_bundles(lines, ms)
    detail["is_bundle"] = detail["is_bundle"].astype(bool)
    assert abs(detail["gmv_1"].sum() - gmv_before) < 1.0, "gmv_1 changed by bundle explosion"
    assert detail.loc[~detail["is_bundle"], "quantity"].sum() == qty_plain
    detail = detail.sort_values(["created_at", "order_no", "source_file", "source_row_no", "line_key"], kind="stable")
    assert not detail.duplicated(["order_no", "line_key"]).any(), "duplicate (order, line_key)"

    orders = build_orders(detail, channel)
    orders = orders.sort_values(["order_created_at"], kind="stable")
    orders.insert(0, "order_id", cid * ID_BASE + np.arange(1, len(orders) + 1))
    orders.insert(1, "channel_id", cid)
    orders = orders.reset_index().rename(columns={"index": "order_no"})
    id_of = orders.set_index("order_no")["order_id"]

    detail["order_id"] = detail["order_no"].map(id_of)
    detail["unit_sold"] = detail["quantity"]
    detail["order_detail_id"] = cid * ID_BASE + np.arange(1, len(detail) + 1)
    d_cols = ["order_detail_id", "order_id", "line_key", "platform_sku_id", "sku_id", "seller_sku", "product_name",
              "item_status", "quantity", "return_quantity", "unit_price", "seller_discount", "platform_discount",
              "gmv_1", "unit_sold", "is_bundle", "dq_flag"]
    for c in ("platform_sku_id", "sku_id"):
        detail[c] = detail[c].astype("Int64")
    for c in ("order_created_at", "order_paid_at", "order_shipped_at", "order_completed_at"):
        orders[c] = fmt_ts(orders[c])
    o_cols = ["order_id", "channel_id", "order_no", "city_name", "province_name", "order_status",
              "order_created_at", "order_paid_at", "order_shipped_at", "order_completed_at", "buyer_username",
              "warehouse_name", "delivery_option", "payment_method", "item_line_count", "total_quantity",
              "shipping_fee", "gmv_2"]

    os.makedirs(a.out_dir, exist_ok=True)
    name = channel.lower()
    orders[o_cols].to_csv(os.path.join(a.out_dir, "t_order_%s.csv" % name), index=False, float_format="%.2f")
    detail[d_cols].to_csv(os.path.join(a.out_dir, "t_order_detail_%s.csv" % name), index=False, float_format="%.2f")
    log.info("%s: %d stg lines (%d bundle lines) -> %d order rows, %d detail rows | gmv_1 %.0f | unresolved sku %d",
             channel, len(lines), n_bundle, len(orders), len(detail), detail["gmv_1"].sum(),
             int(detail["sku_id"].isna().sum()))
