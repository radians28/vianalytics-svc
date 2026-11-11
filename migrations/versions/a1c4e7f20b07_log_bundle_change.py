"""log_bundle_change: component list before / after a SKU bundling upload, and the state of
re-splitting the order lines already loaded with the old list

Revision ID: a1c4e7f20b07
Revises: a1c4e7f20b06
Create Date: 2026-11-08 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'a1c4e7f20b07'
down_revision = 'a1c4e7f20b06'
branch_labels = None
depends_on = None

SCHEMA = 'royal_canin'
TS_COMMENT = 'timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'


def upgrade():
    op.create_table(
        'log_bundle_change',
        sa.Column('change_id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('run_id', sa.BigInteger(), nullable=False, comment='log_etl_run upload SKU bundling'),
        sa.Column('bundle_sku_id', sa.Integer(), nullable=False),
        sa.Column('old_bom', postgresql.JSONB(astext_type=sa.Text()),
                  comment='komponen sebelum upload [{seq, component_sku_id, qty, price_ratio, dq_flag}]; NULL bila '
                          'SKU belum bundle'),
        sa.Column('new_bom', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  comment='komponen setelah upload, format sama'),
        sa.Column('status', sa.Text(), nullable=False, server_default=sa.text("'PENDING'"),
                  comment='PENDING: baris order lama belum dipecah ulang · RUNNING · DONE · FAILED · SKIPPED '
                          '(tidak diminta)'),
        sa.Column('lines_rebuilt', sa.Integer(), comment='baris order asli yang dipecah ulang'),
        sa.Column('lines_mismatch', sa.Integer(),
                  comment='baris yang tidak bisa dibangun ulang dari komponen lama (dq rebundle_mismatch)'),
        sa.Column('orders_touched', sa.Integer()),
        sa.Column('message', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'),
                  comment=TS_COMMENT),
        sa.Column('processed_at', sa.DateTime(timezone=True), comment=TS_COMMENT),
        sa.PrimaryKeyConstraint('change_id', name='pk_log_bundle_change'),
        sa.CheckConstraint("status IN ('PENDING','RUNNING','DONE','FAILED','SKIPPED')", name='ck_log_bundle_change_1'),
        sa.ForeignKeyConstraint(['run_id'], [f'{SCHEMA}.log_etl_run.run_id'], name='fk_log_bundle_change_run_id'),
        sa.ForeignKeyConstraint(['bundle_sku_id'], [f'{SCHEMA}.m_sku.sku_id'], name='fk_log_bundle_change_bundle_sku_id'),
        schema=SCHEMA,
        comment='perubahan komponen bundle per upload SKU bundling, dan status pemecahan ulang baris order yang '
                'sudah dimuat (DAG reconsolidate_bundle_orders)',
    )
    op.create_index('ix_log_bundle_change_status', 'log_bundle_change', ['status'], schema=SCHEMA)
    op.create_index('ix_log_bundle_change_run_id', 'log_bundle_change', ['run_id'], schema=SCHEMA)


def downgrade():
    op.drop_index('ix_log_bundle_change_run_id', table_name='log_bundle_change', schema=SCHEMA)
    op.drop_index('ix_log_bundle_change_status', table_name='log_bundle_change', schema=SCHEMA)
    op.drop_table('log_bundle_change', schema=SCHEMA)
