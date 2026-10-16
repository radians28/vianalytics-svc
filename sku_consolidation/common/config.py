"""Paths, channel definitions and per-channel column maps shared by all steps."""
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(BASE, "raw")
STG = os.path.join(BASE, "stg")
SKU_MASTER = os.path.join(BASE, "sku_master")
TRANSACTION = os.path.join(BASE, "transaction")
DDL = os.path.join(BASE, "ddl_royal_canin.sql")

TZ_SUFFIX = "+07"          # Asia/Jakarta has no DST: fixed +07:00 offset
TS_OUT = "%Y-%m-%d %H:%M:%S"

# channel_id follows the m_channel seed order in ddl_royal_canin.sql
CHANNELS = {
    "SHOPEE":    dict(channel_id=1, name="Shopee",      sku_source_column="Nomor Referensi SKU", ts_format="YYYY-MM-DD HH24:MI"),
    "TOKOPEDIA": dict(channel_id=2, name="Tokopedia",   sku_source_column="Seller SKU",          ts_format="DD/MM/YYYY HH24:MI:SS"),
    "TIKTOK":    dict(channel_id=3, name="TikTok Shop", sku_source_column="Seller SKU",          ts_format="DD/MM/YYYY HH24:MI:SS"),
    "LAZADA":    dict(channel_id=4, name="Lazada",      sku_source_column="sellerSku",           ts_format="DD Mon YYYY HH24:MI"),
    "BLIBLI":    dict(channel_id=5, name="Blibli",      sku_source_column="SKU seller",          ts_format="DD/MM/YYYY HH24:MI"),
}
# Shopee's order export has no item-level quantity-free gmv2 rule; order-level fields repeat on each line
GMV2_DEDUP = {"SHOPEE": True, "TOKOPEDIA": True, "TIKTOK": True, "LAZADA": False, "BLIBLI": False}

# Standard (python strptime) timestamp formats of each export
PY_TS = {
    "SHOPEE": "%Y-%m-%d %H:%M",
    "TOKOPEDIA": "%d/%m/%Y %H:%M:%S",
    "TIKTOK": "%d/%m/%Y %H:%M:%S",
    "LAZADA": "%d %b %Y %H:%M",
    "BLIBLI": "%d/%m/%Y %H:%M",
}

# stg table -> snake_case columns carrying the facts used downstream.
#   money: 'dot' = '414.090' / 'Rp391.000' style (dot = thousands), 'plain' = '175898.00'
STG_MAP = {
    "SHOPEE": dict(
        stg_table="stg_shopee", money="dot",
        order_no="no_pesanan", line_key=None, created="waktu_pesanan_dibuat",
        paid="waktu_pembayaran_dilakukan", shipped="waktu_pengiriman_diatur",
        completed="waktu_pesanan_selesai", status="status_pesanan", item_status="status_pesanan",
        seller_sku="nomor_referensi_sku", platform_sku=None, product_name="nama_produk",
        variation="nama_variasi", qty="jumlah", return_qty="returned_quantity",
        unit_price="harga_awal", seller_discount="diskon_dari_penjual",
        platform_discount="diskon_dari_shopee", buyer="username_pembeli",
        warehouse="nama_gudang", delivery="opsi_pengiriman", payment="metode_pembayaran",
        city="kota_kabupaten", province="provinsi",
        shipping_fee="ongkos_kirim_dibayar_oleh_pembeli", order_total="total_pembayaran"),
    "LAZADA": dict(
        stg_table="stg_lazada", money="plain",
        order_no="order_number", line_key="order_item_id", created="create_time",
        paid=None, shipped=None, completed="delivered_date", status="status", item_status="status",
        seller_sku="seller_sku", platform_sku="lazada_sku", product_name="item_name",
        variation="variation", qty=None, return_qty=None,
        unit_price="unit_price", seller_discount="seller_discount_total",
        platform_discount="platform_discount_total", buyer="customer_name",
        warehouse="ware_house", delivery="shipping_provider", payment="pay_method",
        city="shipping_city", province="shipping_address3",
        shipping_fee="shipping_fee", order_total="paid_price"),
    "BLIBLI": dict(
        stg_table="stg_blibli", money="dot",
        order_no="nomor_pesanan", line_key="nomor_item_pesanan", created="tanggal_pesanan",
        paid=None, shipped="tanggal_pengiriman", completed=None, status="status_pesanan",
        item_status="status_pesanan", seller_sku="sku_seller", platform_sku="sku_blibli",
        product_name="nama_produk", variation=None, qty="total_produk", return_qty=None,
        unit_price="harga_produk", seller_discount="diskon_produk_ditanggung_seller",
        platform_discount="diskon_produk_ditanggung_blibli", buyer="nama_pelanggan",
        warehouse="lokasi_pengambilan", delivery="nama_logistik", payment=None,
        city="kota", province="provinsi", shipping_fee=None, order_total="total"),
    "TIKTOK_TOKOPEDIA": dict(      # applies to both stg_tiktok and stg_tokopedia
        stg_table=None, money="plain",
        order_no="order_id", line_key=None, created="created_time",
        paid="paid_time", shipped="shipped_time", completed="delivered_time",
        status="order_status", item_status="order_substatus",
        seller_sku="seller_sku", platform_sku="sku_id", product_name="product_name",
        variation="variation", qty="quantity", return_qty="sku_quantity_of_return",
        unit_price="sku_unit_original_price", seller_discount="sku_seller_discount",
        platform_discount="sku_platform_discount", buyer="buyer_username",
        warehouse="warehouse_name", delivery="delivery_option", payment="payment_method",
        city="regency_and_city", province="province",
        shipping_fee="original_shipping_fee", order_total="order_amount"),
}
