import uuid

from datetime import date, datetime
from zoneinfo import ZoneInfo

from flask import jsonify

def success_response(data=None, message="Success", meta=None, code=200):
    body = {"success": True, "message": message, "data": data}
    if meta is not None:
        body["meta"] = meta
    return jsonify(body), code


def error_response(message="Something went wrong", code=400, errors=None):
    body = {"success": False, "message": message}
    if errors is not None:
        body["errors"] = errors
    return jsonify(body), code

def gen_uuid() -> str:
    return str(uuid.uuid4())

# All business data (order files, stored timestamps, API output) is in Jakarta
# time, independent of the server's own timezone.
APP_TIMEZONE = "Asia/Jakarta"
APP_TZ = ZoneInfo(APP_TIMEZONE)


def jakarta_now() -> datetime:
    """Current time as a timezone-aware Jakarta datetime."""
    return datetime.now(APP_TZ)


def jakarta_today() -> date:
    """Today's date in Jakarta (not the server's local date)."""
    return jakarta_now().date()


def to_jakarta(value: datetime) -> datetime:
    """Return `value` as an aware Jakarta datetime.

    Naive values are assumed to already be Jakarta wall time (as in the order
    Excel files and in SQLite, which drops tz info) and get the zone attached;
    aware values are converted.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=APP_TZ)
    return value.astimezone(APP_TZ)
