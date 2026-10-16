"""Step 1 - TikTok + Tokopedia (shared "OrderSKUList" export) -> stg_tiktok.csv, stg_tokopedia.csv.

Input  : raw/tiktok_tokopedia/*.xlsx   (row 1 header, row 2 = column description row, dropped)
Output : stg/stg_tiktok.csv, stg/stg_tokopedia.csv
Rows are routed by the `Purchase Channel` column (not the file name).
Sorted by Created Time asc, then Order ID.
"""
import logging
import os

from common import stg, step1


def main():
    a = step1.args(__doc__, "tiktok_tokopedia")
    df = stg.read_files(a.files, 0, "order_id", a.workers)
    df = df[df["order_id"].str.fullmatch(r"\d+", na=False)]     # drops the description row
    channel = df["purchase_channel"].str.strip().str.lower()
    for key, table in (("tiktok", "stg_tiktok"), ("tokopedia", "stg_tokopedia")):
        part = df[channel == key].copy()
        part = stg.finalize(part, table, key.upper(), "order_id", "created_time")
        stg.write(part, os.path.join(a.out_dir, table + ".csv"))
    unknown = (~channel.isin(["tiktok", "tokopedia"])).sum()
    if unknown:
        logging.warning("%d rows with unknown Purchase Channel skipped", unknown)


if __name__ == "__main__":
    main()
