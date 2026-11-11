"""SKU name matching for svc (merge suggestions on the SKU Master page).

Copied from airflow/dags/sku/attributes.py, matcher.py and rules.normalise_name, so svc ranks SKUs
exactly like the process_sku / rematch DAGs rank review candidates: TF-IDF char n-grams (3..5) and
cosine similarity, weighted by species / life stage / size / pack quantity. Keep the copies in sync.
"""
import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------- attributes.py
CATEGORIES = ('species', 'stage', 'size', 'qty')

FACTOR_MATCH = 1.0
FACTOR_ONE_MISSING = 0.95
FACTOR_BOTH_MISSING = 0.9
FACTOR_MISMATCH = 0.7

# whole words of the cleaned name -> value
SPECIES_WORDS = {
    'cat': ('cat', 'cats', 'kucing', 'kitten', 'kittens', 'feline', 'babycat', 'kitty',
            'fhn', 'fbn', 'fcn'),
    'dog': ('dog', 'dogs', 'anjing', 'puppy', 'puppies', 'canine', 'babydog',
            'shn', 'bhn', 'ccn'),
}
STAGE_WORDS = {
    'young': ('kitten', 'kittens', 'kit', 'puppy', 'puppies', 'junior', 'baby', 'babycat',
              'babydog', 'starter', 'anak'),
    'adult': ('adult', 'dewasa'),
    'senior': ('senior', 'ageing', 'aging', 'mature', 'tua', 'lansia'),
}
# "adult+8", "adult 8+", "mature 7+" are senior formulas, not adult ones
SENIOR_RE = re.compile(r'\b(?:adult|mature|ageing|aging)\s*(?:\+\s*\d+|\d+\s*\+)')

_UNITS = {
    'g': ('g', 1), 'gr': ('g', 1), 'grm': ('g', 1), 'gram': ('g', 1), 'grams': ('g', 1),
    'k': ('g', 1000), 'kg': ('g', 1000), 'kgs': ('g', 1000), 'kilo': ('g', 1000),
    'ml': ('ml', 1), 'cc': ('ml', 1),
    'l': ('ml', 1000), 'lt': ('ml', 1000), 'ltr': ('ml', 1000), 'liter': ('ml', 1000), 'litre': ('ml', 1000),
}
_UNIT = '|'.join(sorted(_UNITS, key=len, reverse=True))
_NUM = r'\d+(?:\.\d+)?'
SIZE = rf'({_NUM})\s*({_UNIT})(?![a-z])'
SIZE_RE = re.compile(SIZE)
# 12x85g / 12 x 85 gr   and   85g x 12 / 85g x 6 pouches; the count is not itself a size
COUNT_SIZE_RE = re.compile(rf'(?<![\d.])(\d+)\s*[x×*]\s*{SIZE}')
SIZE_COUNT_RE = re.compile(rf'{SIZE}\s*[x×*]\s*(\d+)(?![\d.])(?!\s*(?:{_UNIT})(?![a-z]))')
PACK_RE = re.compile(r'\bisi\s*(\d+)\b|(?<![\d.])(\d+)\s*(?:pcs|pc|pouch|pouches|sachet|sachets|kaleng|can|cans|box|boxes)\b')
# master names end with the carton count and unit: "FHN KITTEN 2K (6)", "... (24) - PCS"
CARTON_RE = re.compile(r'\(\s*\d+\s*\)\s*(?:-\s*(?:pcs|box)\s*)?$')


@dataclass(frozen=True)
class Attrs:
    species: frozenset
    stage: frozenset
    size: frozenset
    qty: frozenset


EMPTY = Attrs(frozenset(), frozenset(), frozenset(), frozenset())


def _clean(name) -> str:
    s = str(name or '').lower()
    s = re.sub(r'(?<=\d),(?=\d)', '.', s)            # 1,5 kg -> 1.5 kg
    return CARTON_RE.sub(' ', s.strip())


def _size(amount: str, unit: str) -> tuple:
    kind, factor = _UNITS[unit]
    value = round(float(amount) * factor, 3)
    return kind, int(value) if value == int(value) else value


def extract(name) -> Attrs:
    s = _clean(name)
    if not s:
        return EMPTY

    sizes, qtys = set(), set()

    def count_size(m):
        qtys.add(int(m.group(1)))
        sizes.add(_size(m.group(2), m.group(3)))
        return ' '

    def size_count(m):
        sizes.add(_size(m.group(1), m.group(2)))
        qtys.add(int(m.group(3)))
        return ' '

    def single(m):
        sizes.add(_size(m.group(1), m.group(2)))
        return ' '

    def pack(m):
        n = int(m.group(1) or m.group(2))
        if n > 1:                                     # "1 box" of 12x85g is one pack, not a count
            qtys.add(n)
        return ' '

    s = COUNT_SIZE_RE.sub(count_size, s)
    s = SIZE_COUNT_RE.sub(size_count, s)
    s = SIZE_RE.sub(single, s)
    s = PACK_RE.sub(pack, s)

    stages = set()
    if SENIOR_RE.search(s):
        stages.add('senior')
        s = SENIOR_RE.sub(' ', s)
    words = set(re.findall(r'[a-z]+', s))
    species = {k for k, kws in SPECIES_WORDS.items() if words.intersection(kws)}
    stages |= {k for k, kws in STAGE_WORDS.items() if words.intersection(kws)}
    return Attrs(frozenset(species), frozenset(stages), frozenset(sizes), frozenset(qtys))


def factor(a: frozenset, b: frozenset) -> float:
    if a and b:
        return FACTOR_MATCH if a & b else FACTOR_MISMATCH
    if a or b:
        return FACTOR_ONE_MISSING
    return FACTOR_BOTH_MISSING


def multiplier(a: Attrs, b: Attrs) -> tuple[float, dict]:
    """(product of the category factors, factor per category)."""
    factors = {c: factor(getattr(a, c), getattr(b, c)) for c in CATEGORIES}
    total = 1.0
    for f in factors.values():
        total *= f
    return total, factors


# ---------------------------------------------------------------- rules.normalise_name
def normalise_name(name) -> str:
    """Product name for similarity: lower-case, split digits from letters, symbols dropped."""
    s = str(name or '').lower()
    s = re.sub(r'(?<=\d),(?=\d)', '.', s)                       # 1,5 -> 1.5
    s = re.sub(r'(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)', ' ', s)    # 400g -> 400 g, x12 -> x 12
    s = re.sub(r'[^a-z0-9.\s]', ' ', s)                         # scrub symbols, keep spacing
    s = re.sub(r'(?<!\d)\.|\.(?!\d)', ' ', s)                   # '.' only inside decimals
    return re.sub(r'\s+', ' ', s).strip()


# ---------------------------------------------------------------- matcher.py
MATCH_DISTANCE = 0.45
TOP_N = 3
POOL = 50          # names re-scored with attributes, taken by cosine


@dataclass
class Candidate:
    sku_id: int
    sku_master_code: str
    name: str
    score: float                     # cosine x attribute multiplier
    cosine: float | None = None      # n-gram score alone
    factors: dict = field(default_factory=dict)

    def as_json(self) -> dict:
        return {'sku_id': self.sku_id, 'sku_master_code': self.sku_master_code,
                'name': self.name, 'score': self.score, 'cosine': self.cosine,
                'factors': self.factors}


class NameMatcher:
    """Names of the master SKUs and of their marketplace listings, one vector per (sku, name)."""

    def __init__(self, names: list[tuple[int, str, str]]):
        """names: (sku_id, sku_master_code, product name) - several names per SKU are fine."""
        from sklearn.feature_extraction.text import TfidfVectorizer

        seen, rows = set(), []
        for sku_id, code, name in names:
            norm = normalise_name(name)
            if norm and (sku_id, norm) not in seen:
                seen.add((sku_id, norm))
                rows.append((sku_id, code, name, norm, extract(name)))
        self.rows = rows
        self.vectorizer = None
        if rows:
            self.vectorizer = TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5), sublinear_tf=True)
            self.matrix = self.vectorizer.fit_transform([r[3] for r in rows])

    def top(self, name: str | None, n: int = TOP_N) -> list[Candidate]:
        """Best-scoring distinct SKUs for `name` by adjusted score, highest first."""
        norm = normalise_name(name)
        if not norm or self.vectorizer is None:
            return []
        attrs = extract(name)
        cosines = (self.matrix @ self.vectorizer.transform([norm]).T).toarray().ravel()
        scored = []
        for i in cosines.argsort()[::-1][:POOL]:
            cosine = float(min(cosines[i], 1.0))
            if cosine <= 0:
                break
            mult, factors = multiplier(attrs, self.rows[i][4])
            scored.append((cosine * mult, cosine, factors, i))
        scored.sort(key=lambda s: s[0], reverse=True)

        best: dict[int, Candidate] = {}
        for score, cosine, factors, i in scored:
            sku_id, code, label, _, _ = self.rows[i]
            if sku_id not in best:
                best[sku_id] = Candidate(sku_id, code, label, round(score, 4), round(cosine, 4), factors)
                if len(best) == n:
                    break
        return list(best.values())


def is_close(candidate: Candidate | None) -> bool:
    return candidate is not None and 1.0 - candidate.score <= MATCH_DISTANCE
