"""SKU classification / similarity helpers and union-find (ported from 02_cleanse_sku_master.py)."""
import re

SIZE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|gr|g)\b")
MULTIPLIER = re.compile(r"^((?:\d+X)+)")
MULTIPACK_NAME = re.compile(r"^([2-9]|\d{2,})\s*x\s|(^|\s)([2-9]|\d{2,})\s*x\s*\d"
                            r"|\d\s*(g|gr|kg)\s*x\s*([2-9]|\d{2,})(?!\d)|set of \d+")


def sku_type(s, name=""):
    """Classify from the SKU code; "37/..." codes carry no pattern, so fall back to the name."""
    name = str(name or "").lower()
    if s is None:
        return "unknown"
    if "+" in s or s.startswith("BUND") or " + " in name:
        return "bundle"
    if "NEAREXPIRED" in s or "expired" in name:
        return "near_expired"
    if s.endswith("FG") or "for gift" in name or "not for sale" in name:
        return "free_gift"
    if (MULTIPLIER.match(s.upper()) and not s.upper().startswith("1X")) or MULTIPACK_NAME.search(name):
        return "multipack"
    return "single"


def _grams(qty, unit):
    return "%gg" % (float(qty.replace(",", ".")) * (1000 if unit == "kg" else 1))


def sizes(n):
    return {_grams(q, u) for q, u in SIZE.findall(str(n).lower())}


def name_tokens(n):
    n = SIZE.sub(lambda m: " " + _grams(*m.groups()) + " ", str(n).lower())
    n = re.sub(r"[^a-z0-9.]+", " ", n.replace("royal canin", " "))
    return set(n.split())


def similarity(a, b):
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return 0.0
    return round(len(ta & tb) / min(len(ta), len(tb)), 3)


def size_mismatch(a, b):
    sa, sb = sizes(a), sizes(b)
    return bool(sa and sb and not sa & sb)


class DSU:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)
