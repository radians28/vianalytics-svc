"""SKU bundling upload: a bundle bill-of-materials file -> royal_canin.m_sku_bundle (svc, no Airflow).

One row per component: bundle SKU, bundle name, line no, component SKU, component name, qty, unit
price. The rules follow the offline builder (sku_consolidation/common/bundle.py, step5_bundle_sku.py):
- codes are cleaned like seller SKUs (clean_sku) and resolved through m_sku_alias; a code that is
  not in the master yet becomes a new SKU (dq_flag from_bundle_master)
- blank or 0 qty -> 1 (qty_missing); the same component twice -> quantities summed (dup_component)
- a free gift (code 37/B..., or a name with "B - ") is priced 0 (free_gift); a blank price counts as
  0 (component_price_missing)
- price_ratio = unit price x qty / bundle total, 8 decimals, the last component takes the rounding
  rest so a bundle sums to exactly 1; a bundle without any price is split by qty (equal_split)
- a component that is itself a bundle stays as it is, one level (nested_bundle), as the order load
  breaks bundles down one level only
- a row whose component is the bundle itself is skipped (the offline master lists single SKUs that
  way); a SKU with only such rows is not a bundle

Every bundle SKU in the file has its components replaced; bundles not in the file are kept.
`preview` validates and reports without writing; `apply` writes in one transaction under the SKU
master advisory lock.

Order lines already loaded keep the components they were split into. Before replacing a bundle,
apply saves its old and new component lists in log_bundle_change (only bundles whose list changes);
the reconsolidate_bundle_orders DAG uses them to rebuild each stored bundle line and split it again
with the new list. The preview reports how many stored order lines use each bundle.
"""
import json
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from app.blueprints.sku_master.master_writes import insert_sku, lock_master, q
from app.blueprints.upload.sku_rules import clean_sku, clean_text, sku_type
from app.common.sheet_reader import SheetError, read_rows
from app.extensions import db

HEADER_SEARCH_ROWS = 10
RATIO_PLACES = Decimal('0.00000001')
FREE_GIFT_CODE = re.compile(r'^37/B\d')
FREE_GIFT_NAME = re.compile(r'(^|[\s\]])B - ')

# Accepted headers per field (lower case, words only). The template's header comes first; the
# others are the offline bundling_master.csv / bundling_price.csv headers and close variants.
COLUMNS = {
    'bundle_sku': ('bundle sku', 'kode sku', 'sku bundle', 'bundle sku no', 'bundle sku number'),
    'bundle_name': ('bundle product name', 'nama sku', 'product name bundle', 'bundle name'),
    'line_no': ('line no', 'component line no', 'line', 'no'),
    'component_sku': ('component sku', 'kode sku base', 'component sku no', 'component sku number', 'sku'),
    'component_name': ('component product name', 'nama sku base', 'component name', 'product name'),
    'qty': ('qty', 'quantity', 'component qty', 'qty base in 1 bundle'),
    'unit_price': ('unit price', 'component unit price', 'component price', 'price'),
}
REQUIRED = ('bundle_sku', 'component_sku', 'qty')
TEMPLATE_HEADERS = ['Bundle SKU', 'Bundle Product Name', 'Line No', 'Component SKU',
                    'Component Product Name', 'Qty', 'Unit Price']


class BundleUploadError(Exception):
    def __init__(self, message: str, code: int = 400, errors: list | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.errors = errors or []


@dataclass
class Component:
    line_no: int
    code: str
    name: str | None
    qty: int
    price: Decimal | None
    flags: list[str] = field(default_factory=list)
    rows: list[int] = field(default_factory=list)
    ratio: Decimal | None = None
    sku_id: int | None = None


@dataclass
class Bundle:
    code: str
    name: str | None
    components: 'OrderedDict[str, Component]' = field(default_factory=OrderedDict)
    sku_id: int | None = None


def _norm(header) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', str(header or '').lower()).strip()


def _header(rows) -> tuple[int, dict[str, int]]:
    for i in range(min(len(rows), HEADER_SEARCH_ROWS)):
        names = [_norm(h) for h in rows[i]]
        positions = {}
        for key, accepted in COLUMNS.items():
            for alias in accepted:                       # the first accepted header found wins
                if alias in names and names.index(alias) not in positions.values():
                    positions[key] = names.index(alias)
                    break
        if all(k in positions for k in REQUIRED):
            return i, positions
    raise BundleUploadError(
        'Header not found. Expected columns: ' + ', '.join(TEMPLATE_HEADERS)
        + ' (Bundle SKU, Component SKU and Qty are required)')


def _number(text: str) -> Decimal:
    """'21958', '21958.50', '21.958' / '21,958' (thousands), '21.958,50' / 'Rp 21.958' -> Decimal."""
    s = re.sub(r'(?i)rp|\s', '', text)
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.') if s.rfind(',') > s.rfind('.') else s.replace(',', '')
    elif re.fullmatch(r'\d{1,3}([.,]\d{3})+', s):
        s = re.sub(r'[.,]', '', s)
    elif ',' in s:
        s = s.replace(',', '.')
    value = Decimal(s)                                   # raises on anything else
    if not value.is_finite():
        raise ValueError(text)
    return value


def _is_free_gift(code: str, name: str | None) -> bool:
    return bool(FREE_GIFT_CODE.match(code) or (name and FREE_GIFT_NAME.search(name)))


@dataclass
class Parsed:
    bundles: 'OrderedDict[str, Bundle]'
    raw: list[dict]                 # stg_sku_bundle rows, as in the file
    errors: list[dict]
    warnings: list[str]


def parse(data: bytes) -> Parsed:
    try:
        rows = read_rows(data)
    except SheetError as err:
        raise BundleUploadError(str(err)) from err
    h, pos = _header(rows)

    def cell(row, key):
        i = pos.get(key)
        return row[i] if i is not None and i < len(row) else None

    bundles: OrderedDict[str, Bundle] = OrderedDict()
    raw, errors, warnings = [], [], []
    line_seen: dict[str, dict[int, int]] = {}
    self_rows: list[int] = []
    for i in range(h + 1, len(rows)):
        row, row_no = rows[i], i + 1
        if not any(v is not None for v in row):
            continue
        values = {k: cell(row, k) for k in COLUMNS}
        raw.append({**values, 'row': row_no})
        bundle_code, component_code = clean_sku(values['bundle_sku']), clean_sku(values['component_sku'])
        bundle_name, component_name = clean_text(values['bundle_name']), clean_text(values['component_name'])

        def err(message):
            errors.append({'row': row_no, 'message': message})

        if bundle_code is None:
            err('Bundle SKU is empty')
            continue
        if component_code is None:
            err('Component SKU is empty')
            continue
        if component_code == bundle_code:
            self_rows.append(row_no)    # a single SKU listed as its own component: not a bundle
            continue

        flags = []
        qty_text = values['qty']
        try:
            qty_value = _number(qty_text) if qty_text is not None else Decimal(0)
            if qty_value < 0 or qty_value != qty_value.to_integral_value():
                raise ValueError
        except (ValueError, ArithmeticError):
            err(f'Qty {qty_text!r} is not a whole number')
            continue
        qty = int(qty_value)
        if qty == 0:
            qty, flags = 1, flags + ['qty_missing']
            warnings.append(f'Row {row_no}: qty is empty or 0, counted as 1')

        price_text = values['unit_price']
        try:
            price = _number(price_text) if price_text is not None else None
            if price is not None and price < 0:
                raise ValueError
        except (ValueError, ArithmeticError):
            err(f'Unit price {price_text!r} is not a valid amount')
            continue
        if _is_free_gift(component_code, component_name):
            price, flags = Decimal(0), flags + ['free_gift']
        elif price is None:
            price, flags = Decimal(0), flags + ['component_price_missing']

        bundle = bundles.get(bundle_code)
        if bundle is None:
            bundle = bundles[bundle_code] = Bundle(bundle_code, bundle_name)
        elif bundle_name and bundle.name and bundle_name != bundle.name:
            warnings.append(f'Row {row_no}: bundle {bundle_code} has another name; '
                            f'"{bundle.name}" is used')
        bundle.name = bundle.name or bundle_name

        line_text = values['line_no']
        if line_text is not None:
            try:
                line_no = int(_number(line_text))
                if line_no <= 0:
                    raise ValueError
            except (ValueError, ArithmeticError):
                err(f'Line no {line_text!r} is not a positive whole number')
                continue
        else:
            line_no = max((c.line_no for c in bundle.components.values()), default=0) + 1
        seen = line_seen.setdefault(bundle_code, {})
        same = bundle.components.get(component_code)
        if line_no in seen and same is None:
            err(f'Line no {line_no} is used twice in bundle {bundle_code} (rows {seen[line_no]} and {row_no})')
            continue
        seen.setdefault(line_no, row_no)

        if same is not None:                             # the component listed twice: one line, qty summed
            same.qty += qty
            same.rows.append(row_no)
            if 'dup_component' not in same.flags:
                same.flags.append('dup_component')
            if price != same.price:
                warnings.append(f'Row {row_no}: {component_code} has another price in bundle {bundle_code}; '
                                f'the first one is used')
            continue
        bundle.components[component_code] = Component(line_no, component_code, component_name, qty, price,
                                                      flags, [row_no])

    if not raw:
        raise BundleUploadError('The file has no component rows under the header')
    if self_rows:
        warnings.insert(0, f'{len(self_rows)} row(s) list a SKU as its own component and were skipped '
                           f'(e.g. row {self_rows[0]}); such a SKU is not a bundle')
    for bundle in bundles.values():
        _ratios(bundle)
    return Parsed(bundles, raw, errors, warnings)


def _ratios(bundle: Bundle):
    comps = sorted(bundle.components.values(), key=lambda c: c.line_no)
    weights = [c.price * c.qty for c in comps]
    total = sum(weights)
    if total <= 0:                                       # no prices at all: split by quantity
        weights = [Decimal(c.qty) for c in comps]
        total = sum(weights)
        for c in comps:
            c.flags.append('equal_split')
    ratios = [(w / total).quantize(RATIO_PLACES, ROUND_HALF_UP) for w in weights]
    ratios[-1] = max(Decimal(0), Decimal(1) - sum(ratios[:-1]))  # rounding rest -> last line
    for c, r in zip(comps, ratios):
        c.ratio = r


# ------------------------------------------------------------------------------------- resolve

def _lookup(codes: set[str]) -> dict[str, int]:
    """seller SKU code -> sku_id via m_sku_alias (and m_sku.master_sku); '1X' prefixes retried bare."""
    candidates = codes | {c[2:] for c in codes if c.startswith('1x')}
    rows = q("""
        SELECT sku_code, sku_id FROM {S}.m_sku_alias WHERE sku_code = ANY(:c)
        UNION ALL
        SELECT master_sku, sku_id FROM {S}.m_sku WHERE master_sku = ANY(:c)
    """, c=list(candidates)).all()
    found = {}
    for code, sku_id in rows:
        found.setdefault(code, sku_id)
    result = {}
    for c in codes:
        sku_id = found.get(c)
        if sku_id is None and c.startswith('1x'):
            sku_id = found.get(c[2:])
        if sku_id is not None:
            result[c] = sku_id
    return result


def _resolve(parsed: Parsed) -> dict:
    """sku_id of every code; returns the SKUs to create and the bundles that already have components."""
    bundles = parsed.bundles
    codes = set(bundles) | {c for b in bundles.values() for c in b.components}
    known = _lookup(codes)
    new: OrderedDict[str, dict] = OrderedDict()
    for b in bundles.values():
        b.sku_id = known.get(b.code)
        if b.sku_id is None and b.code not in new:
            new[b.code] = {'code': b.code, 'name': b.name or b.code, 'role': 'bundle'}
        for c in b.components.values():
            c.sku_id = known.get(c.code)
            if c.sku_id is None and c.code not in new:
                new[c.code] = {'code': c.code, 'name': c.name or c.code, 'role': 'component',
                               'freeGift': 'free_gift' in c.flags}

    owner: dict[int, str] = {}
    for b in bundles.values():
        if b.sku_id is None:
            continue
        if b.sku_id in owner:
            parsed.errors.append({'row': None, 'message': f'Bundles {owner[b.sku_id]} and {b.code} are the '
                                                           f'same SKU in the master; list it once'})
        owner[b.sku_id] = b.code
        for c in b.components.values():
            if c.sku_id == b.sku_id:
                parsed.errors.append({'row': c.rows[0], 'message': f'Component {c.code} is the bundle '
                                                                    f'{b.code} itself in the SKU master'})

    existing = set()
    known_ids = [b.sku_id for b in bundles.values() if b.sku_id is not None]
    component_ids = [c.sku_id for b in bundles.values() for c in b.components.values() if c.sku_id is not None]
    if known_ids or component_ids:
        existing = set(q('SELECT DISTINCT bundle_sku_id FROM {S}.m_sku_bundle WHERE bundle_sku_id = ANY(:ids)',
                         ids=known_ids + component_ids).scalars().all())
    for b in bundles.values():
        for c in b.components.values():
            if (c.code in bundles or c.sku_id in existing) and 'nested_bundle' not in c.flags:
                c.flags.append('nested_bundle')
    return {'new': list(new.values()), 'replaced': [b.code for b in bundles.values() if b.sku_id in existing]}


def affected_lines(sku_ids: list[int]) -> dict[int, int]:
    """Stored order lines per bundle SKU: split bundle lines (one per order line, found like the order
    load resolves a line: seller SKU alias first, else the listing) and lines of the SKU still
    unsplit (it was not a bundle when they were loaded)."""
    if not sku_ids:
        return {}
    rows = q("""
        WITH cand AS (
            SELECT d.order_id, split_part(d.line_key, '#', 1) AS base,
                   CASE WHEN d.is_bundle THEN coalesce(a.sku_id, p.sku_id) ELSE d.sku_id END AS bundle_sku_id
            FROM {S}.t_order_detail d
            LEFT JOIN {S}.m_sku_alias a ON a.sku_code = upper(btrim(d.seller_sku))
            LEFT JOIN {S}.m_platform_sku p ON p.platform_sku_id = d.platform_sku_id
            WHERE (d.is_bundle AND (p.sku_id = ANY(:ids) OR a.sku_id = ANY(:ids)))
               OR (NOT d.is_bundle AND d.sku_id = ANY(:ids))
        )
        SELECT bundle_sku_id, count(DISTINCT (order_id, base)) FROM cand
        WHERE bundle_sku_id = ANY(:ids) GROUP BY bundle_sku_id
    """, ids=list(sku_ids)).all()
    return {sku_id: n for sku_id, n in rows}


def _report(parsed: Parsed, resolved: dict, affected: dict[int, int] | None = None) -> dict:
    bundles = parsed.bundles
    affected = affected or {}
    return {
        'affectedLines': sum(affected.get(b.sku_id, 0) for b in bundles.values() if b.sku_id is not None),
        'bundles': len(bundles),
        'components': sum(len(b.components) for b in bundles.values()),
        'rows': len(parsed.raw),
        'replacedBundles': len(resolved['replaced']),
        'newBundles': len(bundles) - len(resolved['replaced']),
        'newSkus': resolved['new'],
        'errors': parsed.errors,
        'warnings': parsed.warnings,
        'items': [{
            'skuCode': b.code,
            'productName': b.name,
            'skuId': b.sku_id,
            'replaces': b.code in resolved['replaced'],
            'affectedLines': affected.get(b.sku_id, 0) if b.sku_id is not None else 0,
            'components': [{
                'lineNo': c.line_no,
                'sellerSku': c.code,
                'productName': c.name,
                'skuId': c.sku_id,
                'qty': c.qty,
                'unitPrice': float(c.price) if c.price is not None else None,
                'priceRatio': float(c.ratio * 100),
                'dqFlags': c.flags,
            } for c in sorted(b.components.values(), key=lambda c: c.line_no)],
        } for b in bundles.values()],
    }


def preview(data: bytes) -> dict:
    parsed = parse(data)
    resolved = _resolve(parsed)
    known = [b.sku_id for b in parsed.bundles.values() if b.sku_id is not None]
    report = _report(parsed, resolved, affected_lines(known))
    db.session.rollback()                               # read only
    return report


def _bom_json(rows) -> list[dict]:
    return [{'seq': r['seq'], 'component_sku_id': r['component_sku_id'], 'qty': r['qty'],
             'price_ratio': str(r['price_ratio']) if r['price_ratio'] is not None else None,
             'dq_flag': r['dq_flag'] or None} for r in rows]


def _same_bom(old: list[dict] | None, new: list[dict]) -> bool:
    def key(rows):
        return sorted((r['seq'], r['component_sku_id'], r['qty'],
                       None if r['price_ratio'] is None else Decimal(r['price_ratio']).quantize(RATIO_PLACES))
                      for r in rows)
    return old is not None and key(old) == key(new)


def apply(data: bytes, file_name: str, user: str, reconsolidate: bool = False) -> dict:
    parsed = parse(data)
    try:
        lock_master()
        resolved = _resolve(parsed)                     # again under the lock: the master may have moved
        if parsed.errors:
            raise BundleUploadError(f'{len(parsed.errors)} row(s) need fixing before the file can be applied',
                                    400, parsed.errors)

        created = []
        for new in resolved['new']:
            is_bundle = new['role'] == 'bundle'
            kind = 'bundle' if is_bundle else ('free_gift' if new.get('freeGift') else sku_type(new['code'], new['name']))
            sku = insert_sku(new['code'], new['name'], kind, 'from_bundle_master', bundle_flag=is_bundle)
            created.append({'code': new['code'], 'id': sku['sku_id'], 'skuId': sku['sku_master_code'],
                            'role': new['role']})
        ids = {c['code']: c['id'] for c in created}
        for b in parsed.bundles.values():
            b.sku_id = b.sku_id or ids[b.code]
            for c in b.components.values():
                c.sku_id = c.sku_id or ids[c.code]

        bundle_ids = [b.sku_id for b in parsed.bundles.values()]
        q("""
            UPDATE {S}.m_sku SET sku_type = 'bundle', bundle_flag = true
            WHERE sku_id = ANY(:ids) AND (sku_type <> 'bundle' OR NOT bundle_flag)
        """, ids=bundle_ids)

        run_id = q("""
            INSERT INTO {S}.log_etl_run (status, channels, source_files, triggered_by, finished_at)
            VALUES ('SUCCESS', 'BUNDLE', :file, :by, now()) RETURNING run_id
        """, file=file_name, by=user).scalar_one()
        raw = parsed.raw
        q("""
            INSERT INTO {S}.stg_sku_bundle (sku_bundle, product_name_bundle, line_no, sku, product_name, qty,
                                            unit_price, source_file, source_row_no, load_run_id)
            SELECT a, b, c, d, e, f, g, :file, n, :run
            FROM unnest(CAST(:a AS text[]), CAST(:b AS text[]), CAST(:c AS text[]), CAST(:d AS text[]),
                        CAST(:e AS text[]), CAST(:f AS text[]), CAST(:g AS text[]), CAST(:n AS int[]))
                 AS u(a, b, c, d, e, f, g, n)
        """, file=file_name, run=run_id,
          a=[r['bundle_sku'] for r in raw], b=[r['bundle_name'] for r in raw], c=[r['line_no'] for r in raw],
          d=[r['component_sku'] for r in raw], e=[r['component_name'] for r in raw],
          f=[r['qty'] for r in raw], g=[r['unit_price'] for r in raw], n=[r['row'] for r in raw])

        # snapshot the component lists that change, for re-splitting stored order lines
        old_boms: dict[int, list[dict]] = {}
        for r in q("""
            SELECT bundle_sku_id, component_seq AS seq, component_sku_id, qty, price_ratio, dq_flag
            FROM {S}.m_sku_bundle WHERE bundle_sku_id = ANY(:ids) ORDER BY bundle_sku_id, component_seq
        """, ids=bundle_ids).mappings().all():
            old_boms.setdefault(r['bundle_sku_id'], []).append(r)
        changes = []
        for b in parsed.bundles.values():
            old = _bom_json(old_boms[b.sku_id]) if b.sku_id in old_boms else None
            new = _bom_json([{'seq': c.line_no, 'component_sku_id': c.sku_id, 'qty': c.qty, 'price_ratio': c.ratio,
                              'dq_flag': ','.join(c.flags) or None}
                             for c in sorted(b.components.values(), key=lambda c: c.line_no)])
            if not _same_bom(old, new):
                changes.append((b.sku_id, old, new))
        change_ids = [q("""
            INSERT INTO {S}.log_bundle_change (run_id, bundle_sku_id, old_bom, new_bom, status)
            VALUES (:run, :sku, CAST(:old AS jsonb), CAST(:new AS jsonb), :status) RETURNING change_id
        """, run=run_id, sku=sku_id, old=json.dumps(old) if old is not None else None, new=json.dumps(new),
            status='PENDING' if reconsolidate else 'SKIPPED').scalar_one() for sku_id, old, new in changes]

        deleted = q('DELETE FROM {S}.m_sku_bundle WHERE bundle_sku_id = ANY(:ids)', ids=bundle_ids).rowcount
        lines = [(b.sku_id, c) for b in parsed.bundles.values() for c in b.components.values()]
        q("""
            INSERT INTO {S}.m_sku_bundle (bundle_sku_id, component_seq, component_sku_id, component_sku_code,
                                          qty, component_price, price_ratio, dq_flag)
            SELECT * FROM unnest(CAST(:b AS int[]), CAST(:s AS int[]), CAST(:c AS int[]), CAST(:code AS text[]),
                                 CAST(:qty AS int[]), CAST(:p AS numeric[]), CAST(:r AS numeric[]),
                                 CAST(:f AS text[]))
        """, b=[b for b, _ in lines], s=[c.line_no for _, c in lines], c=[c.sku_id for _, c in lines],
          code=[c.code for _, c in lines], qty=[c.qty for _, c in lines], p=[c.price for _, c in lines],
          r=[c.ratio for _, c in lines], f=[','.join(c.flags) or None for _, c in lines])
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    report = _report(parsed, resolved, affected_lines([b.sku_id for b in parsed.bundles.values()]))
    db.session.commit()
    return {**report, 'created': created, 'deletedRows': deleted, 'insertedRows': len(lines), 'runId': run_id,
            'changeIds': change_ids, 'changedBundles': len(change_ids)}
