"""Read the staging column lists straight from ddl_royal_canin.sql so stg CSVs match it."""
import re

from .config import DDL

_META = {"stg_id", "source_file", "source_row_no", "load_run_id", "loaded_at"}


def stg_columns(table):
    text = open(DDL, encoding="utf-8").read()
    m = re.search(r"CREATE TABLE royal_canin\.%s \((.*?)\n\);" % re.escape(table), text, re.S)
    if not m:
        raise ValueError("table %s not found in DDL" % table)
    cols = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("CONSTRAINT"):
            continue
        name = line.split()[0]
        if name not in _META:
            cols.append(name)
    return cols
