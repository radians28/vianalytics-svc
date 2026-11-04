"""Step 1 - Traffic: merge all daily traffic exports of every channel into stg/stg_traffic.csv.

Input  : raw/traffic/{shopee,lazada,blibli,tiktok_tokopedia}/*
Output : stg/stg_traffic.csv
         (DDL stg_traffic columns channel_code, periode, pengunjung + source_file, source_row_no)
One row per channel per day. periode / pengunjung are kept as-is (text); sorted by channel, date asc.
"""
import argparse
import glob
import os
import re

import pandas as pd

from common.config import RAW, STG

COLS = ["channel_code", "periode", "pengunjung", "source_file", "source_row_no"]
DATE_RE = re.compile(r"^(\d{2}-\d{2}-\d{4}|\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})( 00:00:00)?$")


def _read(path, sheet=0):
    df = pd.read_excel(path, sheet_name=sheet, header=None, dtype=str, engine="calamine")
    return df.map(lambda v: v.replace("\x00", "").strip() if isinstance(v, str) else v)


def _rows(df, hdr, date_col, val_col, channel, name):
    out = []
    for i in range(hdr + 1, len(df)):
        d, v = df.iat[i, date_col], df.iat[i, val_col]
        if not isinstance(d, str) or not DATE_RE.match(d):
            continue
        out.append((channel, d[:10] if d[4:5] == "-" else d, v if isinstance(v, str) else "", name, i + 1))
    return out


def _find(df, first, second):
    """Header row holding `first` (date col) and `second` (visitor col, searched right of it)."""
    for i in range(min(len(df), 30)):
        row = list(df.iloc[i])
        if first in row:
            c = row.index(first)
            for j in range(c + 1, len(row)):
                if row[j] == second:
                    return i, c, j
    return None


def shopee(p):
    df = _read(p, "All")
    h = [i for i in range(len(df)) if df.iat[i, 0] == "Date"][-1]   # daily table = last header
    _, c, v = _find(df.iloc[h:].reset_index(drop=True), "Date", "Visitors")
    return _rows(df, h, c, v, "SHOPEE", os.path.basename(p))


def tiktok_tokopedia(channel):
    def f(p):
        df = _read(p)
        i, c, v = _find(df, "Tanggal", "Pengunjung")
        return _rows(df, i, c, v, channel, os.path.basename(p))
    return f


def lazada(p):
    df = _read(p)
    i, c, v = _find(df, "Tanggal", "Pengunjung")
    return _rows(df, i, c, v, "LAZADA", os.path.basename(p))


def blibli(p):
    df = _read(p, "Overall Traffic Funnel")
    i, c, v = _find(df, "Date", "Visit")
    return _rows(df, i, c, v, "BLIBLI", os.path.basename(p))


JOBS = [
    ("shopee", "shopee/*.xlsx", shopee),
    ("tokopedia", "tiktok_tokopedia/Tokped_Traffic_*.xlsx", tiktok_tokopedia("TOKOPEDIA")),
    ("tiktok", "tiktok_tokopedia/Tiktok_Traffic_*.xlsx", tiktok_tokopedia("TIKTOK")),
    ("lazada", "lazada/*.xls", lazada),
    ("blibli", "blibli/*.xlsx", blibli),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-dir", default=os.path.join(RAW, "traffic"))
    ap.add_argument("--out-dir", default=STG)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    frames = []
    for name, pat, fn in JOBS:
        rows = []
        for p in sorted(glob.glob(os.path.join(a.raw_dir, pat))):
            r = fn(p)
            print("%-9s %-75s %4d rows" % (name, os.path.basename(p), len(r)))
            rows += r
        df = pd.DataFrame(rows, columns=COLS)
        key = pd.to_datetime(df["periode"], format="mixed", dayfirst=True)
        df = df.assign(_k=key).sort_values(["_k", "source_file"], kind="stable").drop(columns="_k")
        dup = df.duplicated(["periode"], keep="first")      # overlapping exports -> first file wins
        if dup.any():
            print("%s: %d duplicate days dropped" % (name, dup.sum()))
            df = df[~dup]
        print("   %-9s %4d rows  %s .. %s" % (name, len(df), df["periode"].iloc[0], df["periode"].iloc[-1]))
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    out = os.path.join(a.out_dir, "stg_traffic.csv")
    df.to_csv(out, index=False)
    print("-> %s  %d rows" % (out, len(df)))

if __name__ == "__main__":
    main()
