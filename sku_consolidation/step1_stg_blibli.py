"""Step 1 - Blibli: merge bulk-order downloads into stg/stg_blibli.csv.

Input  : raw/blibli/*.xlsx   (sheet "Data"; the "full year" seller-analytics dashboard has no
                              'SKU Blibli' column and is skipped)
Output : stg/stg_blibli.csv
Sorted by Tanggal pesanan asc, then Nomor pesanan.
"""
import logging
import os

from common import stg, step1


def main():
    a = step1.args(__doc__, "blibli")
    df = stg.read_files(a.files, "Data", "sku_blibli", a.workers)
    for f, n in df.groupby("source_file").size().items():
        if n == 1000:
            logging.warning("%s has exactly 1000 rows - possible export cap", f)
    df = stg.finalize(df, "stg_blibli", "BLIBLI", "nomor_pesanan", "tanggal_pesanan")
    stg.write(df, os.path.join(a.out_dir, "stg_blibli.csv"))


if __name__ == "__main__":
    main()
