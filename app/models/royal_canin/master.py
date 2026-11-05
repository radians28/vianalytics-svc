"""Layer M: master data (channel, city, SKU golden record, aliases, listings, bundle BOM).

Generated from sku_consolidation/ddl_royal_canin.sql; keep both in sync until the SQL file is retired.
"""
import sqlalchemy as sa
from app.extensions import db
from app.models.royal_canin import SCHEMA


class MChannel(db.Model):
    __tablename__ = 'm_channel'
    __table_args__ = (
        sa.PrimaryKeyConstraint('channel_id', name='pk_m_channel'),
        sa.UniqueConstraint('channel_code', name='uq_m_channel_channel_code'),
        {'schema': SCHEMA, 'comment': '5 channel · atribut aturan GMV 2'},
    )

    channel_id = db.Column(sa.Integer(), sa.Identity(always=False), nullable=False)
    channel_code = db.Column(sa.Text(), nullable=False)
    channel_name = db.Column(sa.Text(), nullable=False)
    sku_source_column = db.Column(sa.Text())
    order_ts_format = db.Column(sa.Text(), nullable=False, comment='format to_timestamp jam order di file mentah (jam dinding WIB); dipakai: royal_canin.to_jakarta_ts(kolom_waktu, order_ts_format)')
    gmv2_dedup_by_order = db.Column(sa.Boolean(), nullable=False, server_default=sa.text('false'))
    is_active = db.Column(sa.Boolean(), nullable=False, server_default=sa.text('true'))
    created_at = db.Column(sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')


class MCity(db.Model):
    __tablename__ = 'm_city'
    __table_args__ = (
        sa.PrimaryKeyConstraint('city_id', name='pk_m_city'),
        sa.UniqueConstraint('city_name', 'province_name', name='uq_m_city_city_name_province_name'),
        {'schema': SCHEMA, 'comment': 'kota + provinsi sesuai penulisan marketplace (tanpa normalisasi)'},
    )

    city_id = db.Column(sa.Integer(), sa.Identity(always=False), nullable=False)
    city_name = db.Column(sa.Text(), nullable=False)
    province_name = db.Column(sa.Text(), nullable=False)
    created_at = db.Column(sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')


class MSku(db.Model):
    __tablename__ = 'm_sku'
    __table_args__ = (
        sa.PrimaryKeyConstraint('sku_id', name='pk_m_sku'),
        sa.UniqueConstraint('sku_master_code', name='uq_m_sku_sku_master_code'),
        sa.UniqueConstraint('master_sku', name='uq_m_sku_master_sku'),
        sa.CheckConstraint("sku_type IN ('single','multipack','bundle','free_gift','near_expired','unknown')", name='ck_m_sku_1'),
        {'schema': SCHEMA, 'comment': 'golden record lintas channel · 1 baris per produk fisik'},
    )

    sku_id = db.Column(sa.Integer(), sa.Identity(always=False), nullable=False)
    sku_master_code = db.Column(sa.Text(), nullable=False, comment='id bisnis SKU master, mis. SKU-00001')
    master_sku = db.Column(sa.Text(), comment='kode seller SKU terkini (golden record, hasil survivorship R4)')
    product_name = db.Column(sa.Text(), nullable=False)
    sku_type = db.Column(sa.Text(), nullable=False, server_default=sa.text("'unknown'"))
    bundle_flag = db.Column(sa.Boolean(), nullable=False, server_default=sa.text('false'), comment='true bila SKU didefinisikan sebagai bundle di file Detail SKU Bundle')
    first_order_at = db.Column(sa.DateTime(timezone=True), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
    dq_flag = db.Column(sa.Text())
    created_at = db.Column(sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
    updated_at = db.Column(sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')


class MSkuAlias(db.Model):
    __tablename__ = 'm_sku_alias'
    __table_args__ = (
        sa.PrimaryKeyConstraint('sku_code', name='pk_m_sku_alias'),
        sa.ForeignKeyConstraint(['sku_id'], ['royal_canin.m_sku.sku_id'], name='fk_m_sku_alias_sku_id'),
        sa.Index('ix_m_sku_alias_sku_id', 'sku_id'),
        {'schema': SCHEMA, 'comment': 'semua kode seller SKU (bersih) → master · lookup ETL'},
    )

    sku_code = db.Column(sa.Text(), nullable=False, comment='seller SKU yang sudah distandardisasi (R1), mis. TKP_25220040 -> 25220040')
    sku_id = db.Column(sa.Integer(), nullable=False)
    is_master_code = db.Column(sa.Boolean(), nullable=False, server_default=sa.text('false'))
    first_seen_at = db.Column(sa.DateTime(timezone=True), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
    created_at = db.Column(sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')


class MPlatformSku(db.Model):
    __tablename__ = 'm_platform_sku'
    __table_args__ = (
        sa.PrimaryKeyConstraint('platform_sku_id', name='pk_m_platform_sku'),
        sa.UniqueConstraint('channel_id', 'merchant_sku', name='uq_m_platform_sku_channel_id_merchant_sku'),
        sa.ForeignKeyConstraint(['sku_id'], ['royal_canin.m_sku.sku_id'], name='fk_m_platform_sku_sku_id'),
        sa.ForeignKeyConstraint(['channel_id'], ['royal_canin.m_channel.channel_id'], name='fk_m_platform_sku_channel_id'),
        sa.Index('ix_m_platform_sku_sku_id', 'sku_id'),
        {'schema': SCHEMA, 'comment': '1 baris per listing marketplace (channel × merchant SKU)'},
    )

    platform_sku_id = db.Column(sa.Integer(), sa.Identity(always=False), nullable=False)
    channel_id = db.Column(sa.Integer(), nullable=False)
    merchant_sku = db.Column(sa.Text(), nullable=False, comment='SKU ID platform; Shopee: SHP_ + md5(nama produk|variasi)[:12]')
    sku_id = db.Column(sa.Integer(), nullable=False)
    current_seller_sku = db.Column(sa.Text())
    product_name = db.Column(sa.Text())
    is_on_master_sku = db.Column(sa.Boolean(), nullable=False, server_default=sa.text('false'))
    first_order_at = db.Column(sa.DateTime(timezone=True), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
    created_at = db.Column(sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
    updated_at = db.Column(sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')


class MSkuHistory(db.Model):
    __tablename__ = 'm_sku_history'
    __table_args__ = (
        sa.PrimaryKeyConstraint('history_id', name='pk_m_sku_history'),
        sa.UniqueConstraint('platform_sku_id', 'version', name='uq_m_sku_history_platform_sku_id_version'),
        sa.CheckConstraint('version >= 2', name='ck_m_sku_history_1'),
        sa.CheckConstraint('changed_at >= valid_from', name='ck_m_sku_history_2'),
        sa.ForeignKeyConstraint(['platform_sku_id'], ['royal_canin.m_platform_sku.platform_sku_id'], name='fk_m_sku_history_platform_sku_id'),
        sa.ForeignKeyConstraint(['sku_id'], ['royal_canin.m_sku.sku_id'], name='fk_m_sku_history_sku_id'),
        sa.Index('ix_m_sku_history_sku_id', 'sku_id'),
        {'schema': SCHEMA, 'comment': 'perubahan seller SKU pada listing yang sama (SCD 2)'},
    )

    history_id = db.Column(sa.BigInteger(), sa.Identity(always=False), nullable=False)
    platform_sku_id = db.Column(sa.Integer(), nullable=False)
    sku_id = db.Column(sa.Integer(), nullable=False)
    version = db.Column(sa.Integer(), nullable=False)
    old_seller_sku = db.Column(sa.Text())
    new_seller_sku = db.Column(sa.Text(), nullable=False)
    valid_from = db.Column(sa.DateTime(timezone=True), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
    changed_at = db.Column(sa.DateTime(timezone=True), nullable=False, comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
    dq_flag = db.Column(sa.Text())


class MSkuBundle(db.Model):
    __tablename__ = 'm_sku_bundle'
    __table_args__ = (
        sa.PrimaryKeyConstraint('bundle_sku_id', 'component_seq', name='pk_m_sku_bundle'),
        sa.CheckConstraint('qty > 0', name='ck_m_sku_bundle_1'),
        sa.CheckConstraint('component_seq > 0', name='ck_m_sku_bundle_2'),
        sa.CheckConstraint('component_price >= 0', name='ck_m_sku_bundle_3'),
        sa.CheckConstraint('price_ratio BETWEEN 0 AND 1', name='ck_m_sku_bundle_4'),
        sa.ForeignKeyConstraint(['bundle_sku_id'], ['royal_canin.m_sku.sku_id'], name='fk_m_sku_bundle_bundle_sku_id', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['component_sku_id'], ['royal_canin.m_sku.sku_id'], name='fk_m_sku_bundle_component_sku_id'),
        sa.Index('ix_m_sku_bundle_component_sku_id', 'component_sku_id'),
        {'schema': SCHEMA, 'comment': 'bill of materials dari file bundle · komponen sudah diratakan (bundle dalam bundle diuraikan sampai komponen akhir)'},
    )

    bundle_sku_id = db.Column(sa.Integer(), nullable=False)
    component_seq = db.Column(sa.Integer(), nullable=False)
    component_sku_id = db.Column(sa.Integer(), comment='komponen yang belum pernah terjual ditambahkan ke m_sku (dq_flag from_bundle_master), sehingga selalu terisi')
    component_sku_code = db.Column(sa.Text(), nullable=False)
    qty = db.Column(sa.Integer(), nullable=False)
    component_price = db.Column(sa.Numeric(precision=18, scale=2), comment='harga satuan komponen dari file bundling price; 0 untuk hadiah gratis (kode 37/B... atau nama berawalan "B - ")')
    price_ratio = db.Column(sa.Numeric(precision=9, scale=8), comment='porsi harga komponen dalam bundle = harga x qty / total (harga x qty); jumlah per bundle = 1; pembagi alokasi GMV item bundle. Bila ada harga kosong atau semua harga 0: rasio qty dan dq_flag equal_split')
    dq_flag = db.Column(sa.Text(), comment='daftar dipisah koma: free_gift, flattened, equal_split, price_gap, qty_missing, dup_component, nested_bundle')
    created_at = db.Column(sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
