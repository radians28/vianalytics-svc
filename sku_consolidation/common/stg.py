"""Shared step-1 logic: read xlsx files -> DDL-shaped stg frame (sorted, de-duplicated)."""
import logging
import os
from concurrent.futures import ProcessPoolExecutor

import pandas as pd

from .config import PY_TS
from .ddl import stg_columns
from .parsers import parse_ts, snake

log = logging.getLogger("stg")


def _read_one(args):
    path, sheet, required = args
    try:
        df = pd.read_excel(path, sheet_name=sheet, dtype=str, engine="calamine")
    except Exception as exc:  # missing sheet etc.
        return path, None, "unreadable (%s)" % exc
    df.columns = [snake(c) for c in df.columns]
    if required not in df.columns:
        return path, None, "not an order list (no '%s' column)" % required
    df["source_row_no"] = df.index + 2          # excel row (header = row 1)
    return path, df, None


def read_files(paths, sheet, required, workers=4):
    jobs = [(p, sheet, required) for p in paths]
    frames = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for fi, (path, df, err) in enumerate(ex.map(_read_one, jobs)):
            name = os.path.basename(path)
            if df is None:
                log.warning("skip %s: %s", name, err)
                continue
            df["source_file"] = name
            df["_fi"] = fi
            log.info("read %-55s %8d rows", name, len(df))
            frames.append(df)
    if not frames:
        raise SystemExit("no order files found")
    return pd.concat(frames, ignore_index=True)


def finalize(df, table, channel_for_ts, order_col, created_col, row_filter=None):
    """Align to DDL columns, drop cross-file duplicates, sort by created asc then order id."""
    cols = stg_columns(table)
    extra = [c for c in df.columns if c not in cols and c not in ("source_file", "source_row_no", "_fi")]
    missing = [c for c in cols if c not in df.columns]
    if extra:
        log.warning("%s: columns not in DDL ignored: %s", table, extra)
    if missing:
        log.warning("%s: DDL columns absent from files (left empty): %s", table, missing)
    for c in missing:
        df[c] = pd.NA
    df = df[cols + ["source_file", "source_row_no", "_fi"]].copy()
    for c in cols:
        df[c] = df[c].astype("string").str.strip().fillna("")

    # same row present in several files (overlapping exports) -> keep the first file's copy
    h = pd.util.hash_pandas_object(df[cols], index=False)
    first_file = df.groupby(h)["_fi"].transform("min")
    dup = df["_fi"] != first_file
    if dup.any():
        log.info("%s: %d cross-file duplicate rows dropped", table, dup.sum())
    df = df[~dup]

    ts = parse_ts(df[created_col], PY_TS[channel_for_ts])
    bad = ts.isna().sum()
    if bad:
        log.warning("%s: %d rows with unparseable %s (sorted last)", table, bad, created_col)
    df = (df.assign(_ts=ts)
            .sort_values(["_ts", order_col, "_fi", "source_row_no"], kind="stable", na_position="last")
            .drop(columns=["_ts", "_fi"]))
    return df


def write(df, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)
    log.info("written %s  %d rows", path, len(df))
