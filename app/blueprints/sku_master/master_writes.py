"""SKU master writes shared by the SKU review (upload/sku_review.py) and the bundle upload.

Every caller runs them inside its transaction after taking pg_advisory_xact_lock(SKU_LOCK_KEY), the
lock the process_sku DAG holds while it writes the master, so ids handed out as max + 1 never clash.
"""
from sqlalchemy import text

from app.extensions import db
from app.models.royal_canin import SCHEMA

# pg_advisory_xact_lock key of SKU master writes; same as LOCK_KEY in airflow/dags/sku/process.py
SKU_LOCK_KEY = 0x534B55


def q(sql: str, **params):
    return db.session.execute(text(sql.replace('{S}', SCHEMA)), params)


def lock_master():
    q('SELECT pg_advisory_xact_lock(:k)', k=SKU_LOCK_KEY)


def next_id(table: str, column: str) -> int:
    # max + 1 under the advisory lock, the id scheme of the process_sku DAG (Master.new_id)
    return q(f'SELECT coalesce(max({column}), 0) + 1 FROM {{S}}.{table}').scalar_one()


def alias_owner(code: str) -> int | None:
    return q('SELECT sku_id FROM {S}.m_sku_alias WHERE sku_code = :code', code=code).scalar()


def insert_sku(code: str | None, name: str, sku_type: str, dq_flag: str, first_order_at=None,
               bundle_flag: bool = False) -> dict:
    """A new m_sku (SKU-{id:05d}) plus, when it has a seller SKU code, its master alias."""
    sku_id = next_id('m_sku', 'sku_id')
    master_code = 'SKU-{:05d}'.format(sku_id)
    q("""
        INSERT INTO {S}.m_sku (sku_id, sku_master_code, master_sku, product_name, sku_type,
                               bundle_flag, first_order_at, dq_flag)
        VALUES (:id, :code, :master, :name, :type, :bundle, :at, :dq)
    """, id=sku_id, code=master_code, master=code, name=name, type=sku_type, bundle=bundle_flag,
      at=first_order_at, dq=dq_flag)
    if code:
        q("""
            INSERT INTO {S}.m_sku_alias (sku_code, sku_id, is_master_code, first_seen_at)
            VALUES (:code, :id, true, :at)
        """, code=code, id=sku_id, at=first_order_at)
    return {'sku_id': sku_id, 'sku_master_code': master_code, 'master_sku': code, 'product_name': name}
