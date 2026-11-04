"""royal_canin datamart (dm_*), log_dq_issue, log_sku_match, dm_traffic view and channel seed

Revision ID: a1c4e7f20b04
Revises: a1c4e7f20b03
Create Date: 2026-11-04 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'a1c4e7f20b04'
down_revision = 'a1c4e7f20b03'
branch_labels = None
depends_on = None

SCHEMA = 'royal_canin'


def upgrade():
    op.create_table(
        'dm_sales_daily',
        sa.Column('sales_date', sa.Date(), nullable=False, comment='tanggal kalender WIB (Asia/Jakarta)'),
        sa.Column('channel_id', sa.Integer(), nullable=False),
        sa.Column('city_id', sa.Integer(), nullable=False),
        sa.Column('warehouse_name', sa.Text(), nullable=False, comment="bagian PK: ETL mengisi 'UNKNOWN' bila kosong"),
        sa.Column('delivery_option', sa.Text(), nullable=False),
        sa.Column('payment_method', sa.Text(), nullable=False),
        sa.Column('gmv_1', sa.Numeric(precision=18, scale=2)),
        sa.Column('gmv_2', sa.Numeric(precision=18, scale=2)),
        sa.Column('order_count', sa.Integer()),
        sa.Column('buyer_count', sa.Integer()),
        sa.Column('unit_sold', sa.Integer()),
        sa.Column('aov', sa.Numeric(precision=18, scale=2)),
        sa.Column('aipo', sa.Numeric(precision=10, scale=2)),
        sa.Column('refreshed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.PrimaryKeyConstraint('sales_date', 'channel_id', 'city_id', 'warehouse_name', 'delivery_option', 'payment_method', name='pk_dm_sales_daily'),
        sa.ForeignKeyConstraint(['channel_id'], ['royal_canin.m_channel.channel_id'], name='fk_dm_sales_daily_channel_id'),
        sa.ForeignKeyConstraint(['city_id'], ['royal_canin.m_city.city_id'], name='fk_dm_sales_daily_city_id'),
        schema=SCHEMA,
        comment='GMV1/2 · order · buyer · unit · AOV · AIPO',
    )
    op.create_index('ix_dm_sales_daily_channel_id', 'dm_sales_daily', ['channel_id'], unique=False, schema=SCHEMA)
    op.create_index('ix_dm_sales_daily_city_id', 'dm_sales_daily', ['city_id'], unique=False, schema=SCHEMA)

    op.create_table(
        'dm_sales_sku_daily',
        sa.Column('sales_date', sa.Date(), nullable=False, comment='tanggal kalender WIB (Asia/Jakarta)'),
        sa.Column('channel_id', sa.Integer(), nullable=False),
        sa.Column('sku_id', sa.Integer(), nullable=False),
        sa.Column('order_count', sa.Integer()),
        sa.Column('quantity', sa.Integer()),
        sa.Column('unit_sold_component', sa.Integer(), comment='unit setelah bundle di-explode via M_SKU_BUNDLE'),
        sa.Column('gmv_1', sa.Numeric(precision=18, scale=2)),
        sa.Column('refreshed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.PrimaryKeyConstraint('sales_date', 'channel_id', 'sku_id', name='pk_dm_sales_sku_daily'),
        sa.ForeignKeyConstraint(['channel_id'], ['royal_canin.m_channel.channel_id'], name='fk_dm_sales_sku_daily_channel_id'),
        sa.ForeignKeyConstraint(['sku_id'], ['royal_canin.m_sku.sku_id'], name='fk_dm_sales_sku_daily_sku_id'),
        schema=SCHEMA,
        comment='penjualan per SKU master lintas channel',
    )
    op.create_index('ix_dm_sales_sku_daily_channel_id', 'dm_sales_sku_daily', ['channel_id'], unique=False, schema=SCHEMA)
    op.create_index('ix_dm_sales_sku_daily_sku_id', 'dm_sales_sku_daily', ['sku_id'], unique=False, schema=SCHEMA)

    op.create_table(
        'log_dq_issue',
        sa.Column('issue_id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('run_id', sa.BigInteger()),
        sa.Column('source_table', sa.Text(), nullable=False),
        sa.Column('dq_flag', sa.Text(), nullable=False),
        sa.Column('record_key', sa.Text()),
        sa.Column('sku_id', sa.Integer()),
        sa.Column('detail', sa.Text()),
        sa.Column('status', sa.Text(), nullable=False, server_default=sa.text("'OPEN'")),
        sa.Column('logged_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.PrimaryKeyConstraint('issue_id', name='pk_log_dq_issue'),
        sa.CheckConstraint("status IN ('OPEN','CONFIRMED','FIXED','IGNORED')", name='ck_log_dq_issue_1'),
        sa.ForeignKeyConstraint(['run_id'], ['royal_canin.log_etl_run.run_id'], name='fk_log_dq_issue_run_id'),
        sa.ForeignKeyConstraint(['sku_id'], ['royal_canin.m_sku.sku_id'], name='fk_log_dq_issue_sku_id'),
        schema=SCHEMA,
        comment='temuan data quality untuk data steward',
    )
    op.create_index('ix_log_dq_issue_run_id', 'log_dq_issue', ['run_id'], unique=False, schema=SCHEMA)
    op.create_index('ix_log_dq_issue_sku_id', 'log_dq_issue', ['sku_id'], unique=False, schema=SCHEMA)

    op.create_table(
        'log_sku_match',
        sa.Column('match_id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('run_id', sa.BigInteger()),
        sa.Column('upload_id', sa.String(length=36)),
        sa.Column('channel_id', sa.Integer(), nullable=False),
        sa.Column('merchant_sku', sa.Text(), nullable=False),
        sa.Column('sku_code', sa.Text(), nullable=False, server_default=sa.text("''"), comment='seller SKU bersih (R1); string kosong bila listing tanpa seller SKU'),
        sa.Column('seller_sku', sa.Text()),
        sa.Column('product_name', sa.Text()),
        sa.Column('variation', sa.Text()),
        sa.Column('first_order_at', sa.DateTime(timezone=True), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.Column('last_order_at', sa.DateTime(timezone=True), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.Column('order_line_count', sa.Integer()),
        sa.Column('suggested_sku_id', sa.Integer()),
        sa.Column('suggested_name', sa.Text()),
        sa.Column('similarity_score', sa.Numeric(precision=5, scale=4), comment='cosine similarity TF-IDF n-gram karakter (3..5) nama ternormalisasi; cocok bila >= 0.55 (jarak <= 0.45)'),
        sa.Column('candidates', postgresql.JSONB(astext_type=sa.Text()), comment='maks. 3 SKU master terdekat: [{sku_id, sku_master_code, name, score}]'),
        sa.Column('status', sa.Text(), nullable=False, server_default=sa.text("'PENDING'"), comment='PENDING: menunggu review · MAPPED: dipetakan ke SKU yang ada · CREATED_NEW: dibuat sebagai SKU baru'),
        sa.Column('resolved_sku_id', sa.Integer()),
        sa.Column('resolved_by', sa.Text(), comment="'auto' bila tidak ada nama yang mirip dan SKU baru dibuat otomatis oleh DAG, selain itu user yang memutuskan"),
        sa.Column('resolved_at', sa.DateTime(timezone=True), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.PrimaryKeyConstraint('match_id', name='pk_log_sku_match'),
        sa.CheckConstraint("status IN ('PENDING','MAPPED','CREATED_NEW')", name='ck_log_sku_match_1'),
        sa.CheckConstraint('similarity_score BETWEEN 0 AND 1', name='ck_log_sku_match_2'),
        sa.CheckConstraint("status = 'PENDING' OR resolved_sku_id IS NOT NULL", name='ck_log_sku_match_3'),
        sa.ForeignKeyConstraint(['run_id'], ['royal_canin.log_etl_run.run_id'], name='fk_log_sku_match_run_id'),
        sa.ForeignKeyConstraint(['upload_id'], ['public.upload_progress.upload_id'], name='fk_log_sku_match_upload', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['channel_id'], ['royal_canin.m_channel.channel_id'], name='fk_log_sku_match_channel_id'),
        sa.ForeignKeyConstraint(['suggested_sku_id'], ['royal_canin.m_sku.sku_id'], name='fk_log_sku_match_suggested_sku_id'),
        sa.ForeignKeyConstraint(['resolved_sku_id'], ['royal_canin.m_sku.sku_id'], name='fk_log_sku_match_resolved_sku_id'),
        schema=SCHEMA,
        comment='listing baru (seller SKU & SKU platform belum ada di master) dicocokkan berdasarkan nama produk; PENDING = menunggu keputusan di UI (SKU sanitize: petakan ke saran atau buat SKU baru)',
    )
    op.create_index('uq_log_sku_match_pending', 'log_sku_match', ['channel_id', 'merchant_sku', 'sku_code'], unique=True, schema=SCHEMA, postgresql_where=sa.text("status = 'PENDING'"))
    op.create_index('ix_log_sku_match_upload_id', 'log_sku_match', ['upload_id'], unique=False, schema=SCHEMA)
    op.create_index('ix_log_sku_match_status', 'log_sku_match', ['status'], unique=False, schema=SCHEMA)
    op.execute("""
        CREATE TRIGGER trg_log_sku_match_updated_at BEFORE UPDATE ON royal_canin.log_sku_match
        FOR EACH ROW EXECUTE FUNCTION royal_canin.set_updated_at()
    """)

    op.execute("""
        CREATE OR REPLACE VIEW royal_canin.dm_traffic AS
        SELECT t.period_start, t.period_end, t.channel_id, c.channel_code, t.visitor
        FROM royal_canin.t_traffic t
        JOIN royal_canin.m_channel c ON c.channel_id = t.channel_id
    """)
    op.execute("COMMENT ON VIEW royal_canin.dm_traffic IS 'VIEW atas T_TRAFFIC'")

    # Reference data: the five marketplaces. order_ts_format is the to_timestamp() pattern of the raw order time.
    op.execute("""
        INSERT INTO royal_canin.m_channel (channel_code, channel_name, sku_source_column, order_ts_format, gmv2_dedup_by_order) VALUES
            ('SHOPEE',    'Shopee',      'Nomor Referensi SKU', 'YYYY-MM-DD HH24:MI',      true),
            ('TOKOPEDIA', 'Tokopedia',   'Seller SKU',          'DD/MM/YYYY HH24:MI:SS',   true),
            ('TIKTOK',    'TikTok Shop', 'Seller SKU',          'DD/MM/YYYY HH24:MI:SS',   true),
            ('LAZADA',    'Lazada',      'sellerSku',           'DD Mon YYYY HH24:MI',     false),
            ('BLIBLI',    'Blibli',      'SKU seller',          'DD/MM/YYYY HH24:MI',      false)
        ON CONFLICT (channel_code) DO UPDATE SET order_ts_format = EXCLUDED.order_ts_format,
                                                 gmv2_dedup_by_order = EXCLUDED.gmv2_dedup_by_order
    """)


def downgrade():
    op.execute("DROP VIEW IF EXISTS royal_canin.dm_traffic")
    op.drop_table('log_sku_match', schema=SCHEMA)
    op.drop_table('log_dq_issue', schema=SCHEMA)
    op.drop_table('dm_sales_sku_daily', schema=SCHEMA)
    op.drop_table('dm_sales_daily', schema=SCHEMA)
