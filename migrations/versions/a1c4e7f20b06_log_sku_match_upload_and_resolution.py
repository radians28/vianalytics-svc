"""log_sku_match_upload (a review row shared by every upload that holds the listing) and
log_sku_match.resolution

Revision ID: a1c4e7f20b06
Revises: a1c4e7f20b05
Create Date: 2026-11-08 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1c4e7f20b06'
down_revision = 'a1c4e7f20b05'
branch_labels = None
depends_on = None

SCHEMA = 'royal_canin'
TS_COMMENT = 'timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'


def upgrade():
    op.create_table(
        'log_sku_match_upload',
        sa.Column('match_id', sa.BigInteger(), nullable=False),
        sa.Column('upload_id', sa.String(length=36), nullable=False),
        sa.Column('run_id', sa.BigInteger()),
        sa.Column('order_line_count', sa.Integer(), comment='baris order listing ini di upload tsb'),
        sa.Column('first_order_at', sa.DateTime(timezone=True), comment=TS_COMMENT),
        sa.Column('last_order_at', sa.DateTime(timezone=True), comment=TS_COMMENT),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'),
                  comment=TS_COMMENT),
        sa.PrimaryKeyConstraint('match_id', 'upload_id', name='pk_log_sku_match_upload'),
        sa.ForeignKeyConstraint(['match_id'], [f'{SCHEMA}.log_sku_match.match_id'],
                                name='fk_log_sku_match_upload_match', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['upload_id'], ['upload_progress.upload_id'],
                                name='fk_log_sku_match_upload_upload', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['run_id'], [f'{SCHEMA}.log_etl_run.run_id'], name='fk_log_sku_match_upload_run'),
        schema=SCHEMA,
        comment='upload yang memuat listing review (log_sku_match); satu baris review bisa menahan beberapa upload',
    )
    op.create_index('ix_log_sku_match_upload_upload_id', 'log_sku_match_upload', ['upload_id'], schema=SCHEMA)
    op.execute(f"""
        INSERT INTO {SCHEMA}.log_sku_match_upload (match_id, upload_id, run_id, order_line_count,
                                                   first_order_at, last_order_at)
        SELECT match_id, upload_id, run_id, order_line_count, first_order_at, last_order_at
        FROM {SCHEMA}.log_sku_match WHERE upload_id IS NOT NULL
    """)

    op.add_column('log_sku_match', sa.Column(
        'resolution', sa.Text(),
        comment="cara diputuskan: manual (user) · sibling (ikut keputusan seller SKU yang sama) · "
                "auto_created (DAG membuat SKU baru, baris order sudah dimuat) · auto_mapped (DAG menemukan "
                "listing sudah dikenal)"), schema=SCHEMA)
    op.execute(f"""
        UPDATE {SCHEMA}.log_sku_match
        SET resolution = CASE WHEN status = 'PENDING' THEN NULL
                              WHEN resolved_by = 'auto' AND status = 'CREATED_NEW' THEN 'auto_created'
                              WHEN resolved_by = 'auto' THEN 'auto_mapped'
                              ELSE 'manual' END
    """)
    op.create_check_constraint(
        'ck_log_sku_match_4', 'log_sku_match',
        "resolution IS NULL OR resolution IN ('manual','sibling','auto_created','auto_mapped')", schema=SCHEMA)
    op.create_index('ix_log_sku_match_sku_code_pending', 'log_sku_match', ['sku_code'], schema=SCHEMA,
                    postgresql_where=sa.text("status = 'PENDING' AND sku_code <> ''"))


def downgrade():
    op.drop_index('ix_log_sku_match_sku_code_pending', table_name='log_sku_match', schema=SCHEMA)
    op.drop_constraint('ck_log_sku_match_4', 'log_sku_match', schema=SCHEMA)
    op.drop_column('log_sku_match', 'resolution', schema=SCHEMA)
    op.drop_index('ix_log_sku_match_upload_upload_id', table_name='log_sku_match_upload', schema=SCHEMA)
    op.drop_table('log_sku_match_upload', schema=SCHEMA)
