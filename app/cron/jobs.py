"""Cron job definitions. Add new jobs here with the @cron_job decorator."""
from datetime import datetime

from app.common.helpers import jakarta_today
from app.common.logger import get_logger
from app.common.period_generator import generate_periods
from app.cron.scheduler import cron_job
from app.extensions import db
from app.models.custom_period import CustomPeriod

logger = get_logger(__name__)


@cron_job("* * * * *")
def heartbeat():
    """Example job: runs every minute. Replace or remove as needed."""
    logger.info("Cron heartbeat")


def _to_date(value: int):
    """YYYYMMDD int (as returned by generate_periods) -> date."""
    return datetime.strptime(str(value), "%Y%m%d").date()


@cron_job("0 0 * * *")
def ensure_current_year_periods():
    """Daily at midnight (Jakarta): generate the current year's periods if missing."""
    year = jakarta_today().year

    if CustomPeriod.query.filter_by(year=year).first():
        logger.info("Custom periods for %s already exist, skipping", year)
        return

    for p in generate_periods(year):
        db.session.add(CustomPeriod(
            period_key=year * 100 + p["period"],  # e.g. 202601
            year=year,
            period=f"P{p['period']:02d}",          # e.g. "P01"
            period_start=_to_date(p["start_date"]),
            period_end=_to_date(p["end_date"]),
        ))
    db.session.commit()
    logger.info("Generated custom periods for %s", year)
