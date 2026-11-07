"""SKU text rules used where svc writes the SKU master itself (SKU review, bundle upload).

Copied from airflow/dags/sku/rules.py (clean_text, clean_sku, sku_type) so a SKU svc registers is
keyed and classified exactly like one the process_sku DAG creates. Keep the two in sync.
"""
import re

CHANNEL_PREFIX = re.compile(r'^(TKP|TTS|LZD|SHP|BLI)[_\-]', re.I)
MULTIPLIER = re.compile(r'^((?:\d+X)+)')
MULTIPACK_NAME = re.compile(r'^([2-9]|\d{2,})\s*x\s|(^|\s)([2-9]|\d{2,})\s*x\s*\d'
                            r'|\d\s*(g|gr|kg)\s*x\s*([2-9]|\d{2,})(?!\d)|set of \d+')
BLANK = {'', '-', 'nan', 'None'}


def clean_text(value) -> str | None:
    """Collapse whitespace; blank, '-', 'nan' -> None."""
    if value is None:
        return None
    text = re.sub(r'\s+', ' ', str(value)).strip()
    return None if text in BLANK else text


def clean_sku(value) -> str | None:
    """R1: trim, upper-case, drop the channel prefix (TKP_, TTS_ ...), lower-case multiplier notation."""
    text = clean_text(value)
    if text is None:
        return None
    text = CHANNEL_PREFIX.sub('', text.upper())
    parts = [MULTIPLIER.sub(lambda m: m.group(1).lower(), p.strip()) for p in text.split('+')]
    return '+'.join(parts)


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
