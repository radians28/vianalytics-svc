"""log_sku_match.resolution 'rematch_created': a waiting listing given a new SKU by the
rematch_pending_skus DAG (no close name match left); its order lines are loaded by the continue DAG

Revision ID: a1c4e7f20b08
Revises: a1c4e7f20b07
Create Date: 2026-11-10 18:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'a1c4e7f20b08'
down_revision = 'a1c4e7f20b07'
branch_labels = None
depends_on = None

SCHEMA = 'royal_canin'
OLD = ('manual', 'sibling', 'auto_created', 'auto_mapped')
NEW = OLD + ('rematch_created',)
COMMENT_OLD = ("cara diputuskan: manual (user) · sibling (ikut keputusan seller SKU yang sama) · "
               "auto_created (DAG membuat SKU baru, baris order sudah dimuat) · auto_mapped (DAG menemukan "
               "listing sudah dikenal)")
COMMENT_NEW = (COMMENT_OLD + " · rematch_created (DAG rematch membuat SKU baru untuk listing yang menunggu "
               "review; baris order dimuat oleh DAG continue)")


def _check(values):
    listed = ','.join(f"'{v}'" for v in values)
    return f'resolution IS NULL OR resolution IN ({listed})'


def upgrade():
    op.drop_constraint('ck_log_sku_match_4', 'log_sku_match', schema=SCHEMA)
    op.create_check_constraint('ck_log_sku_match_4', 'log_sku_match', _check(NEW), schema=SCHEMA)
    op.execute(f"COMMENT ON COLUMN {SCHEMA}.log_sku_match.resolution IS '{COMMENT_NEW}'")


def downgrade():
    op.execute(f"""
        UPDATE {SCHEMA}.log_sku_match SET resolution = 'auto_mapped' WHERE resolution = 'rematch_created'
    """)
    op.drop_constraint('ck_log_sku_match_4', 'log_sku_match', schema=SCHEMA)
    op.create_check_constraint('ck_log_sku_match_4', 'log_sku_match', _check(OLD), schema=SCHEMA)
    op.execute(f"COMMENT ON COLUMN {SCHEMA}.log_sku_match.resolution IS '{COMMENT_OLD}'")
