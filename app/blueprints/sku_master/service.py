from flask import abort
from sqlalchemy import asc, column, desc, exists, func, or_, select, table, text

from sqlalchemy.orm import aliased

from app.blueprints.sku_master.requests.list_request import SkuBundlePaginationRequest, SkuMasterPaginationRequest
from app.common.pagination_request import SortOrder
from app.extensions import db
from app.models.royal_canin import SCHEMA
from app.models.royal_canin.master import MChannel, MPlatformSku, MSku, MSkuAlias, MSkuBundle


# A SKU being merged away (log_sku_change MERGE not DONE) is deleted once its order lines have moved;
# until then it is hidden from the list and the pickers
_SKU_CHANGE = table('log_sku_change', column('source_sku_id'), column('kind'), column('status'), schema=SCHEMA)


def _not_merging():
    return MSku.sku_id.not_in(
        select(_SKU_CHANGE.c.source_sku_id).where(
            _SKU_CHANGE.c.kind == 'MERGE', _SKU_CHANGE.c.status.in_(('PENDING', 'RUNNING', 'FAILED'))))


def get_skus(request_body: SkuMasterPaginationRequest) -> dict:
    statements = select(MSku.sku_id, MSku.sku_master_code, MSku.master_sku, MSku.product_name).where(_not_merging())

    for key, value in (request_body.filter or {}).items():
        statements = _filter_sku(statements, key, value)

    count = db.session.execute(
        select(func.count()).select_from(statements.subquery())
    ).scalar_one()

    statements = _sort(statements, request_body.sort, _SORT_COLUMNS)
    statements = statements.offset(request_body.offset).limit(request_body.size)
    rows = db.session.execute(statements).all()

    return {
        'records': [{
            'id': r.sku_id,
            'skuId': r.sku_master_code,
            'sellerSku': r.master_sku,
            'productName': r.product_name,
        } for r in rows],
        'meta': _meta(request_body, count),
    }


_SORT_COLUMNS = {
    'skuId': MSku.sku_master_code,
    'sellerSku': MSku.master_sku,
    'productName': MSku.product_name,
}


def _filter_sku(statements, key: str, value):
    """WHERE for one of the SKU columns shared by the SKU master and bundling tables."""
    if value is None or str(value).strip() == '':
        return statements
    value = str(value).strip()
    match key:
        case 'skuId':
            return statements.where(MSku.sku_master_code.icontains(value, autoescape=True))
        case 'productName':
            return statements.where(MSku.product_name.icontains(value, autoescape=True))
        case 'sellerSku':
            # Older seller SKUs of the product (aliases) find it too
            return statements.where(or_(
                MSku.master_sku.icontains(value, autoescape=True),
                exists().where(
                    MSkuAlias.sku_id == MSku.sku_id,
                    MSkuAlias.sku_code.icontains(value, autoescape=True),
                ),
            ))
    return statements


def _sort(statements, sort: dict | None, columns: dict):
    if sort:
        for column, order in sort.items():
            if column in columns:
                order_fn = asc if order == SortOrder.ASC else desc
                statements = statements.order_by(order_fn(columns[column]).nulls_last())
    else:
        statements = statements.order_by(MSku.sku_master_code.asc())
    # Tie-breaker keeps pages stable
    return statements.order_by(MSku.sku_id.asc())


def _meta(request_body, count: int) -> dict:
    return {
        'page': request_body.page,
        'size': request_body.size,
        'total': count,
        'total_pages': (count + request_body.size - 1) // request_body.size,
    }


def _flags(value: str | None) -> list[str]:
    return [f.strip() for f in (value or '').split(',') if f.strip()]


def _num(value) -> float | None:
    return None if value is None else float(value)


def get_bundles(request_body: SkuBundlePaginationRequest) -> dict:
    """Bundle SKUs (they have rows in m_sku_bundle), each with its component breakdown."""
    component_count = (
        select(func.count()).where(MSkuBundle.bundle_sku_id == MSku.sku_id)
        .correlate(MSku).scalar_subquery().label('component_count')
    )
    statements = (
        select(MSku.sku_id, MSku.sku_master_code, MSku.master_sku, MSku.product_name, component_count)
        .where(exists().where(MSkuBundle.bundle_sku_id == MSku.sku_id))
    )
    for key, value in (request_body.filter or {}).items():
        if key == 'component' and value is not None and str(value).strip():
            text_ = str(value).strip()
            comp = aliased(MSku)
            statements = statements.where(exists().where(
                MSkuBundle.bundle_sku_id == MSku.sku_id,
                or_(
                    MSkuBundle.component_sku_code.icontains(text_, autoescape=True),
                    exists().where(
                        comp.sku_id == MSkuBundle.component_sku_id,
                        or_(comp.sku_master_code.icontains(text_, autoescape=True),
                            comp.master_sku.icontains(text_, autoescape=True),
                            comp.product_name.icontains(text_, autoescape=True)),
                    ),
                ),
            ))
        else:
            statements = _filter_sku(statements, key, value)

    count = db.session.execute(select(func.count()).select_from(statements.subquery())).scalar_one()
    statements = _sort(statements, request_body.sort, {**_SORT_COLUMNS, 'componentCount': component_count})
    rows = db.session.execute(statements.offset(request_body.offset).limit(request_body.size)).all()

    comp = aliased(MSku)
    parts = db.session.execute(
        select(MSkuBundle, comp.sku_master_code, comp.product_name)
        .outerjoin(comp, comp.sku_id == MSkuBundle.component_sku_id)
        .where(MSkuBundle.bundle_sku_id.in_([r.sku_id for r in rows]))
        .order_by(MSkuBundle.bundle_sku_id, MSkuBundle.component_seq)
    ).all() if rows else []
    components: dict[int, list[dict]] = {}
    for b, code, name in parts:
        price = _num(b.component_price)
        components.setdefault(b.bundle_sku_id, []).append({
            'seq': b.component_seq,
            'id': b.component_sku_id,
            'skuId': code,
            'sellerSku': b.component_sku_code,
            'productName': name,
            'qty': b.qty,
            'unitPrice': price,
            'subtotal': None if price is None else round(price * b.qty, 2),
            # share of the bundle price, in percent
            'priceRatio': None if b.price_ratio is None else round(float(b.price_ratio) * 100, 2),
            'dqFlags': _flags(b.dq_flag),
        })

    records = []
    for r in rows:
        items = components.get(r.sku_id, [])
        subtotals = [c['subtotal'] for c in items]
        records.append({
            'id': r.sku_id,
            'skuId': r.sku_master_code,
            'sellerSku': r.master_sku,
            'productName': r.product_name,
            'componentCount': r.component_count,
            'totalQty': sum(c['qty'] for c in items),
            # bundle price = sum of component price x qty; unknown when a component has no price
            'bundlePrice': None if None in subtotals else round(sum(subtotals), 2),
            'components': items,
        })
    return {'records': records, 'meta': _meta(request_body, count)}


def search_skus(query: str, limit: int) -> list[dict]:
    """SKU options for a picker: code, latest seller SKU, any older seller SKU or name contains `query`."""
    statements = select(MSku.sku_id, MSku.sku_master_code, MSku.master_sku, MSku.product_name).where(_not_merging())
    query = query.strip()
    if query:
        statements = statements.where(or_(
            MSku.sku_master_code.icontains(query, autoescape=True),
            MSku.master_sku.icontains(query, autoescape=True),
            MSku.product_name.icontains(query, autoescape=True),
            exists().where(
                MSkuAlias.sku_id == MSku.sku_id,
                MSkuAlias.sku_code.icontains(query, autoescape=True),
            ),
        ))
    rows = db.session.execute(
        statements.order_by(MSku.sku_master_code.asc(), MSku.sku_id.asc()).limit(limit)
    ).all()
    return [{
        'id': r.sku_id,
        'skuId': r.sku_master_code,
        'sellerSku': r.master_sku,
        'productName': r.product_name,
    } for r in rows]


def _ensure_sku(sku_id: int) -> None:
    if db.session.get(MSku, sku_id) is None:
        abort(404, description='SKU not found')


# Seller SKU timeline of every listing that belongs to the SKU now or had a
# version under it. m_sku_history only stores version >= 2, so version 1 is
# rebuilt: the old seller SKU of version 2 (from its valid_from), or the
# listing's current seller SKU (from its first order) when it never changed.
# The SKU of version 1 is only known when the listing has no history.
_HISTORY_SQL = text(f"""
WITH listing AS (
    SELECT platform_sku_id FROM {SCHEMA}.m_platform_sku WHERE sku_id = :sku_id
    UNION
    SELECT platform_sku_id FROM {SCHEMA}.m_sku_history WHERE sku_id = :sku_id
), first_change AS (
    SELECT DISTINCT ON (h.platform_sku_id) h.platform_sku_id, h.old_seller_sku, h.valid_from
    FROM {SCHEMA}.m_sku_history h
    JOIN listing l ON l.platform_sku_id = h.platform_sku_id
    ORDER BY h.platform_sku_id, h.version
), timeline AS (
    SELECT p.platform_sku_id, 1 AS version, NULL::text AS old_seller_sku,
           COALESCE(f.old_seller_sku, p.current_seller_sku) AS new_seller_sku,
           COALESCE(f.valid_from, p.first_order_at) AS valid_from,
           NULL::timestamptz AS changed_at,
           CASE WHEN f.platform_sku_id IS NULL THEN p.sku_id END AS sku_id,
           NULL::text AS dq_flag
    FROM listing l
    JOIN {SCHEMA}.m_platform_sku p ON p.platform_sku_id = l.platform_sku_id
    LEFT JOIN first_change f ON f.platform_sku_id = l.platform_sku_id
    UNION ALL
    SELECT h.platform_sku_id, h.version, h.old_seller_sku, h.new_seller_sku,
           h.valid_from, h.changed_at, h.sku_id, h.dq_flag
    FROM {SCHEMA}.m_sku_history h
    JOIN listing l ON l.platform_sku_id = h.platform_sku_id
)
SELECT t.platform_sku_id, t.version, t.old_seller_sku, t.new_seller_sku,
       t.valid_from, t.changed_at, t.dq_flag,
       c.channel_name, p.merchant_sku, s.sku_master_code
FROM timeline t
JOIN {SCHEMA}.m_platform_sku p ON p.platform_sku_id = t.platform_sku_id
JOIN {SCHEMA}.m_channel c ON c.channel_id = p.channel_id
LEFT JOIN {SCHEMA}.m_sku s ON s.sku_id = t.sku_id
ORDER BY COALESCE(t.changed_at, t.valid_from) NULLS FIRST,
         c.channel_name, p.merchant_sku, t.version
""")


def get_history(sku_id: int) -> list[dict]:
    """Seller SKU changes of the SKU's listings, oldest first."""
    _ensure_sku(sku_id)
    rows = db.session.execute(_HISTORY_SQL, {'sku_id': sku_id}).all()
    return [{
        'platformSkuId': r.platform_sku_id,
        'channel': r.channel_name,
        'merchantSku': r.merchant_sku,
        'version': r.version,
        'oldSellerSku': r.old_seller_sku,
        'newSellerSku': r.new_seller_sku,
        # SKU master of this version; null when unknown (version 1 of a changed listing)
        'skuId': r.sku_master_code,
        'validFrom': r.valid_from,
        'changedAt': r.changed_at,
        'dqFlag': r.dq_flag,
    } for r in rows]


def get_platforms(sku_id: int) -> list[dict]:
    """All marketplace listings of the SKU, per channel with the latest first."""
    _ensure_sku(sku_id)
    is_latest = (func.row_number().over(
        partition_by=MPlatformSku.channel_id,
        order_by=(
            MPlatformSku.updated_at.desc(),
            MPlatformSku.first_order_at.desc().nulls_last(),
            MPlatformSku.platform_sku_id.desc(),
        ),
    ) == 1).label('is_latest')
    statements = (
        select(MPlatformSku, MChannel.channel_name, is_latest)
        .join(MChannel, MChannel.channel_id == MPlatformSku.channel_id)
        .where(MPlatformSku.sku_id == sku_id)
        .subquery()
    )
    rows = db.session.execute(
        select(statements).order_by(
            statements.c.channel_name,
            statements.c.is_latest.desc(),
            statements.c.updated_at.desc(),
            statements.c.platform_sku_id.desc(),
        )
    ).all()
    return [{
        'platformSkuId': r.platform_sku_id,
        'channel': r.channel_name,
        'merchantSku': r.merchant_sku,
        'currentSellerSku': r.current_seller_sku,
        'productName': r.product_name,
        'isOnMasterSku': r.is_on_master_sku,
        'isLatest': r.is_latest,
        'firstOrderAt': r.first_order_at,
        'updatedAt': r.updated_at,
    } for r in rows]
