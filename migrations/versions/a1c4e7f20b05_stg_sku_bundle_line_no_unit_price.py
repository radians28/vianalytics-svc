"""stg_sku_bundle: line_no and unit_price columns for the SKU bundling upload

Revision ID: a1c4e7f20b05
Revises: a1c4e7f20b04
Create Date: 2026-11-07 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1c4e7f20b05'
down_revision = 'a1c4e7f20b04'
branch_labels = None
depends_on = None

SCHEMA = 'royal_canin'


def upgrade():
    op.add_column('stg_sku_bundle', sa.Column('line_no', sa.Text(), comment='header asli: Line No'), schema=SCHEMA)
    op.add_column('stg_sku_bundle', sa.Column('unit_price', sa.Text(), comment='header asli: Unit Price'), schema=SCHEMA)
    op.execute(f"COMMENT ON TABLE {SCHEMA}.stg_sku_bundle IS "
               "'as-is: file upload SKU bundling (svc /api/sku-master/bundles/upload) · INSERT per run'")


def downgrade():
    op.drop_column('stg_sku_bundle', 'unit_price', schema=SCHEMA)
    op.drop_column('stg_sku_bundle', 'line_no', schema=SCHEMA)
    op.execute(f"COMMENT ON TABLE {SCHEMA}.stg_sku_bundle IS "
               "'as-is: Detail SKU Bundle Royal Canin.xlsx · TRUNCATE → INSERT per run'")
