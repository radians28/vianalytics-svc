import asyncio
import functools
from zoneinfo import ZoneInfo

import aiocron

from app.common.logger import get_logger

logger = get_logger(__name__)

# (spec, func) pairs collected by @cron_job; started by start_jobs()
_registry = []


def cron_job(spec):
    """Register a function to run on a cron schedule, e.g. @cron_job("*/5 * * * *").

    Both sync and async functions are supported. Sync functions run in a worker
    thread so they don't block the event loop. Every run gets a Flask app context,
    so models / db.session can be used as usual.
    """
    def decorator(func):
        _registry.append((spec, func))
        return func
    return decorator


def _wrap(app, func):
    name = func.__qualname__

    def run_sync():
        with app.app_context():
            return func()

    @functools.wraps(func)
    async def runner():
        logger.info("Cron job '%s' started", name)
        try:
            if asyncio.iscoroutinefunction(func):
                with app.app_context():
                    await func()
            else:
                await asyncio.to_thread(run_sync)
            logger.info("Cron job '%s' finished", name)
        except Exception:
            # Swallow so one failing run doesn't stop future runs.
            logger.exception("Cron job '%s' failed", name)

    return runner


def start_jobs(app, loop=None):
    """Start all registered jobs on the given (or current) event loop."""
    # Import job modules so their @cron_job decorators register.
    from app.cron import jobs  # noqa: F401

    tz_name = app.config.get("CRON_TIMEZONE")
    tz = ZoneInfo(tz_name) if tz_name else None
    crons = []
    for spec, func in _registry:
        crons.append(aiocron.crontab(spec, func=_wrap(app, func), start=True, loop=loop, tz=tz))
        logger.info("Registered cron job '%s' with schedule '%s'", func.__qualname__, spec)
    return crons

