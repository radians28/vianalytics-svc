"""Build the sample files offered for download on the upload pages.

    .venv/bin/python vianalytics-svc/scripts/make_upload_samples.py [out_dir]

Writes into vianalytics-ui/public/templates/ by default (served by the UI as /templates/<file>):
- order_{shopee,tiktok_tokped,lazada,blibli}_sample.xlsx: the marketplace order export as the
  Airflow staging loaders read it (sheet name and header row copied from real exports in
  upload_sample_headers.json); only the columns the order load uses are filled, with dummy orders
- traffic_{shopee,tokopedia,tiktok,lazada,blibli}_sample.xlsx: each marketplace's traffic export
  layout as svc's upload/traffic.py parses it (title rows, summary rows, daily table)
- sku_bundling_sample.xlsx / .csv: the SKU bundling upload (sku_master/bundle_upload.py)

Needs openpyxl (dev only). Every value is made up; SKU codes are real seller SKUs of the master so the
samples resolve when uploaded to a database with the master loaded.
"""
import csv
import json
import os
import sys
from datetime import date, datetime, timedelta

from openpyxl import Workbook

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', '..', 'vianalytics-ui', 'public', 'templates')
HEADERS = json.load(open(os.path.join(HERE, 'upload_sample_headers.json'), encoding='utf-8'))

# (seller SKU, product name, unit price) of real master SKUs
KITTEN = ('37/010100101F', 'Royal Canin Kitten (2kg) Dry Makanan Anak Kucing - Feline Health Nutrition', 257870)
INDOOR = ('37/010100101S', 'Royal Canin Indoor Long Hair (0.4kg) Dry Makanan Kucing Dewasa', 93625)
DIGESTIVE = ('37/390409901H', 'Royal Canin Digestive Care (85g x 3 pouches) Wet Makanan Kucing Dewasa', 74499)

# three orders; the second has two lines
ORDERS = [
    {'no': 1, 'at': datetime(2026, 10, 1, 9, 15), 'lines': [(KITTEN, 1, 16870)]},
    {'no': 2, 'at': datetime(2026, 10, 1, 13, 40), 'lines': [(INDOOR, 2, 0), (DIGESTIVE, 1, 4500)]},
    {'no': 3, 'at': datetime(2026, 10, 2, 20, 5), 'lines': [(DIGESTIVE, 3, 0)]},
]
CITY, PROVINCE = 'KOTA ADM. JAKARTA SELATAN', 'DKI JAKARTA'
# marketplace listing id per product (one listing per product on every platform)
LISTING = {KITTEN[0]: 1, INDOOR[0]: 2, DIGESTIVE[0]: 3}


def dot(n: float) -> str:
    """Shopee / Blibli money: dot thousands, no decimals ('257.870')."""
    return f'{int(round(n)):,}'.replace(',', '.')


def save(wb: Workbook, name: str):
    path = os.path.join(OUT, name)
    wb.save(path)
    print('wrote', os.path.relpath(path))


def sheet(wb: Workbook, title: str):
    ws = wb.active
    ws.title = title
    return ws


def order_book(channel: str, rows: list[dict], description: bool = False) -> Workbook:
    spec = HEADERS[channel]
    wb = Workbook()
    ws = sheet(wb, spec['sheet'])
    ws.append(spec['header'])
    if description:
        ws.append(spec['description'])
    for values in rows:
        unknown = set(values) - set(spec['header'])
        assert not unknown, f'{channel}: not in the export header: {unknown}'
        ws.append([values.get(h, '') for h in spec['header']])
    return wb


def orders_shopee():
    rows = []
    for o in ORDERS:
        no = f"{o['at']:%y%m%d}DMY{o['no']:04d}"
        total = sum(p * q - d for (_, _, p), q, d in o['lines'])
        for (sku, name, price), qty, disc in o['lines']:
            rows.append({
                'No. Pesanan': no, 'Status Pesanan': 'Selesai',
                'Waktu Pesanan Dibuat': f"{o['at']:%Y-%m-%d %H:%M}",
                'Waktu Pembayaran Dilakukan': f"{o['at'] + timedelta(minutes=2):%Y-%m-%d %H:%M}",
                'Waktu Pengiriman Diatur': f"{o['at'] + timedelta(hours=20):%Y-%m-%d %H:%M}",
                'Waktu Pesanan Selesai': f"{o['at'] + timedelta(days=3):%Y-%m-%d %H:%M}",
                'Nama Produk': name, 'Nomor Referensi SKU': sku, 'Nama Variasi': '',
                'Harga Awal': dot(price), 'Harga Setelah Diskon': dot(price - disc / qty),
                'Jumlah': qty, 'Returned quantity': 0,
                'Diskon Dari Penjual': dot(disc), 'Diskon Dari Shopee': '0',
                'Ongkos Kirim Dibayar oleh Pembeli': '0', 'Total Pembayaran': dot(total),
                'Opsi Pengiriman': 'Reguler (Cashless)-SPX Standard', 'Metode Pembayaran': 'ShopeePay',
                'Nama Gudang': 'WH Cakung', 'Username (Pembeli)': f"sample_buyer_{o['no']}",
                'Kota/Kabupaten': CITY, 'Provinsi': PROVINCE,
            })
    save(order_book('shopee', rows), 'order_shopee_sample.xlsx')


def orders_tiktok_tokped():
    rows = []
    for o in ORDERS:
        channel = 'Tokopedia' if o['no'] == 2 else 'TikTok'
        total = sum(p * q - d for (_, _, p), q, d in o['lines'])
        for (sku, name, price), qty, disc in o['lines']:
            rows.append({
                'Order ID': f"58600000000000{o['no']:04d}", 'Order Status': 'Selesai', 'Order Substatus': 'Selesai',
                'SKU ID': f'17310000000000{LISTING[sku]:05d}', 'Seller SKU': sku, 'Product Name': name, 'Variation': '',
                'Quantity': qty, 'Sku Quantity of return': 0, 'SKU Unit Original Price': price,
                'SKU Seller Discount': disc, 'SKU Platform Discount': 0, 'Original Shipping Fee': 21500,
                'Order Amount': total,
                'Created Time': f"{o['at']:%d/%m/%Y %H:%M:%S}",
                'Paid Time': f"{o['at'] + timedelta(minutes=2):%d/%m/%Y %H:%M:%S}",
                'Shipped Time': f"{o['at'] + timedelta(hours=20):%d/%m/%Y %H:%M:%S}",
                'Delivered Time': f"{o['at'] + timedelta(days=3):%d/%m/%Y %H:%M:%S}",
                'Warehouse Name': 'WH Cakung', 'Delivery Option': 'Pengiriman standar',
                'Buyer Username': f"sample_buyer_{o['no']}", 'Province': PROVINCE, 'Regency and City': CITY,
                'Payment Method': 'Transfer bank', 'Purchase Channel': channel,
            })
    save(order_book('tiktok_tokped', rows, description=True), 'order_tiktok_tokped_sample.xlsx')


def orders_lazada():
    rows = []
    for o in ORDERS:
        item = 0
        for (sku, name, price), qty, disc in o['lines']:
            for _ in range(qty):                         # Lazada: one row per unit
                item += 1
                rows.append({
                    'orderItemId': f"27000000000{o['no']:02d}{item:03d}", 'orderNumber': f"2700000000{o['no']:04d}",
                    'sellerSku': sku, 'lazadaSku': f"6780000000_ID-{LISTING[sku]:05d}", 'itemName': name,
                    'variation': '', 'createTime': f"{o['at']:%d %b %Y %H:%M}",
                    'deliveredDate': f"{o['at'] + timedelta(days=3):%d %b %Y %H:%M}", 'status': 'delivered',
                    'unitPrice': f'{price:.2f}', 'paidPrice': f'{price - disc / qty:.2f}',
                    'sellerDiscountTotal': f'{-disc / qty:.2f}', 'platformDiscountTotal': '',
                    'shippingFee': '0.00', 'customerName': f"Sample Buyer {o['no']}",
                    'shippingCity': 'Kota Jakarta Selatan', 'shippingAddress3': 'DKI Jakarta',
                    'payMethod': 'QRIS', 'shippingProvider': 'J&T', 'wareHouse': 'WH Cakung',
                })
    save(order_book('lazada', rows), 'order_lazada_sample.xlsx')


def orders_blibli():
    rows = []
    for o in ORDERS:
        for i, ((sku, name, price), qty, disc) in enumerate(o['lines'], start=1):
            rows.append({
                'Nomor pesanan': f"1219000{o['no']:04d}", 'Nomor Item pesanan': f"1227000{o['no']:02d}{i:02d}",
                'Tanggal pesanan': f"{o['at']:%d/%m/%Y %H:%M}", 'Nama pelanggan': f"Sample Buyer {o['no']}",
                'Kota': 'Kota Jakarta Selatan', 'Provinsi': 'DKI Jakarta', 'Nama logistik': 'JNT CASHLESS',
                'SKU seller': sku, 'Nama produk': name, 'Total produk': qty,
                'SKU Blibli': f'ROC-60036-00{LISTING[sku]:03d}-00001', 'Lokasi pengambilan': 'WH Cakung',
                'Harga produk': f'Rp{dot(price)}', 'Total': f'Rp{dot(price * qty - disc)}',
                'Diskon produk ditanggung Seller': f'-Rp{dot(disc)}' if disc else 'Rp0',
                'Diskon produk ditanggung Blibli': 'Rp0', 'Status pesanan': 'Terkirim',
                'Tanggal pengiriman': f"{o['at'] + timedelta(days=1):%d/%m/%Y %H:%M}",
            })
    save(order_book('blibli', rows), 'order_blibli_sample.xlsx')


# ------------------------------------------------------------------------------------------ traffic

DAYS = [date(2026, 10, 1) + timedelta(days=i) for i in range(7)]
VISITORS = [7614, 7086, 7432, 8518, 9786, 10721, 9895]


def traffic_shopee():
    wb = Workbook()
    ws = sheet(wb, 'All')
    header = ['Date', 'Page Views', 'Avg. Page Views', 'Avg. Time Spent', 'Bounce Rate', 'Visitors',
              'New Visitors', 'Existing Visitors', 'New Followers']
    ws.append(header)                                    # period summary table first
    ws.append([f'{DAYS[0]:%d-%m-%Y}-{DAYS[-1]:%d-%m-%Y}', dot(sum(VISITORS) * 3), '3,20', '00:01:00', '51,72%',
               dot(sum(VISITORS)), dot(sum(VISITORS) * 0.6), dot(sum(VISITORS) * 0.4), '312'])
    ws.append([])
    ws.append(header)                                    # the daily table: the last Date header
    for d, v in zip(DAYS, VISITORS):
        ws.append([f'{d:%d-%m-%Y}', dot(v * 3), '3,10', '00:01:02', '56,96%', dot(v), dot(v * 0.55),
                   dot(v * 0.45), '31'])
    for extra in ('PC', 'APP'):
        wb.create_sheet(extra).append(header)
    save(wb, 'traffic_shopee_sample.xlsx')


def traffic_tiktok_tokopedia(name: str):
    wb = Workbook()
    ws = sheet(wb, 'Sheet1')
    cols = ['GMV', 'Pesanan', 'Pembeli', 'Produk terjual', 'Pengembalian dana', 'Pesanan SKU', 'Pendapatan bruto',
            'Tayangan halaman', 'Pengunjung', 'Persentase konversi']
    ws.append([f'Tanggal analisis: {DAYS[0]:%d/%m/%Y} - {DAYS[-1]:%d/%m/%Y}'])
    ws.append(['Ringkasan data'])
    ws.append([''] + cols)
    ws.append(['Total nilai', 650000000, 3100, 2900, 3900, 90000000, 3300, 700000000, 160000, sum(VISITORS), 0.05])
    ws.append([])
    ws.append([])
    ws.append(['Data harian'])
    ws.append(['Tanggal'] + cols)
    for d, v in zip(DAYS, VISITORS):
        ws.append([f'{d:%d/%m/%Y}', v * 12000, v // 17, v // 18, v // 13, 2500000, v // 16, v * 13000, v * 2, v,
                   round(1 / 17, 6)])
    save(wb, f'traffic_{name}_sample.xlsx')


def traffic_lazada():
    wb = Workbook()
    ws = sheet(wb, 'Kunci Metrik')
    cols = ['Tanggal', 'Pendapatan', 'Pengunjung', 'Pembeli', 'Pesanan', 'Tayangan Halaman', 'Unit Terjual',
            'Tingkat Konversi', 'Pendapatan per Pembeli', 'Nilai Pengunjung']
    ws.append(['Sumber Data: Lazada Business Advisor (sample)'])
    ws.append(['Untuk data selengkapnya, kunjungi Business Advisor'])
    ws.append([])
    ws.append([])
    ws.append([])
    ws.append(cols)
    ws.append([f'{DAYS[0]:%Y-%m-%d}~{DAYS[-1]:%Y-%m-%d}', '15400000.00', str(sum(v // 14 for v in VISITORS)),
               '30', '32', '9800', '41', '0.80%', '481250.00', '4012.50'])     # period total: not a day
    ws.append(['-'] * len(cols))
    for d, v in zip(DAYS, VISITORS):
        ws.append([f'{d:%Y-%m-%d}', '2200000.00', str(v // 14), '4', '4', '1400', '6', '0.70%', '550000.00',
                   '4000.00'])
    wb.create_sheet('Definisi Metrik').append(['Metrik', 'Definisi'])
    save(wb, 'traffic_lazada_sample.xlsx')


def traffic_blibli():
    wb = Workbook()
    ws = sheet(wb, 'Overall Traffic Funnel')
    ws.append([f'Blibli Seller Analytics - Traffic - {DAYS[0]:%d %b %Y} - {DAYS[-1]:%d %b %Y} (sample)'])
    for _ in range(4):
        ws.append([])
    ws.append(['Traffic Funnel Summary', '', '', '', '', '', '', 'Traffic Funnel Data'])
    ws.append(['Homepage', 'Visit', 'Landing page', 'Added to Cart', 'Checkout attempt', 'Orders', '',
               'Date', 'Homepage', 'Visit', 'Landing page', 'Added to Cart', 'Checkout attempt', 'Orders'])
    for i, (d, v) in enumerate(zip(DAYS, VISITORS)):
        left = [3100, sum(v // 60 for v in VISITORS), 1200, 35, 30, 12, ''] if i == 0 else [''] * 7
        ws.append(left + [f'{d:%Y-%m-%d}', v // 25, v // 60, v // 62, 3, 2, 1])
    for extra in ('Affiliate Traffic', 'Blibli Paid Traffic', 'Blibli Organic Traffic'):
        wb.create_sheet(extra).append(['Date', 'Visit'])
    save(wb, 'traffic_blibli_sample.xlsx')


# ------------------------------------------------------------------------------------------- bundle

BUNDLE_HEADER = ['Bundle SKU', 'Bundle Product Name', 'Line No', 'Component SKU', 'Component Product Name',
                 'Qty', 'Unit Price']
BUNDLE_ROWS = [
    # a priced bundle (a real one, as in the master): the ratio follows unit price x qty
    ['37/390109901B', 'BDL - FHN FIT32 400G + (6pcs) FHN INSTINCTIVE 12X85G', 1, '37/010100101K',
     'FHN FIT32 400G (12)', 1, 78500],
    ['37/390109901B', 'BDL - FHN FIT32 400G + (6pcs) FHN INSTINCTIVE 12X85G', 2, '37/020100201G',
     'FHN INSTINCTIVE 12X85G (12) - PCS', 6, 21958],
    # SAMPLE/ codes are not in the master: uploading the sample registers them as new SKUs.
    # A bundle with a free gift (name 'B - ...' or code 37/B...): the gift gets price 0 and no share
    ['SAMPLE/BDL-GIFT', 'BDL - FHN KITTEN 2K + FREE TOTE BAG (sample)', 1, '37/010100101F',
     'FHN KITTEN 2K (6)', 1, 257870],
    ['SAMPLE/BDL-GIFT', 'BDL - FHN KITTEN 2K + FREE TOTE BAG (sample)', 2, 'SAMPLE/GIFT-TOTE',
     'B - Tote Bag Royal Canin (sample)', 1, ''],
    # a bundle without prices: split by quantity (equal_split)
    ['SAMPLE/BDL-SPLIT', 'BDL - INSTINCTIVE 85G x 2 + DIGESTIVE 85G x 1 (sample)', 1, '37/020100201G',
     'FHN INSTINCTIVE 12X85G (12) - PCS', 2, ''],
    ['SAMPLE/BDL-SPLIT', 'BDL - INSTINCTIVE 85G x 2 + DIGESTIVE 85G x 1 (sample)', 2, '37/020400201A',
     'FHN DIGESTIVE SENS 12X85G (12) - PCS', 1, ''],
]


def bundles():
    wb = Workbook()
    ws = sheet(wb, 'SKU Bundling')
    ws.append(BUNDLE_HEADER)
    for row in BUNDLE_ROWS:
        ws.append(row)
    save(wb, 'sku_bundling_sample.xlsx')
    path = os.path.join(OUT, 'sku_bundling_sample.csv')
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(BUNDLE_HEADER)
        w.writerows(BUNDLE_ROWS)
    print('wrote', os.path.relpath(path))


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    orders_shopee()
    orders_tiktok_tokped()
    orders_lazada()
    orders_blibli()
    traffic_shopee()
    traffic_tiktok_tokopedia('tiktok')
    traffic_tiktok_tokopedia('tokopedia')
    traffic_lazada()
    traffic_blibli()
    bundles()
