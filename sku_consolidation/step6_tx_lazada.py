"""Step 6 - LAZADA: stg_lazada.csv -> transaction/t_order_lazada.csv + t_order_detail_lazada.csv.

Bundle SKU lines (m_sku.bundle_flag) are broken down into their components from m_sku_bundle:
quantity = order qty x component qty; gross value (gmv_1) and discounts are split by the ratio of
component price x qty (equal split by qty when a component price is missing -> dq_flag 'equal_split').
"""
from common import tx

if __name__ == "__main__":
    tx.run("LAZADA", tx.args(__doc__))
