"""log_sku_change: merge / split of SKU masters (SKU Master page) and the state of moving their
stored order lines (DAG reassign_sku_orders)

Revision ID: a1c4e7f20b09
Revises: a1c4e7f20b08
Create Date: 2026-11-11 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'a1c4e7f20b09'
down_revision = 'a1c4e7f20b08'
branch_labels = None
depends_on = None

SCHEMA = 'royal_canin'
TS_COMMENT = 'timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'


def upgrade():
    op.create_table(
        'log_sku_change',
        sa.Column('change_id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('run_id', sa.BigInteger(), nullable=False, comment='log_etl_run perubahan ini'),
        sa.Column('kind', sa.Text(), nullable=False,
                  comment='MERGE: SKU sumber digabung ke SKU tujuan lalu dihapus · SPLIT: seller SKU / listing '
                          'terpilih dipindah dari SKU sumber ke SKU tujuan (baru atau yang sudah ada)'),
        sa.Column('source_sku_id', sa.Integer(), nullable=False,
                  comment='SKU sumber; tanpa FK karena MERGE menghapus SKU ini'),
        sa.Column('source_code', sa.Text(), nullable=False, comment='sku_master_code SKU sumber'),
        sa.Column('target_sku_id', sa.Integer(), nullable=False, comment='SKU tujuan'),
        sa.Column('target_code', sa.Text(), nullable=False, comment='sku_master_code SKU tujuan'),
        sa.Column('target_created', sa.Boolean(), nullable=False, server_default=sa.text('false'),
                  comment='SPLIT ke SKU baru yang dibuat oleh perubahan ini'),
        sa.Column('items', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  comment='yang dipindah: {codes: [seller SKU], listing_ids: [platform_sku_id]}'),
        sa.Column('snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  comment='isi master kedua SKU sebelum perubahan (m_sku, alias, listing, history, bundle)'),
        sa.Column('bundle', postgresql.JSONB(astext_type=sa.Text()),
                  comment='pemecahan ulang baris bundle: {sku_id, old_bom, new_bom} atau NULL'),
        sa.Column('status', sa.Text(), nullable=False, server_default=sa.text("'PENDING'"),
                  comment='PENDING: master sudah diubah, baris order belum dipindah · RUNNING · DONE · FAILED'),
        sa.Column('counts', postgresql.JSONB(astext_type=sa.Text()), comment='hasil pemindahan baris order'),
        sa.Column('message', sa.Text()),
        sa.Column('created_by', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'),
                  comment=TS_COMMENT),
        sa.Column('finished_at', sa.DateTime(timezone=True), comment=TS_COMMENT),
        sa.PrimaryKeyConstraint('change_id', name='pk_log_sku_change'),
        sa.CheckConstraint("kind IN ('MERGE','SPLIT')", name='ck_log_sku_change_1'),
        sa.CheckConstraint("status IN ('PENDING','RUNNING','DONE','FAILED')", name='ck_log_sku_change_2'),
        sa.ForeignKeyConstraint(['run_id'], [f'{SCHEMA}.log_etl_run.run_id'], name='fk_log_sku_change_run_id'),
        schema=SCHEMA,
        comment='merge / split SKU master dari halaman SKU Master, dan status pemindahan baris order yang sudah '
                'dimuat (DAG reassign_sku_orders)',
    )
    op.create_index('ix_log_sku_change_status', 'log_sku_change', ['status'], schema=SCHEMA)
    op.create_index('ix_log_sku_change_source', 'log_sku_change', ['source_sku_id'], schema=SCHEMA)
    op.create_index('ix_log_sku_change_target', 'log_sku_change', ['target_sku_id'], schema=SCHEMA)


def downgrade():
    op.drop_index('ix_log_sku_change_target', table_name='log_sku_change', schema=SCHEMA)
    op.drop_index('ix_log_sku_change_source', table_name='log_sku_change', schema=SCHEMA)
    op.drop_index('ix_log_sku_change_status', table_name='log_sku_change', schema=SCHEMA)
    op.drop_table('log_sku_change', schema=SCHEMA)
