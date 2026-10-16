"""Timestamp / money / SKU parsing helpers (all times are Asia/Jakarta wall clock)."""
import re

import numpy as np
import pandas as pd

from .config import TS_OUT, TZ_SUFFIX

CHANNEL_PREFIX = re.compile(r"^(TKP|TTS|LZD|SHP|BLI)[_\-]", re.I)
MULTIPLIER = re.compile(r"^((?:\d+X)+)")


def snake(header):
    """'Nomor Referensi SKU' -> 'nomor_referensi_sku' (matches DDL stg column names)."""
    h = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(header))      # camelCase -> camel_case
    return re.sub(r"[^a-z0-9]+", "_", h.lower()).strip("_")


def parse_ts(s, fmt):
    """Naive Jakarta wall-clock text -> datetime64 (NaT for '-', '' or bad text)."""
    s = s.replace({"-": None, "": None})
    return pd.to_datetime(s, format=fmt, errors="coerce")


def fmt_ts(s):
    """datetime64 series -> 'YYYY-MM-DD HH:MM:SS+07' text ('' for NaT)."""
    return s.dt.strftime(TS_OUT).add(TZ_SUFFIX).where(s.notna(), "")


def read_ts(s):
    """Inverse of fmt_ts: text written by this pipeline -> naive datetime64."""
    return pd.to_datetime(s.astype("string").str.replace(r"\+07$", "", regex=True), errors="coerce")


def parse_money(s, style):
    """Text money -> float. 'dot': 'Rp391.000', '-Rp39.100', '414.090'; 'plain': '175898.00'."""
    s = s.astype("string").str.strip()
    if style == "dot":
        neg = s.str.contains("-", na=False)
        digits = s.str.replace(r"[^0-9]", "", regex=True)
        v = pd.to_numeric(digits.replace("", pd.NA), errors="coerce").astype("float64")
        return v.where(~neg, -v)
    s = s.str.replace(r"[^0-9.\-]", "", regex=True)
    return pd.to_numeric(s.replace("", pd.NA), errors="coerce").astype("float64")


def clean_text(s):
    s = s.astype("string").str.replace(r"\s+", " ", regex=True).str.strip()
    return s.mask(s.isin(["", "-", "nan", "None"]))


def clean_sku(s):
    """R1: trim, upper-case, drop channel prefix, lower-case multiplier notation."""
    if s is None or pd.isna(s) or not str(s).strip():
        return None
    s = re.sub(r"\s+", " ", str(s)).strip().upper()
    s = CHANNEL_PREFIX.sub("", s)
    parts = [MULTIPLIER.sub(lambda m: m.group(1).lower(), p.strip()) for p in s.split("+")]
    return "+".join(parts)


def shopee_listing_key(name, variation):
    """Deterministic platform key for Shopee: SHP_ + md5(name|variation)[:12]."""
    import hashlib
    norm = (name.fillna("").str.lower().str.replace(r"\s+", " ", regex=True).str.strip() + "|" +
            variation.fillna("").str.lower().str.strip())
    return "SHP_" + norm.map(lambda x: hashlib.md5(x.encode("utf-8")).hexdigest()[:12])
