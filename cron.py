"""Run scheduled background jobs (aiocron) in a standalone process.

Kept separate from the API server so jobs run exactly once, regardless of how
many web workers are serving the API.

Usage:
    ./.venv/bin/python cron.py
"""
import asyncio

from app import create_app
from app.common.logger import get_logger
from app.cron import start_jobs

logger = get_logger("cron")


async def main():
    app = create_app()
    start_jobs(app)
    logger.info("Cron worker started")
    await asyncio.Event().wait()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Cron worker stopped")
