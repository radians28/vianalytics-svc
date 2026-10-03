from copy import deepcopy
from werkzeug.datastructures import FileStorage

MOCK_RECORDS = [
    {
    'id': 'job-1',
    'fifoOrder': 1,
    'fileName': 'shopee_orders_batch_99.xlsx',
    'marketplace': 'Shopee',
    'size': '3.4 MB',
    'recordsSummary': '420 lines • Cleaning & transforming',
    'status': 'Processing',
    'timestamp': 'Just now',
  },
  {
    'id': 'job-2',
    'fileName': 'tokopedia_trx_unmatched.csv',
    'marketplace': 'Tokopedia',
    'size': '1.2 MB',
    'recordsSummary': '14 Unmatched SKUs (Name similarity found)',
    'status': 'Paused',
    'statusDetail': 'Paused: SKU Similarity Mismatch',
    'timestamp': '2 mins ago',
  },
  {
    'id': 'job-3',
    'fifoOrder': 2,
    'fileName': 'lazada_flashsale_log.csv',
    'marketplace': 'Lazada',
    'size': '2.1 MB',
    'recordsSummary': '180 lines • Waiting in FIFO queue',
    'status': 'Queued',
    'timestamp': '4 mins ago',
  },
  {
    'id': 'job-4',
    'fileName': 'tiktok_daily_orders_0904.xlsx',
    'marketplace': 'TikTok Shop',
    'size': '4.8 MB',
    'recordsSummary': '610 SKUs validated • All matched SKU Master (2a)',
    'status': 'Completed',
    'timestamp': '1 hour ago',
  }
]

def upload(metadata: dict, file: FileStorage):
    pass

def get_progress(filter: dict = {}, order: dict = {}, page: int = 1, size: int = 5) -> dict:
    records = deepcopy(MOCK_RECORDS)

    for k, v in filter.items():
        records = [r for r in records if r.get(k) and r.get(k) == v]

    paginated = records[(page - 1) * 5: page * 5]
    meta = {
        "page": page,
        "size": size,
        "total": len(records),
        "total_pages": (len(records) + size - 1) // size if size else 0,
    }

    return {
        'records': paginated,
        'meta': meta
    }