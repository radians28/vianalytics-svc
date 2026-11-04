"""royal_canin master (m_*) and transaction (t_*) tables

Revision ID: a1c4e7f20b03
Revises: a1c4e7f20b02
Create Date: 2026-11-04 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1c4e7f20b03'
down_revision = 'a1c4e7f20b02'
branch_labels = None
depends_on = None

SCHEMA = 'royal_canin'


def upgrade():
    op.create_table(
        'm_channel',
        sa.Column('channel_id', sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column('channel_code', sa.Text(), nullable=False),
        sa.Column('channel_name', sa.Text(), nullable=False),
        sa.Column('sku_source_column', sa.Text()),
        sa.Column('order_ts_format', sa.Text(), nullable=False, comment='format to_timestamp jam order di file mentah (jam dinding WIB); dipakai: royal_canin.to_jakarta_ts(kolom_waktu, order_ts_format)'),
        sa.Column('gmv2_dedup_by_order', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.PrimaryKeyConstraint('channel_id', name='pk_m_channel'),
        sa.UniqueConstraint('channel_code', name='uq_m_channel_channel_code'),
        schema=SCHEMA,
        comment='5 channel · atribut aturan GMV 2',
    )

    op.create_table(
        'm_city',
        sa.Column('city_id', sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column('city_name', sa.Text(), nullable=False),
        sa.Column('province_name', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.PrimaryKeyConstraint('city_id', name='pk_m_city'),
        sa.UniqueConstraint('city_name', 'province_name', name='uq_m_city_city_name_province_name'),
        schema=SCHEMA,
        comment='kota + provinsi sesuai penulisan marketplace (tanpa normalisasi)',
    )

    op.create_table(
        'm_sku',
        sa.Column('sku_id', sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column('sku_master_code', sa.Text(), nullable=False, comment='id bisnis SKU master, mis. SKU-00001'),
        sa.Column('master_sku', sa.Text(), comment='kode seller SKU terkini (golden record, hasil survivorship R4)'),
        sa.Column('product_name', sa.Text(), nullable=False),
        sa.Column('sku_type', sa.Text(), nullable=False, server_default=sa.text("'unknown'")),
        sa.Column('bundle_flag', sa.Boolean(), nullable=False, server_default=sa.text('false'), comment='true bila SKU didefinisikan sebagai bundle di file Detail SKU Bundle'),
        sa.Column('first_order_at', sa.DateTime(timezone=True), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.Column('dq_flag', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.PrimaryKeyConstraint('sku_id', name='pk_m_sku'),
        sa.UniqueConstraint('sku_master_code', name='uq_m_sku_sku_master_code'),
        sa.UniqueConstraint('master_sku', name='uq_m_sku_master_sku'),
        sa.CheckConstraint("sku_type IN ('single','multipack','bundle','free_gift','near_expired','unknown')", name='ck_m_sku_1'),
        schema=SCHEMA,
        comment='golden record lintas channel · 1 baris per produk fisik',
    )
    op.execute("""
        CREATE TRIGGER trg_m_sku_updated_at BEFORE UPDATE ON royal_canin.m_sku
        FOR EACH ROW EXECUTE FUNCTION royal_canin.set_updated_at()
    """)

    op.create_table(
        'm_sku_alias',
        sa.Column('sku_code', sa.Text(), nullable=False, comment='seller SKU yang sudah distandardisasi (R1), mis. TKP_25220040 -> 25220040'),
        sa.Column('sku_id', sa.Integer(), nullable=False),
        sa.Column('is_master_code', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.PrimaryKeyConstraint('sku_code', name='pk_m_sku_alias'),
        sa.ForeignKeyConstraint(['sku_id'], ['royal_canin.m_sku.sku_id'], name='fk_m_sku_alias_sku_id'),
        schema=SCHEMA,
        comment='semua kode seller SKU (bersih) → master · lookup ETL',
    )
    op.create_index('ix_m_sku_alias_sku_id', 'm_sku_alias', ['sku_id'], unique=False, schema=SCHEMA)

    op.create_table(
        'm_platform_sku',
        sa.Column('platform_sku_id', sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column('channel_id', sa.Integer(), nullable=False),
        sa.Column('merchant_sku', sa.Text(), nullable=False, comment='SKU ID platform; Shopee: SHP_ + md5(nama produk|variasi)[:12]'),
        sa.Column('sku_id', sa.Integer(), nullable=False),
        sa.Column('current_seller_sku', sa.Text()),
        sa.Column('product_name', sa.Text()),
        sa.Column('is_on_master_sku', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('first_order_at', sa.DateTime(timezone=True), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.PrimaryKeyConstraint('platform_sku_id', name='pk_m_platform_sku'),
        sa.UniqueConstraint('channel_id', 'merchant_sku', name='uq_m_platform_sku_channel_id_merchant_sku'),
        sa.ForeignKeyConstraint(['sku_id'], ['royal_canin.m_sku.sku_id'], name='fk_m_platform_sku_sku_id'),
        sa.ForeignKeyConstraint(['channel_id'], ['royal_canin.m_channel.channel_id'], name='fk_m_platform_sku_channel_id'),
        schema=SCHEMA,
        comment='1 baris per listing marketplace (channel × merchant SKU)',
    )
    op.create_index('ix_m_platform_sku_sku_id', 'm_platform_sku', ['sku_id'], unique=False, schema=SCHEMA)
    op.execute("""
        CREATE TRIGGER trg_m_platform_sku_updated_at BEFORE UPDATE ON royal_canin.m_platform_sku
        FOR EACH ROW EXECUTE FUNCTION royal_canin.set_updated_at()
    """)

    op.create_table(
        'm_sku_history',
        sa.Column('history_id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('platform_sku_id', sa.Integer(), nullable=False),
        sa.Column('sku_id', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('old_seller_sku', sa.Text()),
        sa.Column('new_seller_sku', sa.Text(), nullable=False),
        sa.Column('valid_from', sa.DateTime(timezone=True), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.Column('changed_at', sa.DateTime(timezone=True), nullable=False, comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.Column('dq_flag', sa.Text()),
        sa.PrimaryKeyConstraint('history_id', name='pk_m_sku_history'),
        sa.UniqueConstraint('platform_sku_id', 'version', name='uq_m_sku_history_platform_sku_id_version'),
        sa.CheckConstraint('version >= 2', name='ck_m_sku_history_1'),
        sa.CheckConstraint('changed_at >= valid_from', name='ck_m_sku_history_2'),
        sa.ForeignKeyConstraint(['platform_sku_id'], ['royal_canin.m_platform_sku.platform_sku_id'], name='fk_m_sku_history_platform_sku_id'),
        sa.ForeignKeyConstraint(['sku_id'], ['royal_canin.m_sku.sku_id'], name='fk_m_sku_history_sku_id'),
        schema=SCHEMA,
        comment='perubahan seller SKU pada listing yang sama (SCD 2)',
    )
    op.create_index('ix_m_sku_history_sku_id', 'm_sku_history', ['sku_id'], unique=False, schema=SCHEMA)

    op.create_table(
        'm_sku_bundle',
        sa.Column('bundle_sku_id', sa.Integer(), nullable=False),
        sa.Column('component_seq', sa.Integer(), nullable=False),
        sa.Column('component_sku_id', sa.Integer(), comment='komponen yang belum pernah terjual ditambahkan ke m_sku (dq_flag from_bundle_master), sehingga selalu terisi'),
        sa.Column('component_sku_code', sa.Text(), nullable=False),
        sa.Column('qty', sa.Integer(), nullable=False),
        sa.Column('component_price', sa.Numeric(precision=18, scale=2), comment='harga satuan komponen dari file bundling price; 0 untuk hadiah gratis (kode 37/B... atau nama berawalan "B - ")'),
        sa.Column('price_ratio', sa.Numeric(precision=9, scale=8), comment='porsi harga komponen dalam bundle = harga x qty / total (harga x qty); jumlah per bundle = 1; pembagi alokasi GMV item bundle. Bila ada harga kosong atau semua harga 0: rasio qty dan dq_flag equal_split'),
        sa.Column('dq_flag', sa.Text(), comment='daftar dipisah koma: free_gift, flattened, equal_split, price_gap, qty_missing, dup_component, nested_bundle'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.PrimaryKeyConstraint('bundle_sku_id', 'component_seq', name='pk_m_sku_bundle'),
        sa.CheckConstraint('qty > 0', name='ck_m_sku_bundle_1'),
        sa.CheckConstraint('component_seq > 0', name='ck_m_sku_bundle_2'),
        sa.CheckConstraint('component_price >= 0', name='ck_m_sku_bundle_3'),
        sa.CheckConstraint('price_ratio BETWEEN 0 AND 1', name='ck_m_sku_bundle_4'),
        sa.ForeignKeyConstraint(['bundle_sku_id'], ['royal_canin.m_sku.sku_id'], name='fk_m_sku_bundle_bundle_sku_id', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['component_sku_id'], ['royal_canin.m_sku.sku_id'], name='fk_m_sku_bundle_component_sku_id'),
        schema=SCHEMA,
        comment='bill of materials dari file bundle · komponen sudah diratakan (bundle dalam bundle diuraikan sampai komponen akhir)',
    )
    op.create_index('ix_m_sku_bundle_component_sku_id', 'm_sku_bundle', ['component_sku_id'], unique=False, schema=SCHEMA)

    op.create_table(
        't_order',
        sa.Column('order_id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('channel_id', sa.Integer(), nullable=False),
        sa.Column('order_no', sa.Text(), nullable=False),
        sa.Column('city_id', sa.Integer()),
        sa.Column('order_status', sa.Text()),
        sa.Column('order_created_at', sa.DateTime(timezone=True), nullable=False, comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.Column('order_paid_at', sa.DateTime(timezone=True), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.Column('order_shipped_at', sa.DateTime(timezone=True), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.Column('order_completed_at', sa.DateTime(timezone=True), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.Column('order_date', sa.Date(), sa.Computed("(order_created_at AT TIME ZONE 'Asia/Jakarta')::date", persisted=True), nullable=False, comment="GENERATED: tanggal WIB dari order_created_at (AT TIME ZONE 'Asia/Jakarta')"),
        sa.Column('buyer_username', sa.Text()),
        sa.Column('warehouse_name', sa.Text()),
        sa.Column('delivery_option', sa.Text()),
        sa.Column('payment_method', sa.Text()),
        sa.Column('item_line_count', sa.Integer()),
        sa.Column('total_quantity', sa.Integer()),
        sa.Column('shipping_fee', sa.Numeric(precision=18, scale=2)),
        sa.Column('gmv_2', sa.Numeric(precision=18, scale=2), comment='GMV level order: nilai order diambil sekali per order bila m_channel.gmv2_dedup_by_order (Shopee, TikTok, Tokopedia), selain itu dijumlah per baris item (Lazada, Blibli)'),
        sa.Column('etl_run_id', sa.BigInteger()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.PrimaryKeyConstraint('order_id', name='pk_t_order'),
        sa.UniqueConstraint('channel_id', 'order_no', name='uq_t_order_channel_id_order_no'),
        sa.CheckConstraint('item_line_count >= 0', name='ck_t_order_1'),
        sa.CheckConstraint('total_quantity >= 0', name='ck_t_order_2'),
        sa.ForeignKeyConstraint(['channel_id'], ['royal_canin.m_channel.channel_id'], name='fk_t_order_channel_id'),
        sa.ForeignKeyConstraint(['city_id'], ['royal_canin.m_city.city_id'], name='fk_t_order_city_id'),
        sa.ForeignKeyConstraint(['etl_run_id'], ['royal_canin.log_etl_run.run_id'], name='fk_t_order_etl_run_id'),
        schema=SCHEMA,
        comment='grain: 1 baris per order (header)',
    )
    op.create_index('ix_t_order_city_id', 't_order', ['city_id'], unique=False, schema=SCHEMA)
    op.create_index('ix_t_order_etl_run_id', 't_order', ['etl_run_id'], unique=False, schema=SCHEMA)
    op.execute("""
        CREATE TRIGGER trg_t_order_updated_at BEFORE UPDATE ON royal_canin.t_order
        FOR EACH ROW EXECUTE FUNCTION royal_canin.set_updated_at()
    """)

    op.create_table(
        't_order_detail',
        sa.Column('order_detail_id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('order_id', sa.BigInteger(), nullable=False),
        sa.Column('line_key', sa.Text(), nullable=False, comment='id baris marketplace, atau <SKU platform>:<urutan>; komponen bundle diberi akhiran #<component_seq>'),
        sa.Column('platform_sku_id', sa.Integer()),
        sa.Column('sku_id', sa.Integer(), comment='NULL bila seller SKU belum terpetakan ke M_SKU (lihat LOG_DQ_ISSUE)'),
        sa.Column('seller_sku', sa.Text()),
        sa.Column('product_name', sa.Text()),
        sa.Column('item_status', sa.Text()),
        sa.Column('quantity', sa.Integer(), nullable=False, comment='qty order x qty komponen untuk item bundle'),
        sa.Column('return_quantity', sa.Integer(), server_default=sa.text('0')),
        sa.Column('unit_price', sa.Numeric(precision=18, scale=2)),
        sa.Column('seller_discount', sa.Numeric(precision=18, scale=2)),
        sa.Column('platform_discount', sa.Numeric(precision=18, scale=2)),
        sa.Column('gmv_1', sa.Numeric(precision=18, scale=2), comment='GMV level item = harga awal x qty sebelum diskon; item bundle dibagi ke komponen dengan m_sku_bundle.price_ratio'),
        sa.Column('unit_sold', sa.Integer()),
        sa.Column('is_bundle', sa.Boolean(), nullable=False, server_default=sa.text('false'), comment='true bila baris berasal dari penguraian SKU bundle'),
        sa.Column('etl_run_id', sa.BigInteger()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.PrimaryKeyConstraint('order_detail_id', name='pk_t_order_detail'),
        sa.UniqueConstraint('order_id', 'line_key', name='uq_t_order_detail_order_id_line_key'),
        sa.CheckConstraint('quantity >= 0', name='ck_t_order_detail_1'),
        sa.CheckConstraint('return_quantity >= 0', name='ck_t_order_detail_2'),
        sa.CheckConstraint('unit_sold >= 0', name='ck_t_order_detail_3'),
        sa.ForeignKeyConstraint(['order_id'], ['royal_canin.t_order.order_id'], name='fk_t_order_detail_order_id', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['platform_sku_id'], ['royal_canin.m_platform_sku.platform_sku_id'], name='fk_t_order_detail_platform_sku_id'),
        sa.ForeignKeyConstraint(['sku_id'], ['royal_canin.m_sku.sku_id'], name='fk_t_order_detail_sku_id'),
        sa.ForeignKeyConstraint(['etl_run_id'], ['royal_canin.log_etl_run.run_id'], name='fk_t_order_detail_etl_run_id'),
        schema=SCHEMA,
        comment='grain: 1 baris per item / SKU dalam order',
    )
    op.create_index('ix_t_order_detail_platform_sku_id', 't_order_detail', ['platform_sku_id'], unique=False, schema=SCHEMA)
    op.create_index('ix_t_order_detail_sku_id', 't_order_detail', ['sku_id'], unique=False, schema=SCHEMA)
    op.create_index('ix_t_order_detail_etl_run_id', 't_order_detail', ['etl_run_id'], unique=False, schema=SCHEMA)
    op.execute("""
        CREATE TRIGGER trg_t_order_detail_updated_at BEFORE UPDATE ON royal_canin.t_order_detail
        FOR EACH ROW EXECUTE FUNCTION royal_canin.set_updated_at()
    """)

    op.create_table(
        't_order_detail_dq',
        sa.Column('order_detail_id', sa.BigInteger(), nullable=False),
        sa.Column('dq_flag', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('order_detail_id', name='pk_t_order_detail_dq'),
        sa.ForeignKeyConstraint(['order_detail_id'], ['royal_canin.t_order_detail.order_detail_id'], name='fk_t_order_detail_dq_order_detail_id', ondelete='CASCADE'),
        schema=SCHEMA,
        comment='baris item dengan catatan kualitas data; equal_split = bundle tanpa harga komponen (semua 0 / kosong), nilai dibagi menurut qty',
    )

    op.create_table(
        't_traffic',
        sa.Column('traffic_id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('channel_id', sa.Integer(), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False, comment='tanggal kalender WIB (Asia/Jakarta)'),
        sa.Column('period_end', sa.Date(), nullable=False, comment='tanggal kalender WIB (Asia/Jakarta)'),
        sa.Column('visitor', sa.Integer(), nullable=False),
        sa.Column('etl_run_id', sa.BigInteger()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default'),
        sa.PrimaryKeyConstraint('traffic_id', name='pk_t_traffic'),
        sa.UniqueConstraint('channel_id', 'period_start', 'period_end', name='uq_t_traffic_channel_id_period_start_period_end'),
        sa.CheckConstraint('period_end >= period_start', name='ck_t_traffic_1'),
        sa.CheckConstraint('visitor >= 0', name='ck_t_traffic_2'),
        sa.ForeignKeyConstraint(['channel_id'], ['royal_canin.m_channel.channel_id'], name='fk_t_traffic_channel_id'),
        sa.ForeignKeyConstraint(['etl_run_id'], ['royal_canin.log_etl_run.run_id'], name='fk_t_traffic_etl_run_id'),
        schema=SCHEMA,
        comment='periode · channel · visitor',
    )
    op.create_index('ix_t_traffic_etl_run_id', 't_traffic', ['etl_run_id'], unique=False, schema=SCHEMA)
    op.execute("""
        CREATE TRIGGER trg_t_traffic_updated_at BEFORE UPDATE ON royal_canin.t_traffic
        FOR EACH ROW EXECUTE FUNCTION royal_canin.set_updated_at()
    """)


def downgrade():
    op.drop_table('t_traffic', schema=SCHEMA)
    op.drop_table('t_order_detail_dq', schema=SCHEMA)
    op.drop_table('t_order_detail', schema=SCHEMA)
    op.drop_table('t_order', schema=SCHEMA)
    op.drop_table('m_sku_bundle', schema=SCHEMA)
    op.drop_table('m_sku_history', schema=SCHEMA)
    op.drop_table('m_platform_sku', schema=SCHEMA)
    op.drop_table('m_sku_alias', schema=SCHEMA)
    op.drop_table('m_sku', schema=SCHEMA)
    op.drop_table('m_city', schema=SCHEMA)
    op.drop_table('m_channel', schema=SCHEMA)
