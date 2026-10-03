"""Cron job definitions. Add new jobs here with the @cron_job decorator."""
from app.common.logger import get_logger
from app.cron.scheduler import cron_job

logger = get_logger(__name__)


@cron_job("* * * * *")
def heartbeat():
    """Example job: runs every minute. Replace or remove as needed."""
    logger.info("Cron heartbeat")
