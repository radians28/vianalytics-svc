"""Step 7 - Merge the per-channel step-6 files into the single DDL-shaped transaction tables.

Input  : transaction/by_channel/t_order_{channel}.csv, t_order_detail_{channel}.csv
Output : transaction/t_order.csv            columns of royal_canin.t_order (without the generated
                                            order_date and the defaulted etl_run_id / created_at / updated_at)
         transaction/t_order_detail.csv     columns of royal_canin.t_order_detail (same exclusions)
         transaction/t_order_detail_dq.csv  order_detail_id, dq_flag (lines with equal_split / sku_not_resolved)
         sku_master/m_city.csv              city_id, city_name, province_name (t_order.city_id points here)

order_id / order_detail_id are re-numbered 1..N across all channels (orders by created time, then channel,
then order_no) so they can be loaded straight into the identity columns.
"""
import argparse
import logging
import os

import pandas as pd

from common.config import CHANNELS, SKU_MASTER, TRANSACTION

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("step7")

O_COLS = ["order_id", "channel_id", "order_no", "city_id", "order_status", "order_created_at", "order_paid_at",
          "order_shipped_at", "order_completed_at", "buyer_username", "warehouse_name", "delivery_option",
          "payment_method", "item_line_count", "total_quantity", "shipping_fee", "gmv_2"]
D_COLS = ["order_detail_id", "order_id", "line_key", "platform_sku_id", "sku_id", "seller_sku", "product_name",
          "item_status", "quantity", "return_quantity", "unit_price", "seller_discount", "platform_discount",
          "gmv_1", "unit_sold", "is_bundle"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in-dir", default=os.path.join(TRANSACTION, "by_channel"))
    ap.add_argument("--out-dir", default=TRANSACTION)
    ap.add_argument("--master-dir", default=SKU_MASTER)
    a = ap.parse_args()
    rd = lambda f: pd.read_csv(os.path.join(a.in_dir, f), dtype=str, keep_default_na=False)

    orders = pd.concat([rd("t_order_%s.csv" % c.lower()) for c in CHANNELS], ignore_index=True)
    detail = pd.concat([rd("t_order_detail_%s.csv" % c.lower()) for c in CHANNELS], ignore_index=True)
    orders["channel_id"] = orders["channel_id"].astype(int)

    # m_city
    city = (orders.loc[orders["city_name"] != "", ["city_name", "province_name"]].drop_duplicates()
            .sort_values(["province_name", "city_name"]).reset_index(drop=True))
    city.insert(0, "city_id", range(1, len(city) + 1))
    orders = orders.merge(city, on=["city_name", "province_name"], how="left")
    orders["city_id"] = orders["city_id"].astype("Int64")

    # global ids
    orders = orders.sort_values(["order_created_at", "channel_id", "order_no"], kind="stable").reset_index(drop=True)
    old_to_new = dict(zip(orders["order_id"], range(1, len(orders) + 1)))
    orders["order_id"] = orders["order_id"].map(old_to_new)
    detail["order_id"] = detail["order_id"].map(old_to_new)
    assert detail["order_id"].notna().all(), "detail without order"
    detail["_o"] = detail["order_id"].astype(int)
    detail["_c"] = detail["order_detail_id"].astype(int)
    detail = detail.sort_values(["_o", "_c"], kind="stable").reset_index(drop=True)
    detail["order_detail_id"] = range(1, len(detail) + 1)
    assert not orders.duplicated(["channel_id", "order_no"]).any()
    assert not detail.duplicated(["order_id", "line_key"]).any()

    dq = detail.loc[detail["dq_flag"] != "", ["order_detail_id", "dq_flag"]]
    os.makedirs(a.out_dir, exist_ok=True)
    orders[O_COLS].to_csv(os.path.join(a.out_dir, "t_order.csv"), index=False)
    detail[D_COLS].to_csv(os.path.join(a.out_dir, "t_order_detail.csv"), index=False)
    dq.to_csv(os.path.join(a.out_dir, "t_order_detail_dq.csv"), index=False)
    city.to_csv(os.path.join(a.master_dir, "m_city.csv"), index=False)
    log.info("t_order %d rows | t_order_detail %d rows | detail dq %d rows | m_city %d rows",
             len(orders), len(detail), len(dq), len(city))
    log.info("orders per channel: %s", orders["channel_id"].map({v["channel_id"]: k for k, v in CHANNELS.items()})
             .value_counts().to_dict())


if __name__ == "__main__":
    main()
