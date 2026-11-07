"""SKU review of a Paused upload: listings the Airflow process_sku step could not match.

process_sku_{channel} writes a listing whose seller SKU and platform SKU are both unknown, but
whose name is close to an existing SKU, to royal_canin.log_sku_match as PENDING. Its order lines
wait, and the upload ends Paused. Here a user decides for every PENDING listing of the upload:

- map:    the listing belongs to an existing SKU (a suggested candidate or any other SKU)
- create: the listing is a new product -> new m_sku

The master writes follow airflow/dags/sku/process.py (add_platform, add_alias, touch_sku,
create_sku) and run under the same advisory lock, so svc and the DAG never write the SKU master at
the same time. Keep both in sync.

A mapping never alters the SKU's seller SKU. One seller SKU is sold on every platform; only the
platform SKU differs per listing. So the listing's seller SKU is added as a non-master alias (so
later uploads of the same listing resolve), and there is no R4 promotion: m_sku.master_sku, the
alias master flags and the SKU's other listings stay as they are.

A review row is shared by every upload that holds the listing (log_sku_match_upload): deciding
it once resolves it for all of them. A decision on a seller SKU also settles the PENDING rows of
other listings with the same seller SKU (any marketplace, any upload): they are mapped to the same
SKU with resolution 'sibling'.

Afterwards handle_continue_order_data_{channel} is triggered with conf {upload_id, channel,
match_ids} for this upload and for every other Paused upload the decisions leave with nothing
pending. It loads ONLY the order lines of those resolved listings, never lines that were already
loaded, and keeps existing order headers (only recounting them). If Airflow cannot start the DAG,
the decisions stay saved and the upload stays Paused until /resume succeeds.
"""
import json

from sqlalchemy import text

from app.blueprints.upload.requests.sku_review_request import SkuDecision, SkuReviewResolveRequest
from app.blueprints.upload.service import CHANNEL_MARKETPLACES
from app.blueprints.sku_master.master_writes import SKU_LOCK_KEY, alias_owner, insert_sku, next_id
from app.blueprints.upload.sku_rules import sku_type
from app.common.airflow_client import trigger_dag
from app.common.helpers import jakarta_now
from app.common.logger import get_logger
from app.extensions import db
from app.models.royal_canin import SCHEMA

# DAG that loads the order lines of the resolved listings (not built yet)
CONTINUE_DAG_ID = 'handle_continue_order_data_{channel}'

logger = get_logger(__name__)


class SkuReviewError(Exception):
    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code


def _q(sql: str, **params):
    return db.session.execute(text(sql.replace('{S}', SCHEMA)), params)


def _upload(upload_id: str, lock: bool = False):
    row = _q(f"""
        SELECT upload_id, file_name, channel, status, total_rows, created_at, meta_data
        FROM public.upload_progress WHERE upload_id = :id {'FOR UPDATE' if lock else ''}
    """, id=upload_id).mappings().first()
    if row is None:
        raise SkuReviewError('Upload not found', 404)
    return row


# ------------------------------------------------------------------------------------- review list

def get_review(upload_id: str) -> dict:
    upload = _upload(upload_id)
    rows = _q("""
        SELECT m.match_id, m.status, c.channel_name, m.merchant_sku, m.seller_sku, m.sku_code,
               m.product_name, m.variation, m.order_line_count, m.first_order_at, m.last_order_at,
               m.candidates, m.resolved_sku_id, rs.sku_master_code AS resolved_code,
               rs.product_name AS resolved_name, m.resolved_by, m.resolved_at,
               m.resolution, mu.order_line_count AS upload_line_count
        FROM {S}.log_sku_match m
        JOIN {S}.log_sku_match_upload mu ON mu.match_id = m.match_id AND mu.upload_id = :id
        JOIN {S}.m_channel c ON c.channel_id = m.channel_id
        LEFT JOIN {S}.m_sku rs ON rs.sku_id = m.resolved_sku_id
        ORDER BY (m.status <> 'PENDING'), m.match_id
    """, id=upload_id).mappings().all()
    others = _other_uploads([r['match_id'] for r in rows], upload_id)

    # candidates are stored as found by the matcher; show the SKUs as they are now
    sku_ids = {c['sku_id'] for r in rows for c in (r['candidates'] or []) if c.get('sku_id') is not None}
    current = {}
    if sku_ids:
        current = {s['sku_id']: s for s in _q("""
            SELECT sku_id, sku_master_code, master_sku, product_name FROM {S}.m_sku
            WHERE sku_id = ANY(:ids)
        """, ids=list(sku_ids)).mappings().all()}

    def candidates(raw) -> list[dict]:
        found = [c for c in (raw or []) if c.get('sku_id') in current]
        found.sort(key=lambda c: c.get('score') or 0, reverse=True)
        return [{
            'id': c['sku_id'],
            'skuId': current[c['sku_id']]['sku_master_code'],
            'sellerSku': current[c['sku_id']]['master_sku'],
            'productName': current[c['sku_id']]['product_name'],
            'score': float(c['score']) if c.get('score') is not None else None,
        } for c in found]

    items = [{
        'matchId': r['match_id'],
        'status': r['status'],
        'channel': r['channel_name'],
        'merchantSku': r['merchant_sku'],
        'sellerSku': r['seller_sku'],
        'skuCode': r['sku_code'] or None,
        'productName': r['product_name'],
        'variation': r['variation'] or None,
        'orderLineCount': r['upload_line_count'] if r['upload_line_count'] is not None else r['order_line_count'],
        # other uploads that hold the same listing: deciding it here resolves it there too
        'otherUploads': others.get(r['match_id'], []),
        'firstOrderAt': r['first_order_at'],
        'lastOrderAt': r['last_order_at'],
        'candidates': candidates(r['candidates']),
        'resolved': None if r['status'] == 'PENDING' else {
            'id': r['resolved_sku_id'],
            'skuId': r['resolved_code'],
            'productName': r['resolved_name'],
            'by': r['resolved_by'],
            'at': r['resolved_at'],
            'resolution': r['resolution'],
        },
    } for r in rows]

    meta = upload['meta_data'] or {}
    return {
        'upload': {
            'id': upload['upload_id'],
            'fileName': upload['file_name'],
            'channel': upload['channel'],
            'marketplace': CHANNEL_MARKETPLACES.get(upload['channel'], (upload['channel'],))[0],
            'status': upload['status'],
            'totalRows': upload['total_rows'],
            'createdAt': upload['created_at'],
            'pending': sum(1 for i in items if i['status'] == 'PENDING'),
            'resumeError': meta.get('resume_error'),
            'resumeNeeded': bool(meta.get('resume_needed')),
        },
        'items': items,
    }


def _other_uploads(match_ids: list[int], upload_id: str) -> dict[int, list[dict]]:
    """match_id -> the other uploads holding the listing."""
    if not match_ids:
        return {}
    found: dict[int, list[dict]] = {}
    for r in _q("""
        SELECT mu.match_id, u.upload_id, u.file_name, u.status
        FROM {S}.log_sku_match_upload mu JOIN public.upload_progress u ON u.upload_id = mu.upload_id
        WHERE mu.match_id = ANY(:ids) AND mu.upload_id <> :id
        ORDER BY u.created_at
    """, ids=match_ids, id=upload_id).mappings().all():
        found.setdefault(r['match_id'], []).append(
            {'id': r['upload_id'], 'fileName': r['file_name'], 'status': r['status']})
    return found


# -------------------------------------------------------------------------------- master writes



def _sku(sku_id: int):
    return _q("""
        SELECT sku_id, sku_master_code, master_sku, product_name FROM {S}.m_sku WHERE sku_id = :id
    """, id=sku_id).mappings().first()




def _create_sku(match, product_name: str | None) -> dict:
    """create_sku: a new SKU master for the listing; its seller SKU becomes the master code."""
    code = match['sku_code'] or None
    if code and alias_owner(code) is not None:
        raise SkuReviewError(f"Seller SKU {code} already belongs to another SKU; map the listing instead", 409)
    name = product_name or match['product_name'] or match['seller_sku'] or match['merchant_sku']
    return insert_sku(code, name, sku_type(code, name) if code else 'unknown',
                      'name_unmatched' if code else 'missing_seller_sku,name_unmatched',
                      first_order_at=match['first_order_at'])


def _link_listing(match, sku: dict):
    """The listing (channel, platform SKU) and its seller SKU now point at `sku`.

    Only rows of this listing are added; the SKU's master seller SKU and its other listings are
    never changed (no R4 promotion from a review)."""
    sku_id = sku['sku_id']
    code = match['sku_code'] or None
    listing = _q("""
        SELECT p.sku_id, s.sku_master_code FROM {S}.m_platform_sku p JOIN {S}.m_sku s USING (sku_id)
        WHERE p.channel_id = :ch AND p.merchant_sku = :ms
    """, ch=match['channel_id'], ms=match['merchant_sku']).mappings().first()
    if listing is not None and listing['sku_id'] != sku_id:
        raise SkuReviewError(
            f"Listing {match['merchant_sku']} already belongs to {listing['sku_master_code']}", 409)
    if code:
        owner = alias_owner(code)
        if owner is not None and owner != sku_id:
            other = _q('SELECT sku_master_code FROM {S}.m_sku WHERE sku_id = :id', id=owner).scalar()
            raise SkuReviewError(f'Seller SKU {code} already belongs to {other}', 409)

    if listing is None:                                                    # add_platform
        _q("""
            INSERT INTO {S}.m_platform_sku (platform_sku_id, channel_id, merchant_sku, sku_id,
                current_seller_sku, product_name, is_on_master_sku, first_order_at)
            VALUES (:pid, :ch, :ms, :sku, :seller, :name, :on_master, :at)
        """, pid=next_id('m_platform_sku', 'platform_sku_id'), ch=match['channel_id'],
           ms=match['merchant_sku'], sku=sku_id, seller=match['seller_sku'], name=match['product_name'],
           on_master=code is not None and code == sku['master_sku'], at=match['first_order_at'])

    if code and alias_owner(code) is None:                 # add_alias, without promote_master_code
        _q("""
            INSERT INTO {S}.m_sku_alias (sku_code, sku_id, is_master_code, first_seen_at)
            VALUES (:code, :id, false, :at)
        """, code=code, id=sku_id, at=match['first_order_at'])

    if match['first_order_at'] is not None:                                # touch_sku
        _q("""
            UPDATE {S}.m_sku SET first_order_at = :at
            WHERE sku_id = :id AND (first_order_at IS NULL OR first_order_at > :at)
        """, id=sku_id, at=match['first_order_at'])
        if code:
            _q("""
                UPDATE {S}.m_sku_alias SET first_seen_at = :at
                WHERE sku_code = :code AND (first_seen_at IS NULL OR first_seen_at > :at)
            """, code=code, at=match['first_order_at'])


def _apply(upload_id: str, decisions: list[SkuDecision], user: str) -> dict:
    _q('SELECT pg_advisory_xact_lock(:key)', key=SKU_LOCK_KEY)
    upload = _upload(upload_id, lock=True)
    if upload['status'] != 'Paused':
        raise SkuReviewError(f"Upload is {upload['status']}; only Paused uploads can be resolved", 409)

    pending = {m['match_id']: m for m in _q("""
        SELECT m.match_id, m.channel_id, m.merchant_sku, m.sku_code, m.seller_sku, m.product_name,
               m.first_order_at, m.last_order_at
        FROM {S}.log_sku_match m
        JOIN {S}.log_sku_match_upload mu ON mu.match_id = m.match_id AND mu.upload_id = :id
        WHERE m.status = 'PENDING'
        ORDER BY m.match_id FOR UPDATE OF m
    """, id=upload_id).mappings().all()}
    requested = {d.matchId for d in decisions}
    if not pending:
        raise SkuReviewError('No SKU of this upload waits for review', 409)
    if requested - pending.keys():
        extra = sorted(requested - pending.keys())
        raise SkuReviewError(f'Not pending for this upload: match {", ".join(map(str, extra))}', 409)
    if pending.keys() - requested:
        missing = len(pending.keys() - requested)
        raise SkuReviewError(f'Every unmapped SKU needs a decision; {missing} left without one', 409)

    targets = {}
    for sku_id in {d.skuId for d in decisions if d.action == 'map'}:
        sku = _sku(sku_id)
        if sku is None:
            raise SkuReviewError(f'SKU {sku_id} not found', 404)
        targets[sku_id] = dict(sku)

    mapped, created, decided = 0, [], {}
    for d in decisions:
        match = pending[d.matchId]
        if d.action == 'create':
            sku = _create_sku(match, d.productName)
            created.append({'matchId': d.matchId, 'id': sku['sku_id'], 'skuId': sku['sku_master_code']})
            status = 'CREATED_NEW'
        else:
            sku = targets[d.skuId]
            mapped += 1
            status = 'MAPPED'
        _link_listing(match, dict(sku))
        _q("""
            UPDATE {S}.log_sku_match
            SET status = :status, resolved_sku_id = :sku, resolved_by = :by, resolved_at = now(),
                resolution = 'manual'
            WHERE match_id = :id AND status = 'PENDING'
        """, status=status, sku=sku['sku_id'], by=user, id=d.matchId)
        decided[d.matchId] = dict(sku)

    siblings = _settle_siblings(pending, decided, user, upload['file_name'])

    resolved = {'by': user, 'at': jakarta_now().isoformat(), 'mapped': mapped, 'created': len(created)}
    _q("""
        UPDATE public.upload_progress
        SET meta_data = (coalesce(meta_data::jsonb, '{}'::jsonb)
                         || jsonb_build_object('sku_review_pending', 0,
                                               'sku_review_resolved', CAST(:resolved AS jsonb)))::json,
            updated_at = now()
        WHERE upload_id = :id
    """, id=upload_id, resolved=json.dumps(resolved))
    resolved_ids = sorted(pending) + [s_['matchId'] for s_ in siblings]
    affected = _q("""
        SELECT DISTINCT upload_id FROM {S}.log_sku_match_upload
        WHERE match_id = ANY(:ids) AND upload_id <> :id
    """, ids=resolved_ids, id=upload_id).scalars().all()
    return {'channel': upload['channel'], 'matchIds': sorted(pending), 'mapped': mapped, 'created': created,
            'siblings': siblings, 'affected': list(affected)}


def _settle_siblings(pending: dict, decided: dict[int, dict], user: str, file_name: str) -> list[dict]:
    """PENDING rows of other listings with a seller SKU just decided get the same SKU (resolution
    'sibling'): one seller SKU is one product on every marketplace. A sibling whose listing already
    belongs to another SKU stays PENDING for its own review."""
    codes = {}
    for match_id, sku in decided.items():
        code = pending[match_id]['sku_code']
        if code:
            codes.setdefault(code, sku)
    if not codes:
        return []
    rows = _q("""
        SELECT match_id, channel_id, merchant_sku, sku_code, seller_sku, product_name,
               first_order_at, last_order_at
        FROM {S}.log_sku_match
        WHERE status = 'PENDING' AND sku_code = ANY(:codes) AND NOT (match_id = ANY(:ids))
        ORDER BY match_id FOR UPDATE
    """, codes=list(codes), ids=list(pending)).mappings().all()
    settled = []
    for row in rows:
        sku = codes[row['sku_code']]
        try:
            with db.session.begin_nested():
                _link_listing(row, sku)
                _q("""
                    UPDATE {S}.log_sku_match
                    SET status = 'MAPPED', resolved_sku_id = :sku, resolved_by = :by, resolved_at = now(),
                        resolution = 'sibling'
                    WHERE match_id = :id AND status = 'PENDING'
                """, sku=sku['sku_id'], by=f'{user} (via {file_name})', id=row['match_id'])
        except SkuReviewError as err:
            logger.warning('Sibling %s of %s left pending: %s', row['match_id'], row['sku_code'], err.message)
            continue
        settled.append({'matchId': row['match_id'], 'sellerSku': row['seller_sku'], 'skuId': sku['sku_master_code']})
    return settled


def resolve(upload_id: str, request_body: SkuReviewResolveRequest, user: str) -> dict:
    """Apply every decision in one transaction, then try to resume the upload's pipeline."""
    try:
        applied = _apply(upload_id, request_body.decisions, user)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    resume, status = _trigger_resume(upload_id, applied['channel'], _continue_match_ids(upload_id), user)
    return {'mapped': applied['mapped'], 'created': applied['created'], 'siblings': applied['siblings'],
            'resume': resume, 'uploadStatus': status, 'alsoResumed': _fan_out(applied['affected'], user)}


def _continue_match_ids(upload_id: str) -> list[int]:
    """The upload's resolved listings whose order lines the continue DAG loads."""
    ids = _q("""
        SELECT m.match_id FROM {S}.log_sku_match m
        JOIN {S}.log_sku_match_upload mu ON mu.match_id = m.match_id AND mu.upload_id = :id
        WHERE m.status <> 'PENDING' AND m.resolution IN ('manual', 'sibling', 'auto_mapped')
        ORDER BY m.match_id
    """, id=upload_id).scalars().all()
    db.session.commit()
    return list(ids)


def _linked_pending(upload_id: str) -> int:
    return _q("""
        SELECT count(*) FROM {S}.log_sku_match m
        JOIN {S}.log_sku_match_upload mu ON mu.match_id = m.match_id AND mu.upload_id = :id
        WHERE m.status = 'PENDING'
    """, id=upload_id).scalar_one()


def _fan_out(upload_ids: list[str], user: str) -> list[dict]:
    """Other uploads holding a listing resolved just now: recount their pending SKUs, and resume
    every Paused one that has none left. Queued / Processing uploads pick the SKUs up in their own
    run (orders.status.finalize flags a mid-run resolution as resume_needed)."""
    results = []
    for other in upload_ids:
        row = _q("""
            SELECT upload_id, file_name, channel, status FROM public.upload_progress WHERE upload_id = :id
        """, id=other).mappings().first()
        if row is None:
            continue
        pending = _linked_pending(other)
        _q("""
            UPDATE public.upload_progress
            SET meta_data = (coalesce(meta_data::jsonb, '{}'::jsonb)
                             || jsonb_build_object('sku_review_pending', :pending))::json,
                updated_at = now()
            WHERE upload_id = :id
        """, id=other, pending=pending)
        db.session.commit()
        entry = {'uploadId': other, 'fileName': row['file_name'], 'status': row['status'], 'pending': pending}
        if row['status'] == 'Paused' and pending == 0:
            resume, status = _trigger_resume(other, row['channel'], _continue_match_ids(other), user)
            entry.update({'triggered': resume['triggered'], 'error': resume.get('error'), 'status': status})
        results.append(entry)
    return results


# --------------------------------------------------------------------------------------- resume

def resume(upload_id: str, user: str) -> dict:
    """Start the order load again for an upload whose SKUs are all resolved (after a failed trigger)."""
    upload = _upload(upload_id)
    if upload['status'] != 'Paused':
        raise SkuReviewError(f"Upload is {upload['status']}; only Paused uploads can be resumed", 409)
    pending = _linked_pending(upload_id)
    if pending:
        raise SkuReviewError(f'{pending} SKU(s) still need a decision', 409)
    match_ids = _continue_match_ids(upload_id)   # also ends the read transaction before calling Airflow
    if not match_ids:
        raise SkuReviewError('No resolved SKU of this upload has order lines left to load', 409)
    result, status = _trigger_resume(upload_id, upload['channel'], match_ids, user)
    return {'resume': result, 'uploadStatus': status}


def _trigger_resume(upload_id: str, channel: str, match_ids: list[int], user: str) -> tuple[dict, str]:
    dag_id = CONTINUE_DAG_ID.format(channel=channel)
    now = jakarta_now()
    dag_run_id = f'continue__{upload_id}__{now:%Y%m%d%H%M%S}'
    try:
        trigger_dag(dag_id, conf={'upload_id': upload_id, 'channel': channel, 'match_ids': match_ids},
                    dag_run_id=dag_run_id)
    except Exception as err:   # decisions are saved; record why the resume did not start
        logger.error('Could not resume upload %s with %s: %s', upload_id, dag_id, err)
        message = str(err)[:500]
        _q("""
            UPDATE public.upload_progress
            SET meta_data = (coalesce(meta_data::jsonb, '{}'::jsonb)
                             || jsonb_build_object('resume_error', CAST(:error AS text)))::json,
                updated_at = now()
            WHERE upload_id = :id
        """, id=upload_id, error=message)
        db.session.commit()
        return {'triggered': False, 'dagId': dag_id, 'error': message}, 'Paused'

    resume_meta = {'dag_id': dag_id, 'dag_run_id': dag_run_id, 'triggered_at': now.isoformat(), 'by': user}
    _q("""
        UPDATE public.upload_progress
        SET status = 'Processing', error_message = NULL, processed_at = now(), last_heartbeat = now(),
            updated_at = now(),
            meta_data = ((coalesce(meta_data::jsonb, '{}'::jsonb) - 'resume_error' - 'resume_needed')
                         || jsonb_build_object('resume', CAST(:resume AS jsonb)))::json
        WHERE upload_id = :id
    """, id=upload_id, resume=json.dumps(resume_meta))
    db.session.commit()
    return {'triggered': True, 'dagId': dag_id, 'dagRunId': dag_run_id}, 'Processing'
