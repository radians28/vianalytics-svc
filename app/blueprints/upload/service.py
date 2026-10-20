import os

from flask import current_app
from sqlalchemy import asc, case, desc, func, select
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from app.blueprints.upload.requests.progress_request import ProgressPaginationRequest
from app.common.airflow_client import AirflowError, trigger_dag
from app.common.helpers import gen_uuid, jakarta_now
from app.common.logger import get_logger
from app.common.pagination_request import SortOrder
from app.extensions import db
from app.models.upload import UploadProgress


# Airflow DAG that loads an uploaded file into staging
UPLOAD_DAG_ID = 'api_triggered_dag'

SUPPORTED_CHANNELS = {'tiktok_tokped', 'shopee', 'lazada', 'blibli'}

# Marketplace names shown in the UI per channel; the first one is displayed.
# TikTok Shop and Tokopedia share one export, so both filter to tiktok_tokped
CHANNEL_MARKETPLACES = {
    'shopee': ('Shopee',),
    'tiktok_tokped': ('TikTok Shop', 'Tokopedia'),
    'lazada': ('Lazada',),
    'blibli': ('Blibli',),
}

STATUS_PRIORITY = {'Processing': 1, 'Paused': 2, 'Queued': 3, 'Completed': 4, 'Failed': 5}

logger = get_logger(__name__)


class UploadError(Exception):
    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code


def upload(metadata: dict, file: FileStorage) -> dict:
    channel = str(metadata.get('channel') or '').strip().lower()
    if channel not in SUPPORTED_CHANNELS:
        raise UploadError(
            f"Invalid channel. Allowed channels: {', '.join(sorted(SUPPORTED_CHANNELS))}"
        )

    upload_id = gen_uuid()
    original_name = file.filename or ''
    extension = original_name.rsplit('.', 1)[1].lower()
    # Stored under the upload id so the same file name can be uploaded again;
    # the folder is shared with Airflow, which reads the file from file_path
    file_path = os.path.join(
        os.path.abspath(current_app.config['UPLOAD_FOLDER']),
        f'{upload_id}.{extension}',
    )

    # 1. queue the upload in upload_progress
    upload_progress = UploadProgress()
    upload_progress.upload_id = upload_id
    upload_progress.file_name = secure_filename(original_name) or f'{upload_id}.{extension}'
    upload_progress.file_path = file_path
    upload_progress.channel = channel
    upload_progress.status = 'Queued'
    upload_progress.meta_data = metadata
    upload_progress.queued_at = jakarta_now()

    db.session.add(upload_progress)

    # 2. put the file into the shared upload folder
    try:
        file.save(file_path)
        upload_progress.meta_data = {**metadata, 'size': os.path.getsize(file_path)}
        db.session.commit()
    except Exception:
        db.session.rollback()
        if os.path.exists(file_path):
            os.remove(file_path)
        raise

    # 3. start processing in Airflow; the file and queue record are kept on
    # failure so the run can be retried
    try:
        trigger_dag(
            UPLOAD_DAG_ID,
            conf={'upload_id': upload_id},
            dag_run_id=f'upload__{upload_id}',
        )
    except AirflowError as err:
        logger.error('Failed to trigger Airflow for upload %s: %s', upload_id, err)
        upload_progress.status = 'Failed'
        upload_progress.error_message = str(err)
        db.session.commit()
        raise UploadError('File saved but processing could not be started', 502) from err

    return upload_progress.to_dict()


def _format_size(size: int | None) -> str:
    if size is None:
        return ''
    if size < 1024 * 1024:
        return f'{size / 1024:.1f} KB'
    return f'{size / (1024 * 1024):.1f} MB'


def _status_priority():
    """Processing first, then the FIFO queue, then finished uploads (same
    order as the UI's status sorter)."""
    return case(STATUS_PRIORITY, value=UploadProgress.status, else_=len(STATUS_PRIORITY) + 1)


def _channels_for(marketplace: str) -> list[str]:
    value = marketplace.strip().lower()
    return [
        channel for channel, names in CHANNEL_MARKETPLACES.items()
        if value == channel or value in (n.lower() for n in names)
    ]


def _fifo_orders(upload_ids: list[str]) -> dict[str, int]:
    """Queue position (1-based) of the given uploads among all queued ones."""
    if not upload_ids:
        return {}
    positions = select(
        UploadProgress.upload_id,
        func.row_number().over(
            order_by=(UploadProgress.queued_at.asc(), UploadProgress.created_at.asc())
        ).label('position'),
    ).where(UploadProgress.status == 'Queued').subquery()
    rows = db.session.execute(
        select(positions.c.upload_id, positions.c.position)
        .where(positions.c.upload_id.in_(upload_ids))
    ).all()
    return {upload_id: position for upload_id, position in rows}


def get_progress(request_body: ProgressPaginationRequest) -> dict:
    statements = select(UploadProgress)

    if request_body.filter:
        for key, value in request_body.filter.items():
            if value is None or value == '':
                continue
            match key:
                case 'fileName':
                    statements = statements.where(UploadProgress.file_name.icontains(str(value)))
                case 'marketplace':
                    statements = statements.where(UploadProgress.channel.in_(_channels_for(str(value))))
                case 'status':
                    statements = statements.where(UploadProgress.status == value)

    count = db.session.execute(
        select(func.count()).select_from(statements.subquery())
    ).scalar_one()

    sort_columns = {
        'fileName': UploadProgress.file_name,
        'marketplace': UploadProgress.channel,
        'status': _status_priority(),
    }
    if request_body.sort:
        for column, order in request_body.sort.items():
            order_fn = asc if order == SortOrder.ASC else desc
            statements = statements.order_by(order_fn(sort_columns[column]))
    else:
        statements = statements.order_by(_status_priority())
    # Tie-breakers keep pages stable: FIFO for the queue, newest first otherwise
    statements = statements.order_by(
        case((UploadProgress.status == 'Queued', UploadProgress.queued_at)).asc(),
        UploadProgress.created_at.desc(),
        UploadProgress.upload_id,
    )

    statements = statements.offset(request_body.offset).limit(request_body.size)
    records = db.session.execute(statements).scalars().all()

    fifo_orders = _fifo_orders([r.upload_id for r in records if r.status == 'Queued'])

    return {
        'records': [{
            'id': r.upload_id,
            'fifoOrder': fifo_orders.get(r.upload_id),
            'fileName': r.file_name,
            'marketplace': CHANNEL_MARKETPLACES.get(r.channel, (r.channel,))[0],
            'size': _format_size((r.meta_data or {}).get('size')),
            # TODO fill from the processing results once the DAG reports them
            'recordsSummary': '',
            'status': r.status,
            'statusDetail': '',
            'timestamp': r.created_at,
        } for r in records],
        'meta': {
            'page': request_body.page,
            'size': request_body.size,
            'total': count,
            'total_pages': (count + request_body.size - 1) // request_body.size,
        },
    }
