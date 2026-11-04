"""Layer DM: daily aggregates.

Generated from sku_consolidation/ddl_royal_canin.sql; keep both in sync until the SQL file is retired.
"""
import sqlalchemy as sa
from app.extensions import db
from app.models.royal_canin import SCHEMA


class DmSalesDaily(db.Model):
    __tablename__ = 'dm_sales_daily'
    __table_args__ = (
        sa.PrimaryKeyConstraint('sales_date', 'channel_id', 'city_id', 'warehouse_name', 'delivery_option', 'payment_method', name='pk_dm_sales_daily'),
        sa.ForeignKeyConstraint(['channel_id'], ['royal_canin.m_channel.channel_id'], name='fk_dm_sales_daily_channel_id'),
        sa.ForeignKeyConstraint(['city_id'], ['royal_canin.m_city.city_id'], name='fk_dm_sales_daily_city_id'),
        sa.Index('ix_dm_sales_daily_channel_id', 'channel_id'),
        sa.Index('ix_dm_sales_daily_city_id', 'city_id'),
        {'schema': SCHEMA, 'comment': 'GMV1/2 · order · buyer · unit · AOV · AIPO'},
    )

    sales_date = db.Column(sa.Date(), nullable=False, comment='tanggal kalender WIB (Asia/Jakarta)')
    channel_id = db.Column(sa.Integer(), nullable=False)
    city_id = db.Column(sa.Integer(), nullable=False)
    warehouse_name = db.Column(sa.Text(), nullable=False, comment="bagian PK: ETL mengisi 'UNKNOWN' bila kosong")
    delivery_option = db.Column(sa.Text(), nullable=False)
    payment_method = db.Column(sa.Text(), nullable=False)
    gmv_1 = db.Column(sa.Numeric(precision=18, scale=2))
    gmv_2 = db.Column(sa.Numeric(precision=18, scale=2))
    order_count = db.Column(sa.Integer())
    buyer_count = db.Column(sa.Integer())
    unit_sold = db.Column(sa.Integer())
    aov = db.Column(sa.Numeric(precision=18, scale=2))
    aipo = db.Column(sa.Numeric(precision=10, scale=2))
    refreshed_at = db.Column(sa.DateTime(timezone=True), server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')


class DmSalesSkuDaily(db.Model):
    __tablename__ = 'dm_sales_sku_daily'
    __table_args__ = (
        sa.PrimaryKeyConstraint('sales_date', 'channel_id', 'sku_id', name='pk_dm_sales_sku_daily'),
        sa.ForeignKeyConstraint(['channel_id'], ['royal_canin.m_channel.channel_id'], name='fk_dm_sales_sku_daily_channel_id'),
        sa.ForeignKeyConstraint(['sku_id'], ['royal_canin.m_sku.sku_id'], name='fk_dm_sales_sku_daily_sku_id'),
        sa.Index('ix_dm_sales_sku_daily_channel_id', 'channel_id'),
        sa.Index('ix_dm_sales_sku_daily_sku_id', 'sku_id'),
        {'schema': SCHEMA, 'comment': 'penjualan per SKU master lintas channel'},
    )

    sales_date = db.Column(sa.Date(), nullable=False, comment='tanggal kalender WIB (Asia/Jakarta)')
    channel_id = db.Column(sa.Integer(), nullable=False)
    sku_id = db.Column(sa.Integer(), nullable=False)
    order_count = db.Column(sa.Integer())
    quantity = db.Column(sa.Integer())
    unit_sold_component = db.Column(sa.Integer(), comment='unit setelah bundle di-explode via M_SKU_BUNDLE')
    gmv_1 = db.Column(sa.Numeric(precision=18, scale=2))
    refreshed_at = db.Column(sa.DateTime(timezone=True), server_default=sa.text('now()'), comment='timestamptz: instan waktu absolut; tampil dalam Asia/Jakarta (WIB) pada session TimeZone default')
