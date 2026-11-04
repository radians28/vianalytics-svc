"""Layer T: orders, order lines and traffic.

Generated from sku_consolidation/ddl_royal_canin.sql; keep both in sync until the SQL file is retired.
"""
import sqlalchemy as sa
from app.extensions import db
from app.models.royal_canin import SCHEMA


class TOrder(db.Model):
    __tablename__ = 't_order'
    __table_args__ = (
        sa.PrimaryKeyConstraint('order_id', name='pk_t_order'),
        sa.UniqueConstraint('channel_id', 'order_no', name='uq_t_order_channel_id_order_no'),
        sa.CheckConstraint('item_line_count >= 0', name='ck_t_order_1'),
        sa.CheckConstraint('total_quantity >= 0', name='ck_t_order_2'),
        sa.ForeignKeyConstraint(['channel_id'], ['royal_canin.m_channel.channel_id'], name='fk_t_order_channel_id'),
        sa.ForeignKeyConstraint(['city_id'], ['royal_canin.m_city.city_id'], name='fk_t_order_city_id'),
        sa.ForeignKeyConstraint(['etl_run_id'], ['royal_canin.log_etl_run.run_id'], name='fk_t_order_etl_run_id'),
        sa.Index('ix_t_order_city_id', 'city_id'),
        sa.Index('ix_t_order_etl_run_id', 'etl_run_id'),
        {'schema': SCHEMA, 'comment': 'grain: 1 baris per order (header)'},
    )

    order_id = db.Column(sa.BigInteger(), sa.Identity(always=False), nullable=False)
    channel_id = db.Column(sa.Integer(), nullable=False)
    order_no = db.Column(sa.Text(), nullable=False)
    city_id = db.Column(sa.Integer())
    order_status = db.Column(sa.Text())
    order_created_at = db.Column(sa.DateTime(timezone=True), nullable=False, comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
    order_paid_at = db.Column(sa.DateTime(timezone=True), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
    order_shipped_at = db.Column(sa.DateTime(timezone=True), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
    order_completed_at = db.Column(sa.DateTime(timezone=True), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
    order_date = db.Column(sa.Date(), sa.Computed("(order_created_at AT TIME ZONE 'Asia/Jakarta')::date", persisted=True), nullable=False, comment="GENERATED: tanggal WIB dari order_created_at (AT TIME ZONE 'Asia/Jakarta')")
    buyer_username = db.Column(sa.Text())
    warehouse_name = db.Column(sa.Text())
    delivery_option = db.Column(sa.Text())
    payment_method = db.Column(sa.Text())
    item_line_count = db.Column(sa.Integer())
    total_quantity = db.Column(sa.Integer())
    shipping_fee = db.Column(sa.Numeric(precision=18, scale=2))
    gmv_2 = db.Column(sa.Numeric(precision=18, scale=2), comment='GMV level order: nilai order diambil sekali per order bila m_channel.gmv2_dedup_by_order (Shopee, TikTok, Tokopedia), selain itu dijumlah per baris item (Lazada, Blibli)')
    etl_run_id = db.Column(sa.BigInteger())
    created_at = db.Column(sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
    updated_at = db.Column(sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')


class TOrderDetail(db.Model):
    __tablename__ = 't_order_detail'
    __table_args__ = (
        sa.PrimaryKeyConstraint('order_detail_id', name='pk_t_order_detail'),
        sa.UniqueConstraint('order_id', 'line_key', name='uq_t_order_detail_order_id_line_key'),
        sa.CheckConstraint('quantity >= 0', name='ck_t_order_detail_1'),
        sa.CheckConstraint('return_quantity >= 0', name='ck_t_order_detail_2'),
        sa.CheckConstraint('unit_sold >= 0', name='ck_t_order_detail_3'),
        sa.ForeignKeyConstraint(['order_id'], ['royal_canin.t_order.order_id'], name='fk_t_order_detail_order_id', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['platform_sku_id'], ['royal_canin.m_platform_sku.platform_sku_id'], name='fk_t_order_detail_platform_sku_id'),
        sa.ForeignKeyConstraint(['sku_id'], ['royal_canin.m_sku.sku_id'], name='fk_t_order_detail_sku_id'),
        sa.ForeignKeyConstraint(['etl_run_id'], ['royal_canin.log_etl_run.run_id'], name='fk_t_order_detail_etl_run_id'),
        sa.Index('ix_t_order_detail_platform_sku_id', 'platform_sku_id'),
        sa.Index('ix_t_order_detail_sku_id', 'sku_id'),
        sa.Index('ix_t_order_detail_etl_run_id', 'etl_run_id'),
        {'schema': SCHEMA, 'comment': 'grain: 1 baris per item / SKU dalam order'},
    )

    order_detail_id = db.Column(sa.BigInteger(), sa.Identity(always=False), nullable=False)
    order_id = db.Column(sa.BigInteger(), nullable=False)
    line_key = db.Column(sa.Text(), nullable=False, comment='id baris marketplace, atau <SKU platform>:<urutan>; komponen bundle diberi akhiran #<component_seq>')
    platform_sku_id = db.Column(sa.Integer())
    sku_id = db.Column(sa.Integer(), comment='NULL bila seller SKU belum terpetakan ke M_SKU (lihat LOG_DQ_ISSUE)')
    seller_sku = db.Column(sa.Text())
    product_name = db.Column(sa.Text())
    item_status = db.Column(sa.Text())
    quantity = db.Column(sa.Integer(), nullable=False, comment='qty order x qty komponen untuk item bundle')
    return_quantity = db.Column(sa.Integer(), server_default=sa.text('0'))
    unit_price = db.Column(sa.Numeric(precision=18, scale=2))
    seller_discount = db.Column(sa.Numeric(precision=18, scale=2))
    platform_discount = db.Column(sa.Numeric(precision=18, scale=2))
    gmv_1 = db.Column(sa.Numeric(precision=18, scale=2), comment='GMV level item = harga awal x qty sebelum diskon; item bundle dibagi ke komponen dengan m_sku_bundle.price_ratio')
    unit_sold = db.Column(sa.Integer())
    is_bundle = db.Column(sa.Boolean(), nullable=False, server_default=sa.text('false'), comment='true bila baris berasal dari penguraian SKU bundle')
    etl_run_id = db.Column(sa.BigInteger())
    created_at = db.Column(sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
    updated_at = db.Column(sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')


class TOrderDetailDq(db.Model):
    __tablename__ = 't_order_detail_dq'
    __table_args__ = (
        sa.PrimaryKeyConstraint('order_detail_id', name='pk_t_order_detail_dq'),
        sa.ForeignKeyConstraint(['order_detail_id'], ['royal_canin.t_order_detail.order_detail_id'], name='fk_t_order_detail_dq_order_detail_id', ondelete='CASCADE'),
        {'schema': SCHEMA, 'comment': 'baris item dengan catatan kualitas data; equal_split = bundle tanpa harga komponen (semua 0 / kosong), nilai dibagi menurut qty'},
    )

    order_detail_id = db.Column(sa.BigInteger(), nullable=False)
    dq_flag = db.Column(sa.Text(), nullable=False)


class TTraffic(db.Model):
    __tablename__ = 't_traffic'
    __table_args__ = (
        sa.PrimaryKeyConstraint('traffic_id', name='pk_t_traffic'),
        sa.UniqueConstraint('channel_id', 'period_start', 'period_end', name='uq_t_traffic_channel_id_period_start_period_end'),
        sa.CheckConstraint('period_end >= period_start', name='ck_t_traffic_1'),
        sa.CheckConstraint('visitor >= 0', name='ck_t_traffic_2'),
        sa.ForeignKeyConstraint(['channel_id'], ['royal_canin.m_channel.channel_id'], name='fk_t_traffic_channel_id'),
        sa.ForeignKeyConstraint(['etl_run_id'], ['royal_canin.log_etl_run.run_id'], name='fk_t_traffic_etl_run_id'),
        sa.Index('ix_t_traffic_etl_run_id', 'etl_run_id'),
        {'schema': SCHEMA, 'comment': 'periode · channel · visitor'},
    )

    traffic_id = db.Column(sa.BigInteger(), sa.Identity(always=False), nullable=False)
    channel_id = db.Column(sa.Integer(), nullable=False)
    period_start = db.Column(sa.Date(), nullable=False, comment='tanggal kalender WIB (Asia/Jakarta)')
    period_end = db.Column(sa.Date(), nullable=False, comment='tanggal kalender WIB (Asia/Jakarta)')
    visitor = db.Column(sa.Integer(), nullable=False)
    etl_run_id = db.Column(sa.BigInteger())
    created_at = db.Column(sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
    updated_at = db.Column(sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
