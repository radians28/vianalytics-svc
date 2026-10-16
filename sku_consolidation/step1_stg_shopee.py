"""Step 1 - Shopee: merge all monthly order exports into stg/stg_shopee.csv.

Input  : raw/shopee/*.xlsx   (sheet "orders", header row 1, one row per order line)
Output : stg/stg_shopee.csv  (DDL stg_shopee columns + source_file, source_row_no)
Sorted by order created time (Waktu Pesanan Dibuat) asc, then order id (No. Pesanan).
"""
import os

from common import stg, step1


def main():
    a = step1.args(__doc__, "shopee")
    df = stg.read_files(a.files, "orders", "nomor_referensi_sku", a.workers)
    df = stg.finalize(df, "stg_shopee", "SHOPEE", "no_pesanan", "waktu_pesanan_dibuat")
    stg.write(df, os.path.join(a.out_dir, "stg_shopee.csv"))


if __name__ == "__main__":
    main()
