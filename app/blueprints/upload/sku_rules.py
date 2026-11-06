"""SKU classification for SKUs registered from the SKU review.

Copied from airflow/dags/sku/rules.py (sku_type) so a SKU created by a reviewer is classified
exactly like one the process_sku DAG creates. Keep the two in sync.
"""
import re

MULTIPLIER = re.compile(r'^((?:\d+X)+)')
MULTIPACK_NAME = re.compile(r'^([2-9]|\d{2,})\s*x\s|(^|\s)([2-9]|\d{2,})\s*x\s*\d'
                            r'|\d\s*(g|gr|kg)\s*x\s*([2-9]|\d{2,})(?!\d)|set of \d+')


def sku_type(code: str | None, name: str | None = '') -> str:
    """Classify from the SKU code; "37/..." codes carry no pattern, so fall back to the name."""
    name = str(name or '').lower()
    if code is None:
        return 'unknown'
    if '+' in code or code.startswith('BUND') or ' + ' in name:
        return 'bundle'
    if 'NEAREXPIRED' in code or 'expired' in name:
        return 'near_expired'
    if code.endswith('FG') or 'for gift' in name or 'not for sale' in name:
        return 'free_gift'
    if (MULTIPLIER.match(code.upper()) and not code.upper().startswith('1X')) or MULTIPACK_NAME.search(name):
        return 'multipack'
    return 'single'
