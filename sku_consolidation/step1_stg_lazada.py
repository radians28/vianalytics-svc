"""Step 1 - Lazada: merge yearly order exports into stg/stg_lazada.csv.

Input  : raw/lazada/*.xlsx   (sheet 1, header row 1, one row per order item)
Output : stg/stg_lazada.csv
Sorted by createTime asc, then orderNumber.
"""
import os

from common import stg, step1


def main():
    a = step1.args(__doc__, "lazada")
    df = stg.read_files(a.files, 0, "seller_sku", a.workers)
    df = stg.finalize(df, "stg_lazada", "LAZADA", "order_number", "create_time")
    stg.write(df, os.path.join(a.out_dir, "stg_lazada.csv"))


if __name__ == "__main__":
    main()
