"""Re-split stored order lines after a SKU bundling upload (Airflow reconsolidate_bundle_orders).

bundle_upload.apply writes one log_bundle_change row per bundle whose component list changed. With
reconsolidate on, the rows start PENDING and the DAG is triggered right away; otherwise they are
SKIPPED and can be started later from the SKU Bundling page. A failed trigger leaves them PENDING.
"""
from app.blueprints.sku_master.master_writes import q
from app.common.airflow_client import trigger_dag
from app.common.helpers import jakarta_now
from app.common.logger import get_logger
from app.extensions import db

DAG_ID = 'reconsolidate_bundle_orders'
OPEN_STATUSES = ('PENDING', 'RUNNING', 'FAILED', 'SKIPPED')

logger = get_logger(__name__)


def list_changes(statuses: list[str] | None = None, limit: int = 200) -> list[dict]:
    rows = q("""
        SELECT c.change_id, c.run_id, c.bundle_sku_id, s.sku_master_code, s.master_sku, s.product_name,
               c.status, c.old_bom IS NULL AS new_bundle, jsonb_array_length(c.new_bom) AS components,
               c.lines_rebuilt, c.lines_mismatch, c.orders_touched, c.message, c.created_at, c.processed_at,
               r.source_files, r.triggered_by
        FROM {S}.log_bundle_change c
        JOIN {S}.m_sku s ON s.sku_id = c.bundle_sku_id
        JOIN {S}.log_etl_run r ON r.run_id = c.run_id
        WHERE cardinality(CAST(:st AS text[])) = 0 OR c.status = ANY(CAST(:st AS text[]))
        ORDER BY c.change_id DESC LIMIT :limit
    """, st=list(statuses or []), limit=limit).mappings().all()
    return [{
        'changeId': r['change_id'], 'runId': r['run_id'], 'id': r['bundle_sku_id'], 'skuId': r['sku_master_code'],
        'sellerSku': r['master_sku'], 'productName': r['product_name'], 'status': r['status'],
        'newBundle': r['new_bundle'], 'components': r['components'], 'linesRebuilt': r['lines_rebuilt'],
        'linesMismatch': r['lines_mismatch'], 'ordersTouched': r['orders_touched'], 'message': r['message'],
        'createdAt': r['created_at'], 'processedAt': r['processed_at'], 'fileName': r['source_files'],
        'by': r['triggered_by'],
    } for r in rows]


def start(change_ids: list[int] | None, user: str) -> dict:
    """Mark the changes PENDING and trigger the DAG for them (all open, not running ones by default)."""
    ids = q("""
        UPDATE {S}.log_bundle_change SET status = 'PENDING', message = NULL
        WHERE status IN ('PENDING', 'FAILED', 'SKIPPED')
          AND (cardinality(CAST(:ids AS bigint[])) = 0 OR change_id = ANY(CAST(:ids AS bigint[])))
        RETURNING change_id
    """, ids=list(change_ids or [])).scalars().all()
    db.session.commit()
    if not ids:
        return {'triggered': False, 'changeIds': [], 'error': 'Nothing to re-split'}
    dag_run_id = f'rebundle__{jakarta_now():%Y%m%d%H%M%S%f}'
    try:
        trigger_dag(DAG_ID, conf={'change_ids': sorted(ids), 'by': user}, dag_run_id=dag_run_id)
    except Exception as err:   # the changes stay PENDING; the page offers a retry
        logger.error('Could not start %s for changes %s: %s', DAG_ID, ids, err)
        message = str(err)[:500]
        q("UPDATE {S}.log_bundle_change SET message = :m WHERE change_id = ANY(:ids)", m=f'Not started: {message}',
          ids=list(ids))
        db.session.commit()
        return {'triggered': False, 'changeIds': sorted(ids), 'dagId': DAG_ID, 'error': message}
    return {'triggered': True, 'changeIds': sorted(ids), 'dagId': DAG_ID, 'dagRunId': dag_run_id}
