"""
Stage 1 - Extract unique product listings per merchant from raw order exports.

Input  : raw/<source>/  (order list exports, Jan-Sep 2026)
Output : output/01_unique_products.csv

Columns: merchant, product_name, seller_sku, merchant_sku, first_order_date

Grain  : one row per unique (merchant, product_name, seller_sku, merchant_sku)
         with the earliest order timestamp that combination was seen in.

Source mapping (raw column -> standard column)
-------------------------------------------------------------------------------
merchant    file(s)                     product_name  seller_sku           merchant_sku   order date
Tokopedia   raw/tiktok_tokopedia/*.xlsx Product Name  Seller SKU           SKU ID         Created Time
TikTok      raw/tiktok_tokopedia/*.xlsx Product Name  Seller SKU           SKU ID         Created Time
Lazada      raw/lazada/*.xlsx           itemName      sellerSku            lazadaSku      createTime
Blibli      raw/blibli/*.xlsx  (Data)   Nama produk   SKU seller           SKU Blibli     Tanggal pesanan
Shopee      raw/shopee/*.xlsx           Nama Produk   Nomor Referensi SKU  (*)            Waktu Pesanan Dibuat

TikTok and Tokopedia share the TikTok Shop "OrderSKUList" export format. Rows
are routed to a merchant by the `Purchase Channel` column, not by file name,
so any OrderSKUList export can be dropped into raw/tiktok_tokopedia/.

(*) Shopee's order export has no platform item/model ID, and `SKU Induk` is
    seller-entered (it changed together with the seller SKU in the Apr-2026
    recode to "37/..." codes). The stable identifier is the listing itself, so
    merchant_sku = "SHP_" + md5(product name | variation)[:12].

Usage:
    python 01_extract_unique_products.py [--raw raw] [--out output]
                                         [--start 2026-01-01] [--end 2026-09-30]
"""

import argparse
import glob
import hashlib
import logging
import os
import warnings

import pandas as pd

warnings.filterwarnings("ignore", category=UserWarning)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("stage1")

OUT_COLS = ["merchant", "product_name", "seller_sku", "merchant_sku", "first_order_date"]


def read_any(path, sheet=0):
    """Read xlsx/xls/csv as strings. calamine tolerates the broken <dimension>
    tags in TikTok/Tokopedia exports that make openpyxl see a single column."""
    if path.lower().endswith(".csv"):
        return pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])
    return pd.read_excel(path, sheet_name=sheet, dtype=str, engine="calamine")


def files(raw, folder, patterns=("*.xlsx", "*.xls", "*.csv")):
    out = []
    for p in patterns:
        out += glob.glob(os.path.join(raw, folder, p))
    return sorted(f for f in out if not os.path.basename(f).startswith("~$"))


def standardise(df, merchant, name, seller, platform, date, date_fmt=None, dayfirst=False):
    out = pd.DataFrame({
        "merchant": merchant,
        "product_name": df[name],
        "seller_sku": df[seller],
        "merchant_sku": df[platform],
        "order_date": pd.to_datetime(df[date], format=date_fmt, dayfirst=dayfirst, errors="coerce"),
    })
    return out


# --------------------------------------------------------------------------- #
# Per-merchant loaders
# --------------------------------------------------------------------------- #
def load_tiktok_tokopedia(raw):
    frames = []
    for f in files(raw, "tiktok_tokopedia"):
        df = read_any(f)
        # Row 0 of OrderSKUList exports is a column-description row.
        df = df[df["Order ID"].str.fullmatch(r"\d+", na=False)]
        channel = df["Purchase Channel"].str.strip().str.lower()
        for merchant, key in (("Tokopedia", "tokopedia"), ("TikTok", "tiktok")):
            part = df[channel == key]
            if len(part):
                frames.append(standardise(part, merchant, "Product Name", "Seller SKU", "SKU ID",
                                          "Created Time", "%d/%m/%Y %H:%M:%S"))
        unknown = df[~channel.isin(["tokopedia", "tiktok"])]
        if len(unknown):
            log.warning("%s: %d rows with unknown Purchase Channel skipped", f, len(unknown))
        log.info("read %-50s %7d rows", os.path.basename(f), len(df))
    return frames


def load_lazada(raw):
    frames = []
    for f in files(raw, "lazada"):
        df = read_any(f)
        if "sellerSku" not in df.columns:  # e.g. dashboard/metric exports
            log.info("skip %s (not an order list)", os.path.basename(f))
            continue
        frames.append(standardise(df, "Lazada", "itemName", "sellerSku", "lazadaSku",
                                  "createTime", "%d %b %Y %H:%M"))
        log.info("read %-50s %7d rows", os.path.basename(f), len(df))
    return frames


def load_blibli(raw):
    frames = []
    # Blibli bulk-order exports: order lines in sheet "Data" (sheet "Legend" = field docs).
    for f in files(raw, "blibli", patterns=("*.xlsx",)):
        df = read_any(f, sheet="Data")
        if "SKU Blibli" not in df.columns:
            log.info("skip %s (not an order list)", os.path.basename(f))
            continue
        frames.append(standardise(df, "Blibli", "Nama produk", "SKU seller", "SKU Blibli",
                                  "Tanggal pesanan", "%d/%m/%Y %H:%M"))
        log.info("read %-50s %7d rows", os.path.basename(f), len(df))
    return frames


def shopee_listing_key(name, variation):
    """Deterministic surrogate platform key: SHP_ + 12 hex of normalised name|variation."""
    norm = (name.fillna("").str.lower().str.replace(r"\s+", " ", regex=True).str.strip() + "|" +
            variation.fillna("").str.lower().str.strip())
    return "SHP_" + norm.map(lambda s: hashlib.md5(s.encode("utf-8")).hexdigest()[:12])


def load_shopee(raw):
    frames = []
    for f in files(raw, "shopee"):
        df = read_any(f)
        if "Nomor Referensi SKU" not in df.columns:  # e.g. traffic_overview
            log.info("skip %s (not an order list)", os.path.basename(f))
            continue
        df["_platform"] = shopee_listing_key(df["Nama Produk"], df["Nama Variasi"])
        frames.append(standardise(df, "Shopee", "Nama Produk", "Nomor Referensi SKU", "_platform",
                                  "Waktu Pesanan Dibuat", "%Y-%m-%d %H:%M"))
        log.info("read %-50s %7d rows", os.path.basename(f), len(df))
    return frames


LOADERS = [load_tiktok_tokopedia, load_lazada, load_blibli, load_shopee]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="raw")
    ap.add_argument("--out", default="output")
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default="2026-09-30")
    a = ap.parse_args()

    frames = [f for loader in LOADERS for f in loader(a.raw)]
    df = pd.concat(frames, ignore_index=True)
    total = len(df)

    # Light technical cleanup only (business cleansing happens in stage 2).
    for c in ("product_name", "seller_sku", "merchant_sku"):
        df[c] = df[c].astype("string").str.replace(r"\s+", " ", regex=True).str.strip()
        df.loc[df[c].isin(["", "-", "nan", "None"]), c] = pd.NA

    bad_date = df["order_date"].isna().sum()
    if bad_date:
        log.warning("%d rows with unparseable order date dropped", bad_date)
    df = df[df["order_date"].notna()]
    in_range = df["order_date"].between(pd.Timestamp(a.start), pd.Timestamp(a.end) + pd.Timedelta(days=1),
                                        inclusive="left")
    log.info("%d rows outside %s..%s dropped", (~in_range).sum(), a.start, a.end)
    df = df[in_range]

    key = ["merchant", "product_name", "seller_sku", "merchant_sku"]
    uniq = (df.groupby(key, dropna=False, as_index=False)["order_date"].min()
              .rename(columns={"order_date": "first_order_date"})
              .sort_values(["merchant", "merchant_sku", "first_order_date"]))
    uniq = uniq[OUT_COLS]

    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "01_unique_products.csv")
    uniq.to_csv(path, index=False, date_format="%Y-%m-%d %H:%M:%S")

    log.info("order lines read: %d -> unique product rows: %d", total, len(uniq))
    summary = df.groupby("merchant")["order_date"].agg(["count", "min", "max"])
    summary["unique_rows"] = uniq.groupby("merchant").size()
    log.info("per merchant:\n%s", summary.to_string())
    log.info("written %s", path)


if __name__ == "__main__":
    main()
