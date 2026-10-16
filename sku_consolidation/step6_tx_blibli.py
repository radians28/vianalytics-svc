"""Step 6 - BLIBLI: stg_blibli.csv -> transaction/t_order_blibli.csv + t_order_detail_blibli.csv.

Bundle SKU lines (m_sku.bundle_flag) are broken down into their components from m_sku_bundle:
quantity = order qty x component qty; gross value (gmv_1) and discounts are split by the ratio of
component price x qty (equal split by qty when a component price is missing -> dq_flag 'equal_split').
"""
from common import tx

if __name__ == "__main__":
    tx.run("BLIBLI", tx.args(__doc__))
