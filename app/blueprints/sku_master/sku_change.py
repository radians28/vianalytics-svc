"""Merge and split of SKU masters (SKU Master page), followed by their stored order lines.

MERGE source B into target A: every seller SKU (m_sku_alias), listing (m_platform_sku), listing
history version and reference of B moves to A, then B is deleted. SPLIT source A: the chosen seller
SKUs and listings move to target T, an existing SKU or a new one.

svc changes the master in one transaction under the SKU master advisory lock (master_writes), logs
the change in royal_canin.log_sku_change with a snapshot of both SKUs, and triggers the Airflow DAG
reassign_sku_orders. That DAG re-points the stored order lines (a line belongs to the SKU of its
cleaned seller SKU, else of its listing - the order load's rule), re-splits bundle lines where a
SKU starts or stops being a bundle, and for a merge deletes B at the end. Until then B is hidden from
the SKU list, search and name matching.

Rules (user decisions): a merge deletes B; a merge of two bundles with different components is
refused; there is no undo - a wrong merge is fixed by a split and the other way round.
"""
import json
from datetime import date, datetime
from decimal import Decimal

from app.blueprints.sku_master.master_writes import insert_sku, lock_master, q
from app.blueprints.upload.sku_rules import clean_sku, sku_type
from app.common.airflow_client import trigger_dag
from app.common.helpers import jakarta_now
from app.common.logger import get_logger
from app.extensions import db

logger = get_logger(__name__)

DAG_ID = 'reassign_sku_orders'
OPEN = ('PENDING', 'RUNNING', 'FAILED')
SELLER_PREFIX = r'^(TKP|TTS|LZD|SHP|BLI)[_-]'
SUGGESTIONS = 3


class SkuChangeError(Exception):
    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code


# --------------------------------------------------------------------------------------- reads

def _sku(sku_id: int) -> dict:
    row = q("""
        SELECT sku_id, sku_master_code, master_sku, product_name, sku_type, bundle_flag, first_order_at
        FROM {S}.m_sku WHERE sku_id = :id
    """, id=sku_id).mappings().first()
    if row is None:
        raise SkuChangeError(f'SKU {sku_id} not found', 404)
    return dict(row)


def _open_change(*sku_ids: int):
    return q("""
        SELECT change_id, kind, source_code, target_code, status FROM {S}.log_sku_change
        WHERE status = ANY(:open) AND (source_sku_id = ANY(:ids) OR target_sku_id = ANY(:ids))
        ORDER BY change_id LIMIT 1
    """, open=list(OPEN), ids=list(sku_ids)).mappings().first()


def _merging(sku_id: int) -> bool:
    return q("""
        SELECT 1 FROM {S}.log_sku_change
        WHERE kind = 'MERGE' AND source_sku_id = :id AND status = ANY(:open)
    """, id=sku_id, open=list(OPEN)).first() is not None


def _bom(sku_id: int) -> list[dict]:
    """Components in the log_bundle_change format (sku_master/bundle_upload._bom_json)."""
    rows = q("""
        SELECT component_seq AS seq, component_sku_id, qty, price_ratio, dq_flag
        FROM {S}.m_sku_bundle WHERE bundle_sku_id = :id ORDER BY component_seq
    """, id=sku_id).mappings().all()
    return [{'seq': r['seq'], 'component_sku_id': r['component_sku_id'], 'qty': r['qty'],
             'price_ratio': str(r['price_ratio']) if r['price_ratio'] is not None else None,
             'dq_flag': r['dq_flag'] or None} for r in rows]


def _components_key(bom: list[dict]) -> list[tuple]:
    return sorted((c['component_sku_id'], c['qty']) for c in bom)


def _aliases(sku_id: int) -> list[dict]:
    return [dict(r) for r in q("""
        SELECT sku_code, is_master_code, first_seen_at FROM {S}.m_sku_alias
        WHERE sku_id = :id ORDER BY first_seen_at DESC NULLS LAST, sku_code
    """, id=sku_id).mappings().all()]


def _listings(sku_id: int) -> list[dict]:
    return [dict(r) for r in q("""
        SELECT p.platform_sku_id, p.channel_id, c.channel_name, p.merchant_sku, p.product_name,
               p.current_seller_sku, p.first_order_at
        FROM {S}.m_platform_sku p JOIN {S}.m_channel c USING (channel_id)
        WHERE p.sku_id = :id ORDER BY c.channel_name, p.merchant_sku
    """, id=sku_id).mappings().all()]


def _line_groups(sku_id: int, listing_ids: list[int], codes: list[str]) -> list[dict]:
    """Stored order rows that may belong to the SKU, grouped by (seller SKU, listing, is_bundle): its own
    plain rows, plus the split component rows sold on its listings or under its seller SKUs."""
    return [dict(r) for r in q(f"""
        SELECT seller_sku, platform_sku_id, is_bundle, count(*) AS rows,
               count(DISTINCT (order_id, split_part(line_key, '#', 1))) AS lines
        FROM {{S}}.t_order_detail
        WHERE (sku_id = :id AND NOT is_bundle)
           OR (is_bundle AND (platform_sku_id = ANY(:listings)
               OR upper(regexp_replace(btrim(seller_sku), '{SELLER_PREFIX}', '', 'i')) = ANY(:codes)))
        GROUP BY seller_sku, platform_sku_id, is_bundle
    """, id=sku_id, listings=listing_ids or [0], codes=codes or ['']).mappings().all()]


def _owned_groups(sku_id: int, listing_ids: list[int], codes: list[str]) -> list[dict]:
    """The line groups that resolve to the SKU (the order load's rule: the cleaned seller SKU's owner,
    else the listing's), each tagged with what carries it: 'code' or 'listing'."""
    groups = _line_groups(sku_id, listing_ids, codes)
    for g in groups:
        g['code'] = clean_sku(g['seller_sku'])
    seen = sorted({g['code'] for g in groups if g['code']})
    code_owner = dict(q('SELECT sku_code, sku_id FROM {S}.m_sku_alias WHERE sku_code = ANY(:c)',
                        c=seen or ['']).all())
    pids = sorted({g['platform_sku_id'] for g in groups if g['platform_sku_id'] is not None})
    listing_owner = dict(q('SELECT platform_sku_id, sku_id FROM {S}.m_platform_sku WHERE platform_sku_id = ANY(:p)',
                           p=pids or [0]).all())
    owned = []
    for g in groups:
        by_code = code_owner.get(g['code']) if g['code'] else None
        owner = by_code if by_code is not None else listing_owner.get(g['platform_sku_id'])
        if owner == sku_id or (not g['is_bundle'] and owner is None):
            owned.append({**g, 'by': 'code' if by_code == sku_id else 'listing'})
    return owned


def _jsonable(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _rows(sql: str, **params) -> list[dict]:
    return [{k: _jsonable(v) for k, v in r.items()} for r in q(sql, **params).mappings().all()]


def _snapshot(*sku_ids: int) -> dict:
    """Master rows of the SKUs before the change, for the audit trail (log_sku_change.snapshot)."""
    ids = list(sku_ids)
    return {
        'm_sku': _rows('SELECT * FROM {S}.m_sku WHERE sku_id = ANY(:ids)', ids=ids),
        'm_sku_alias': _rows('SELECT * FROM {S}.m_sku_alias WHERE sku_id = ANY(:ids)', ids=ids),
        'm_platform_sku': _rows('SELECT * FROM {S}.m_platform_sku WHERE sku_id = ANY(:ids)', ids=ids),
        'm_sku_history': _rows("""
            SELECT h.* FROM {S}.m_sku_history h
            WHERE h.sku_id = ANY(:ids) OR h.platform_sku_id IN
                (SELECT platform_sku_id FROM {S}.m_platform_sku WHERE sku_id = ANY(:ids))
        """, ids=ids),
        'm_sku_bundle': _rows("""
            SELECT * FROM {S}.m_sku_bundle WHERE bundle_sku_id = ANY(:ids) OR component_sku_id = ANY(:ids)
        """, ids=ids),
    }


def _sku_brief(sku: dict) -> dict:
    return {'id': sku['sku_id'], 'skuId': sku['sku_master_code'], 'sellerSku': sku['master_sku'],
            'productName': sku['product_name']}


# --------------------------------------------------------------------------------------- composition

def composition(sku_id: int) -> dict:
    """Seller SKUs and listings of a SKU with their stored order lines (for the split dialog)."""
    sku = _sku(sku_id)
    aliases, listings = _aliases(sku_id), _listings(sku_id)
    by_code, by_listing = {}, {}
    for g in _owned_groups(sku_id, [x['platform_sku_id'] for x in listings], [a['sku_code'] for a in aliases]):
        if g['by'] == 'code':
            by_code[g['code']] = by_code.get(g['code'], 0) + g['lines']
        elif g['platform_sku_id'] is not None:
            by_listing[g['platform_sku_id']] = by_listing.get(g['platform_sku_id'], 0) + g['lines']
    bom = _bom(sku_id)
    return {
        'sku': _sku_brief(sku),
        'codes': [{'code': a['sku_code'], 'isMasterCode': a['is_master_code'], 'firstSeenAt': a['first_seen_at'],
                   'orderLines': by_code.get(a['sku_code'], 0)} for a in aliases],
        'listings': [{'platformSkuId': x['platform_sku_id'], 'channel': x['channel_name'],
                      'merchantSku': x['merchant_sku'], 'productName': x['product_name'],
                      'currentSellerSku': x['current_seller_sku'],
                      'orderLines': by_listing.get(x['platform_sku_id'], 0)} for x in listings],
        'bundleComponents': len(bom),
        'merging': _merging(sku_id),
    }


# --------------------------------------------------------------------------------------- suggestions

def merge_suggestions(sku_id: int) -> list[dict]:
    """SKUs most like this one by name (same scoring as the review candidates), best first."""
    from app.common.sku_match import NameMatcher

    sku = _sku(sku_id)
    names = q("""
        SELECT s.sku_id, s.sku_master_code, s.product_name FROM {S}.m_sku s
        WHERE s.sku_id <> :id AND s.sku_id NOT IN
            (SELECT source_sku_id FROM {S}.log_sku_change WHERE kind = 'MERGE' AND status = ANY(:open))
        UNION ALL
        SELECT s.sku_id, s.sku_master_code, p.product_name
        FROM {S}.m_platform_sku p JOIN {S}.m_sku s USING (sku_id)
        WHERE s.sku_id <> :id AND p.product_name IS NOT NULL AND s.sku_id NOT IN
            (SELECT source_sku_id FROM {S}.log_sku_change WHERE kind = 'MERGE' AND status = ANY(:open))
    """, id=sku_id, open=list(OPEN)).all()
    matcher = NameMatcher([tuple(r) for r in names])
    own = [sku['product_name']] + [x['product_name'] for x in _listings(sku_id) if x['product_name']]
    best = {}
    for name in dict.fromkeys(own):
        for c in matcher.top(name, n=SUGGESTIONS * 2):
            if c.sku_id not in best or c.score > best[c.sku_id].score:
                best[c.sku_id] = c
    ranked = sorted(best.values(), key=lambda c: c.score, reverse=True)[:SUGGESTIONS]
    if not ranked:
        return []
    info = {r['sku_id']: r for r in q("""
        SELECT s.sku_id, s.master_sku, s.product_name, s.bundle_flag FROM {S}.m_sku s WHERE s.sku_id = ANY(:ids)
    """, ids=[c.sku_id for c in ranked]).mappings().all()}
    return [{'id': c.sku_id, 'skuId': c.sku_master_code, 'productName': info[c.sku_id]['product_name'],
             'sellerSku': info[c.sku_id]['master_sku'], 'matchedName': c.name, 'score': c.score,
             'cosine': c.cosine, 'factors': c.factors} for c in ranked]


# --------------------------------------------------------------------------------------- merge

def _merge_check(source: dict, target: dict) -> tuple[list[dict], list[dict]]:
    if source['sku_id'] == target['sku_id']:
        raise SkuChangeError('Choose another SKU to merge into')
    change = _open_change(source['sku_id'], target['sku_id'])
    if change:
        raise SkuChangeError(
            f"{change['kind'].title()} {change['source_code']} → {change['target_code']} is still "
            f"{change['status'].lower()}; wait for it to finish (or retry it) first", 409)
    bom_s, bom_t = _bom(source['sku_id']), _bom(target['sku_id'])
    if bom_s and bom_t and _components_key(bom_s) != _components_key(bom_t):
        raise SkuChangeError(
            f"{source['sku_master_code']} and {target['sku_master_code']} are bundles with different "
            "components; align them in SKU Bundling first", 409)
    for outer, inner in ((source, target), (target, source)):
        if any(c['component_sku_id'] == inner['sku_id'] for c in _bom(outer['sku_id'])):
            raise SkuChangeError(
                f"{inner['sku_master_code']} is a component of {outer['sku_master_code']}; a bundle "
                "cannot be merged with its own component", 409)
    return bom_s, bom_t


def _merge_counts(source: dict, bom_s: list[dict], bom_t: list[dict]) -> dict:
    sid = source['sku_id']
    listings = _listings(sid)
    groups = _owned_groups(sid, [x['platform_sku_id'] for x in listings], [a['sku_code'] for a in _aliases(sid)])
    in_bundles = q('SELECT count(DISTINCT bundle_sku_id) FROM {S}.m_sku_bundle WHERE component_sku_id = :id',
                   id=sid).scalar_one()
    return {
        'codes': len(_aliases(sid)),
        'listings': len(listings),
        'historyRows': q('SELECT count(*) FROM {S}.m_sku_history WHERE sku_id = :id', id=sid).scalar_one(),
        'orderLines': sum(g['lines'] for g in groups),
        'componentOfBundles': in_bundles,
        'bundle': ('same components' if bom_s and bom_t else
                   'source components move to the target' if bom_s else
                   "source lines are split with the target's components" if bom_t else None),
    }


def merge(source_id: int, target_id: int, mode: str, user: str) -> dict:
    """Merge SKU `source_id` into `target_id`; 'preview' validates and counts, 'apply' writes."""
    if mode == 'apply':
        lock_master()
    source, target = _sku(source_id), _sku(target_id)
    bom_s, bom_t = _merge_check(source, target)
    counts = _merge_counts(source, bom_s, bom_t)
    result = {'kind': 'MERGE', 'source': _sku_brief(source), 'target': _sku_brief(target),
              'deletes': source['sku_master_code'], 'counts': counts}
    if mode != 'apply':
        db.session.rollback()
        return result

    sid, tid = source['sku_id'], target['sku_id']
    snapshot = _snapshot(sid, tid)
    codes = [a['sku_code'] for a in _aliases(sid)]
    listing_ids = [x['platform_sku_id'] for x in _listings(sid)]
    run_id = _open_run(user, f"merge {source['sku_master_code']} -> {target['sku_master_code']}")

    q('UPDATE {S}.m_sku_alias SET sku_id = :t, is_master_code = false WHERE sku_id = :s', s=sid, t=tid)
    q('UPDATE {S}.m_platform_sku SET sku_id = :t, updated_at = now() WHERE sku_id = :s', s=sid, t=tid)
    q('UPDATE {S}.m_sku_history SET sku_id = :t WHERE sku_id = :s', s=sid, t=tid)
    _recount_on_master(tid)

    bundle = None
    if bom_s and not bom_t:                         # the target becomes the bundle
        q('UPDATE {S}.m_sku_bundle SET bundle_sku_id = :t WHERE bundle_sku_id = :s', s=sid, t=tid)
        q("UPDATE {S}.m_sku SET bundle_flag = true WHERE sku_id = :t", t=tid)
        bundle = {'sku_id': tid, 'old_bom': bom_s, 'new_bom': bom_s}       # the target's own lines split
    elif bom_t and not bom_s:
        bundle = {'sku_id': tid, 'old_bom': bom_t, 'new_bom': bom_t}       # the source's lines split
    elif bom_s:
        q('DELETE FROM {S}.m_sku_bundle WHERE bundle_sku_id = :s', s=sid)   # same components: keep the target's
    bundle_changes = _merge_component(sid, tid, run_id)

    for table, column in (('log_sku_match', 'resolved_sku_id'), ('log_sku_match', 'suggested_sku_id'),
                          ('log_dq_issue', 'sku_id'), ('log_bundle_change', 'bundle_sku_id')):
        q(f'UPDATE {{S}}.{table} SET {column} = :t WHERE {column} = :s', s=sid, t=tid)
    q('DELETE FROM {S}.dm_sales_sku_daily WHERE sku_id = :s', s=sid)      # rebuilt from the order lines
    q("""
        UPDATE {S}.m_sku SET first_order_at = least(first_order_at, :at), updated_at = now() WHERE sku_id = :t
    """, t=tid, at=source['first_order_at'])

    change_id = _log_change(run_id, 'MERGE', source, target, False, {'codes': codes, 'listing_ids': listing_ids},
                            snapshot, {'rebuild': bundle, 'bundle_change_ids': bundle_changes} if bundle or
                            bundle_changes else None, user)
    db.session.commit()
    return {**result, 'changeId': change_id, 'reassign': _start(change_id, user)}


def _merge_component(sid: int, tid: int, run_id: int) -> list[int]:
    """Bundles listing the source as a component now list the target; where the target is already a
    component the two rows are combined, and the bundle's stored lines are re-split (log_bundle_change)."""
    changes = []
    bundles = q('SELECT DISTINCT bundle_sku_id FROM {S}.m_sku_bundle WHERE component_sku_id = :s',
                s=sid).scalars().all()
    for bundle_id in bundles:
        old = _bom(bundle_id)
        rows = {c['component_sku_id']: c for c in old}
        if tid not in rows:
            q('UPDATE {S}.m_sku_bundle SET component_sku_id = :t WHERE bundle_sku_id = :b AND component_sku_id = :s',
              s=sid, t=tid, b=bundle_id)
            continue
        src, dst = rows[sid], rows[tid]
        ratio = None
        if src['price_ratio'] is not None or dst['price_ratio'] is not None:
            ratio = min(Decimal(src['price_ratio'] or 0) + Decimal(dst['price_ratio'] or 0), Decimal(1))
        q("""
            UPDATE {S}.m_sku_bundle SET qty = qty + :qty, price_ratio = :ratio
            WHERE bundle_sku_id = :b AND component_seq = :seq
        """, qty=src['qty'], ratio=ratio, b=bundle_id, seq=dst['seq'])
        q('DELETE FROM {S}.m_sku_bundle WHERE bundle_sku_id = :b AND component_seq = :seq', b=bundle_id,
          seq=src['seq'])
        changes.append(q("""
            INSERT INTO {S}.log_bundle_change (run_id, bundle_sku_id, old_bom, new_bom, status)
            VALUES (:run, :b, CAST(:old AS jsonb), CAST(:new AS jsonb), 'PENDING') RETURNING change_id
        """, run=run_id, b=bundle_id, old=json.dumps(old), new=json.dumps(_bom(bundle_id))).scalar_one())
    return changes


# --------------------------------------------------------------------------------------- split

def split(source_id: int, codes: list[str], listing_ids: list[int], target_id: int | None,
          new_name: str | None, mode: str, user: str) -> dict:
    """Move seller SKUs / listings of `source_id` to SKU `target_id`, or to a new SKU named `new_name`."""
    if mode == 'apply':
        lock_master()
    source = _sku(source_id)
    codes, listing_ids = sorted(set(codes)), sorted(set(listing_ids))
    if not codes and not listing_ids:
        raise SkuChangeError('Choose at least one seller SKU or listing to split off')
    aliases = {a['sku_code']: a for a in _aliases(source_id)}
    listings = {x['platform_sku_id']: x for x in _listings(source_id)}
    foreign = [c for c in codes if c not in aliases] + [str(i) for i in listing_ids if i not in listings]
    if foreign:
        raise SkuChangeError(f"Not part of {source['sku_master_code']}: {', '.join(foreign)}", 409)
    target = _sku(target_id) if target_id is not None else None
    if target is not None and target['sku_id'] == source_id:
        raise SkuChangeError('Choose another SKU than the one being split')
    if target is None and not (new_name or '').strip():
        raise SkuChangeError('A new SKU needs a product name')
    change = _open_change(source_id, *( [target['sku_id']] if target else []))
    if change:
        raise SkuChangeError(
            f"{change['kind'].title()} {change['source_code']} → {change['target_code']} is still "
            f"{change['status'].lower()}; wait for it to finish (or retry it) first", 409)
    remains = (set(aliases) - set(codes)) or (set(listings) - set(listing_ids))
    if not remains:
        raise SkuChangeError(
            f"Nothing would remain on {source['sku_master_code']}; use Merge to move all of it", 409)

    bom_s = _bom(source_id)
    bom_t = _bom(target['sku_id']) if target else []
    counts = _split_counts(source_id, codes, listing_ids, aliases, listings)
    counts['bundle'] = ('bundle lines are rebuilt as plain lines' if bom_s and not bom_t else
                        "lines are re-split with the target's components" if bom_t else None)
    target_brief = _sku_brief(target) if target else {'id': None, 'skuId': '(new SKU)', 'sellerSku': None,
                                                         'productName': new_name.strip()}
    result = {'kind': 'SPLIT', 'source': _sku_brief(source), 'target': target_brief, 'counts': counts}
    if mode != 'apply':
        db.session.rollback()
        return result

    sid = source_id
    snapshot = _snapshot(sid, *([target['sku_id']] if target else []))
    # newest first; codes without a first-seen date last
    moved_codes = sorted(codes, key=lambda c: (aliases[c]['first_seen_at'] is not None,
                                               aliases[c]['first_seen_at'] or 0), reverse=True)
    first_at = min([aliases[c]['first_seen_at'] for c in codes if aliases[c]['first_seen_at']] +
                   [listings[i]['first_order_at'] for i in listing_ids if listings[i]['first_order_at']],
                   default=None)
    created = target is None
    if created:
        name = new_name.strip()
        newest = moved_codes[0] if moved_codes else None
        target = insert_sku(None, name, sku_type(newest, name) if newest else 'unknown', f"split_from:{source['sku_master_code']}",
                            first_order_at=first_at)
        target = _sku(target['sku_id'])
    tid = target['sku_id']
    run_id = _open_run(user, f"split {source['sku_master_code']} -> {target['sku_master_code']}")

    master_moves = source['master_sku'] in codes
    if master_moves:                                    # uq_m_sku_master_sku: clear before the code moves
        q('UPDATE {S}.m_sku SET master_sku = NULL WHERE sku_id = :s', s=sid)
    if codes:
        q("""
            UPDATE {S}.m_sku_alias SET sku_id = :t, is_master_code = false WHERE sku_code = ANY(:codes)
        """, t=tid, codes=codes)
        q(f"""
            UPDATE {{S}}.m_sku_history SET sku_id = :t
            WHERE sku_id = :s AND upper(regexp_replace(btrim(new_seller_sku), '{SELLER_PREFIX}', '', 'i')) = ANY(:codes)
        """, s=sid, t=tid, codes=codes)
    if listing_ids:
        q("""
            UPDATE {S}.m_platform_sku SET sku_id = :t, updated_at = now() WHERE platform_sku_id = ANY(:ids)
        """, t=tid, ids=listing_ids)
        q("""
            UPDATE {S}.m_sku_history SET sku_id = :t WHERE sku_id = :s AND platform_sku_id = ANY(:ids)
        """, s=sid, t=tid, ids=listing_ids)
    if master_moves:
        _promote_newest(sid)
    if target['master_sku'] is None and moved_codes:
        _set_master(tid, moved_codes[0])
    _recount_on_master(sid)
    _recount_on_master(tid)
    q("""
        UPDATE {S}.log_sku_match m SET resolved_sku_id = :t
        WHERE m.resolved_sku_id = :s AND (m.sku_code = ANY(:codes) OR EXISTS (
            SELECT 1 FROM {S}.m_platform_sku p
            WHERE p.platform_sku_id = ANY(:ids) AND p.channel_id = m.channel_id AND p.merchant_sku = m.merchant_sku))
    """, s=sid, t=tid, codes=codes or [''], ids=listing_ids or [0])
    if not created:
        q("""
            UPDATE {S}.m_sku SET first_order_at = least(first_order_at, :at), updated_at = now() WHERE sku_id = :t
        """, t=tid, at=first_at)

    bundle = {'sku_id': tid, 'old_bom': bom_s or None, 'new_bom': bom_t} if bom_s or bom_t else None
    change_id = _log_change(run_id, 'SPLIT', source, target, created,
                            {'codes': codes, 'listing_ids': listing_ids}, snapshot,
                            {'rebuild': bundle, 'bundle_change_ids': []} if bundle else None, user)
    target = _sku(tid)                                  # with the master code it took over
    db.session.commit()
    return {**result, 'target': _sku_brief(target), 'changeId': change_id, 'reassign': _start(change_id, user)}


def _split_counts(sid: int, codes: list[str], listing_ids: list[int], aliases: dict, listings: dict) -> dict:
    """Order lines that move: a line follows its seller SKU when that is one of the SKU's codes, else its
    listing (the order load's rule)."""
    lines = 0
    for g in _owned_groups(sid, list(listings), list(aliases)):
        if (g['by'] == 'code' and g['code'] in codes) or (g['by'] == 'listing' and g['platform_sku_id'] in listing_ids):
            lines += g['lines']
    history = q("""
        SELECT count(*) FROM {S}.m_sku_history WHERE sku_id = :s AND platform_sku_id = ANY(:ids)
    """, s=sid, ids=listing_ids or [0]).scalar_one()
    return {'codes': len(codes), 'listings': len(listing_ids), 'historyRows': history, 'orderLines': lines}


def _promote_newest(sku_id: int):
    code = q("""
        SELECT sku_code FROM {S}.m_sku_alias WHERE sku_id = :id
        ORDER BY first_seen_at DESC NULLS LAST, sku_code LIMIT 1
    """, id=sku_id).scalar()
    if code:
        _set_master(sku_id, code)


def _set_master(sku_id: int, code: str):
    q('UPDATE {S}.m_sku_alias SET is_master_code = (sku_code = :code) WHERE sku_id = :id', id=sku_id, code=code)
    q('UPDATE {S}.m_sku SET master_sku = :code, updated_at = now() WHERE sku_id = :id', id=sku_id, code=code)


def _recount_on_master(sku_id: int):
    """m_platform_sku.is_on_master_sku of the SKU's listings (as sku/process.promote_master_code)."""
    q(f"""
        UPDATE {{S}}.m_platform_sku p
        SET is_on_master_sku = coalesce(upper(btrim(p.current_seller_sku)) = s.master_sku
            OR upper(regexp_replace(btrim(p.current_seller_sku), '{SELLER_PREFIX}', '', 'i')) = s.master_sku, false)
        FROM {{S}}.m_sku s WHERE s.sku_id = p.sku_id AND p.sku_id = :id
    """, id=sku_id)


# --------------------------------------------------------------------------------------- log / DAG

def _open_run(user: str, what: str) -> int:
    return q("""
        INSERT INTO {S}.log_etl_run (status, channels, source_files, triggered_by)
        VALUES ('RUNNING', 'SKU_CHANGE', :what, :user) RETURNING run_id
    """, what=what, user=user).scalar_one()


def _log_change(run_id: int, kind: str, source: dict, target: dict, created: bool, items: dict,
                snapshot: dict, bundle: dict | None, user: str) -> int:
    return q("""
        INSERT INTO {S}.log_sku_change (run_id, kind, source_sku_id, source_code, target_sku_id, target_code,
                                        target_created, items, snapshot, bundle, created_by)
        VALUES (:run, :kind, :s, :scode, :t, :tcode, :created, CAST(:items AS jsonb), CAST(:snapshot AS jsonb),
                CAST(:bundle AS jsonb), :user)
        RETURNING change_id
    """, run=run_id, kind=kind, s=source['sku_id'], scode=source['sku_master_code'], t=target['sku_id'],
       tcode=target['sku_master_code'], created=created, items=json.dumps(items),
       snapshot=json.dumps(snapshot, default=_jsonable), bundle=json.dumps(bundle) if bundle else None,
       user=user).scalar_one()


def _start(change_id: int, user: str) -> dict:
    dag_run_id = f'reassign__{change_id}__{jakarta_now():%Y%m%d%H%M%S}'
    try:
        trigger_dag(DAG_ID, conf={'change_id': change_id, 'by': user}, dag_run_id=dag_run_id)
    except Exception as err:          # the change stays PENDING; the changes drawer offers a retry
        logger.error('Could not start %s for SKU change %s: %s', DAG_ID, change_id, err)
        message = str(err)[:500]
        q('UPDATE {S}.log_sku_change SET message = :m WHERE change_id = :id', m=f'Not started: {message}',
          id=change_id)
        db.session.commit()
        return {'triggered': False, 'dagId': DAG_ID, 'error': message}
    return {'triggered': True, 'dagId': DAG_ID, 'dagRunId': dag_run_id}


def list_changes(statuses: list[str]) -> list[dict]:
    rows = q("""
        SELECT change_id, kind, source_code, target_code, target_created, items, status, counts, message,
               created_by, created_at, finished_at
        FROM {S}.log_sku_change
        WHERE cardinality(CAST(:statuses AS text[])) = 0 OR status = ANY(CAST(:statuses AS text[]))
        ORDER BY change_id DESC LIMIT 200
    """, statuses=statuses).mappings().all()
    return [{'changeId': r['change_id'], 'kind': r['kind'], 'source': r['source_code'], 'target': r['target_code'],
             'targetCreated': r['target_created'], 'codes': len(r['items'].get('codes') or []),
             'listings': len(r['items'].get('listing_ids') or []), 'status': r['status'],
             'counts': r['counts'], 'message': r['message'], 'by': r['created_by'],
             'createdAt': r['created_at'], 'finishedAt': r['finished_at']} for r in rows]


def retry(change_id: int, user: str) -> dict:
    row = q("""
        UPDATE {S}.log_sku_change SET status = 'PENDING', message = NULL
        WHERE change_id = :id AND status IN ('PENDING', 'FAILED') RETURNING change_id
    """, id=change_id).first()
    db.session.commit()
    if row is None:
        raise SkuChangeError(f'Change {change_id} is not pending or failed', 409)
    return _start(change_id, user)
