"""Traffic upload: a marketplace's daily visitors export -> royal_canin.stg_traffic -> t_traffic.

Loaded by svc directly (no Airflow): the files are a few hundred rows. Layouts are ported from
sku_consolidation/step1_stg_traffic.py; each channel's export has a daily table whose header holds
a date column and a visitors column further right.

1. stg_traffic gets the daily rows as-is (periode / pengunjung text), one log_etl_run per upload
2. t_traffic gets one row per channel and day (period_start = period_end), upserted on
   (channel_id, period_start, period_end), so re-uploading an overlapping export updates the days
"""
import os
import re
from dataclasses import dataclass
from datetime import date, datetime

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from app.blueprints.sku_master.master_writes import q
from app.blueprints.upload.service import UploadError
from app.common.helpers import gen_uuid, jakarta_now
from app.common.logger import get_logger
from app.common.sheet_reader import SheetError, read_rows
from app.extensions import db
from app.models.upload import UploadProgress

logger = get_logger(__name__)

UPLOAD_TYPE = 'traffic'
HEADER_SEARCH_ROWS = 30
DATE_RE = re.compile(r'^(\d{2}-\d{2}-\d{4}|\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})( 00:00:00)?$')
DATE_FORMATS = ('%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d')


@dataclass(frozen=True)
class Layout:
    channel_code: str               # m_channel.channel_code
    sheets: tuple[str, ...]         # preferred sheet, else the first one
    date_header: str
    visitor_header: str
    last_header: bool = False       # Shopee: the daily table is the last "Date" header of the sheet


# Traffic exports are per platform, so TikTok Shop and Tokopedia are separate channels here
LAYOUTS = {
    'shopee': Layout('SHOPEE', ('All',), 'Date', 'Visitors', last_header=True),
    'tokopedia': Layout('TOKOPEDIA', (), 'Tanggal', 'Pengunjung'),
    'tiktok': Layout('TIKTOK', (), 'Tanggal', 'Pengunjung'),
    'lazada': Layout('LAZADA', (), 'Tanggal', 'Pengunjung'),
    'blibli': Layout('BLIBLI', ('Overall Traffic Funnel',), 'Date', 'Visit'),
}


@dataclass
class DayRow:
    row_no: int                     # file row number, 1-based
    periode: str                    # as in the file
    pengunjung: str | None
    day: date
    visitors: int


def _find_header(rows, layout: Layout) -> tuple[int, int, int]:
    """(header row index, date column, visitor column); the visitor column is right of the date."""
    found = None
    limit = len(rows) if layout.last_header else min(len(rows), HEADER_SEARCH_ROWS)
    for i in range(limit):
        row = rows[i]
        if layout.date_header not in row:
            continue
        c = row.index(layout.date_header)
        for j in range(c + 1, len(row)):
            if row[j] == layout.visitor_header:
                found = (i, c, j)
                break
        if found and not layout.last_header:
            return found
    if found is None:
        raise UploadError(
            f"No '{layout.date_header}' / '{layout.visitor_header}' header found. "
            f"Is this a {layout.channel_code.title()} traffic export?")
    return found


def _parse_date(text: str) -> date:
    value = text[:10]
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f'unreadable date {text!r}')


def _parse_visitors(text: str | None) -> int:
    """'2.204' (Shopee, dot thousands), '2,204' or '2204' -> 2204."""
    if text is None:
        return 0
    digits = re.sub(r'[.,\s]', '', text)
    if not digits.isdigit():
        raise ValueError(f'visitors {text!r} is not a number')
    return int(digits)


def parse(data: bytes, channel: str) -> tuple[list[DayRow], list[dict], list[str]]:
    """Daily rows of the export, the rows skipped with a reason, and warnings."""
    layout = LAYOUTS[channel]
    try:
        rows = read_rows(data, layout.sheets)
    except SheetError as err:
        raise UploadError(str(err)) from err
    h, dc, vc = _find_header(rows, layout)

    days: dict[date, DayRow] = {}
    skipped, warnings = [], []
    for i in range(h + 1, len(rows)):
        row = rows[i]
        periode = row[dc] if dc < len(row) else None
        if periode is None or not DATE_RE.match(periode):
            continue                    # totals, separators, notes (e.g. Lazada '2026-06-01~2026-06-30')
        pengunjung = row[vc] if vc < len(row) else None
        try:
            day, visitors = _parse_date(periode), _parse_visitors(pengunjung)
        except ValueError as err:
            skipped.append({'row': i + 1, 'reason': str(err)})
            continue
        if day in days:
            warnings.append(f'{day:%d %b %Y} appears more than once; row {i + 1} is used')
        days[day] = DayRow(i + 1, periode, pengunjung, day, visitors)

    if not days:
        raise UploadError('No daily traffic rows found under the header', 400)
    return sorted(days.values(), key=lambda d: d.day), skipped, warnings


def upload_traffic(metadata: dict, file: FileStorage, user: str) -> dict:
    channel = str(metadata.get('channel') or '').strip().lower()
    if channel not in LAYOUTS:
        raise UploadError(f"Invalid channel. Allowed channels: {', '.join(sorted(LAYOUTS))}")
    layout = LAYOUTS[channel]
    data = file.read()
    original_name = file.filename or 'traffic'
    days, skipped, warnings = parse(data, channel)

    upload_id = gen_uuid()
    extension = original_name.rsplit('.', 1)[-1].lower() if '.' in original_name else 'xlsx'
    file_path = os.path.join(os.path.abspath(current_app.config['UPLOAD_FOLDER']), f'{upload_id}.{extension}')
    file_name = secure_filename(original_name) or f'{upload_id}.{extension}'
    now = jakarta_now()
    summary = {
        'rows': len(days) + len(skipped),
        'days': len(days),
        'periodStart': days[0].day.isoformat(),
        'periodEnd': days[-1].day.isoformat(),
        'skipped': skipped,
        'warnings': warnings,
    }

    try:
        with open(file_path, 'wb') as f:
            f.write(data)
        progress = UploadProgress(
            upload_id=upload_id, file_name=file_name, file_path=file_path, channel=channel,
            status='Completed', total_rows=summary['rows'], processed_rows=len(days),
            meta_data={'channel': channel, 'upload_type': UPLOAD_TYPE, 'size': len(data),
                       'days': len(days), 'period_start': summary['periodStart'],
                       'period_end': summary['periodEnd']},
            queued_at=now, processed_at=now, finished_at=now,
        )
        db.session.add(progress)
        db.session.flush()

        channel_id = q('SELECT channel_id FROM {S}.m_channel WHERE channel_code = :c',
                       c=layout.channel_code).scalar()
        if channel_id is None:
            raise UploadError(f'Channel {layout.channel_code} is missing from m_channel', 500)
        run_id = q("""
            INSERT INTO {S}.log_etl_run (status, channels, source_files, triggered_by, upload_id, finished_at)
            VALUES ('SUCCESS', :ch, :file, :by, :id, now()) RETURNING run_id
        """, ch=layout.channel_code, file=file_name, by=user, id=upload_id).scalar_one()
        q("""
            INSERT INTO {S}.stg_traffic (channel_code, periode, pengunjung, source_file, source_row_no, load_run_id)
            SELECT :ch, p, v, :file, n, :run
            FROM unnest(CAST(:p AS text[]), CAST(:v AS text[]), CAST(:n AS int[])) AS u(p, v, n)
        """, ch=layout.channel_code, file=file_name, run=run_id,
          p=[d.periode for d in days], v=[d.pengunjung for d in days], n=[d.row_no for d in days])
        result = q("""
            INSERT INTO {S}.t_traffic (channel_id, period_start, period_end, visitor, etl_run_id)
            SELECT :ch, d, d, v, :run FROM unnest(CAST(:d AS date[]), CAST(:v AS int[])) AS u(d, v)
            ON CONFLICT (channel_id, period_start, period_end)
            DO UPDATE SET visitor = EXCLUDED.visitor, etl_run_id = EXCLUDED.etl_run_id
            RETURNING (xmax = 0) AS inserted
        """, ch=channel_id, run=run_id, d=[d.day for d in days], v=[d.visitors for d in days]).scalars().all()
        inserted = sum(1 for r in result if r)
        progress.meta_data = {**progress.meta_data, 'inserted': inserted, 'updated': len(result) - inserted,
                              'run_id': run_id}
        db.session.commit()
    except Exception as err:
        db.session.rollback()
        if os.path.exists(file_path):
            os.remove(file_path)
        logger.error('Traffic upload %s (%s) failed: %s', file_name, channel, err)
        _record_failure(upload_id, file_name, file_path, channel, len(data), err)
        if isinstance(err, UploadError):
            raise
        raise UploadError('Traffic could not be saved', 500) from err

    return {
        'upload': progress.to_dict(),
        'channel': channel,
        **summary,
        'inserted': inserted,
        'updated': len(result) - inserted,
        'runId': run_id,
    }


def _record_failure(upload_id: str, file_name: str, file_path: str, channel: str, size: int, err: Exception):
    """A Failed upload_progress row, so the failed file still shows in the traffic history."""
    try:
        now = jakarta_now()
        db.session.add(UploadProgress(
            upload_id=upload_id, file_name=file_name, file_path=file_path, channel=channel, status='Failed',
            error_message=getattr(err, 'message', None) or str(err),
            meta_data={'channel': channel, 'upload_type': UPLOAD_TYPE, 'size': size},
            queued_at=now, finished_at=now,
        ))
        db.session.commit()
    except Exception as record_err:
        db.session.rollback()
        logger.error('Could not record the failed traffic upload %s: %s', upload_id, record_err)
