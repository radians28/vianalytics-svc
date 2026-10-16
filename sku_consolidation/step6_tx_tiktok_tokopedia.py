"""Step 6 - TikTok + Tokopedia: stg_tiktok.csv / stg_tokopedia.csv -> transaction/t_order_{tiktok,tokopedia}.csv
and t_order_detail_{tiktok,tokopedia}.csv.

Bundle SKU lines (m_sku.bundle_flag) are broken down into their components from m_sku_bundle:
quantity = order qty x component qty; gross value (gmv_1) and discounts are split by the ratio of
component price x qty (equal split by qty when a component price is missing -> dq_flag 'equal_split').
"""
from common import tx

if __name__ == "__main__":
    a = tx.args(__doc__)
    for channel in ("TIKTOK", "TOKOPEDIA"):
        tx.run(channel, a)
