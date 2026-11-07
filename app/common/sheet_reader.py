"""Read an uploaded spreadsheet (xlsx, xls or CSV) as rows of text cells.

For the uploads svc loads itself (traffic, SKU bundling). Ported from the Airflow staging reader
(airflow/dags/staging/common.py: open_source, _detect_encoding, _detect_delimiter): the format
comes from the file's content, not its extension, so a CSV saved as .xlsx still loads.
"""
import codecs
import csv
import io
from datetime import date, datetime

XLSX_SIGNATURE = b'PK\x03\x04'                          # zip container
XLS_SIGNATURE = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'     # OLE2 compound file
CSV_DELIMITERS = ',;\t|'
CSV_SAMPLE_CHARS = 64 * 1024
BLANK = {'', '-', 'nan', 'None'}


class SheetError(ValueError):
    """The file can't be read as a spreadsheet."""


def cell_text(value) -> str | None:
    """Cell -> trimmed text; blank, '-', 'nan' -> None. Excel numbers and dates become plain text."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)                              # 12.0 -> '12'
    elif isinstance(value, datetime):
        value = value.strftime('%Y-%m-%d') if value.time() == datetime.min.time() \
            else value.strftime('%Y-%m-%d %H:%M:%S')
    elif isinstance(value, date):
        value = value.strftime('%Y-%m-%d')
    text = str(value).replace('\x00', '').strip()       # Lazada .xls cells carry NUL bytes
    return None if text in BLANK else text


def file_format(data: bytes) -> str:
    if data.startswith(XLSX_SIGNATURE):
        return 'xlsx'
    if data.startswith(XLS_SIGNATURE):
        return 'xls'
    return 'csv'


def read_rows(data: bytes, sheet_names: tuple[str, ...] = ()) -> list[list[str | None]]:
    """All rows of the file. For Excel the first sheet named in `sheet_names` is used, else the
    first sheet."""
    if not data:
        raise SheetError('The file is empty')
    kind = file_format(data)
    try:
        rows = _excel_rows(data, sheet_names) if kind in ('xlsx', 'xls') else _csv_rows(data)
    except SheetError:
        raise
    except Exception as err:                            # corrupt workbook, wrong encoding, ...
        raise SheetError(f'Could not read the file as {kind}: {err}') from err
    rows = [[cell_text(v) for v in row] for row in rows]
    if not any(any(v is not None for v in row) for row in rows):
        raise SheetError('The file has no data')
    return rows


def sheet_names_of(data: bytes) -> list[str]:
    if file_format(data) == 'csv':
        return []
    from python_calamine import CalamineWorkbook
    return CalamineWorkbook.from_filelike(io.BytesIO(data)).sheet_names


def _excel_rows(data: bytes, sheet_names: tuple[str, ...]) -> list[list]:
    from python_calamine import CalamineWorkbook

    workbook = CalamineWorkbook.from_filelike(io.BytesIO(data))
    by_name = {name.lower(): name for name in workbook.sheet_names}
    wanted = next((by_name[n.lower()] for n in sheet_names if n.lower() in by_name), None)
    sheet = workbook.get_sheet_by_name(wanted) if wanted else workbook.get_sheet_by_index(0)
    return list(sheet.iter_rows())


def _csv_rows(data: bytes) -> list[list]:
    text = _decode(data)
    delimiter = _detect_delimiter(text[:CSV_SAMPLE_CHARS])
    return list(csv.reader(io.StringIO(text, newline=''), delimiter=delimiter))


def _decode(data: bytes) -> str:
    """UTF-8 (with or without BOM), else Windows-1252, which Excel on Windows uses for CSV."""
    try:
        return codecs.decode(data, 'utf-8-sig')
    except UnicodeDecodeError:
        return data.decode('cp1252', errors='replace')


def _detect_delimiter(sample: str) -> str:
    """Comma, semicolon (Indonesian-locale Excel), tab or pipe separated."""
    try:
        return csv.Sniffer().sniff(sample, delimiters=CSV_DELIMITERS).delimiter
    except csv.Error:
        header = sample.splitlines()[0] if sample else ''
        delimiter = max(CSV_DELIMITERS, key=header.count)
        return delimiter if header.count(delimiter) else ','
