"""APScheduler setup for automated morning brief generation."""
from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="UTC")
JOB_ID = "morning_brief"


async def _run_brief() -> None:
    from app.services.brief import generate_brief
    logger.info("Scheduler: generating morning brief...")
    try:
        result = await generate_brief(web_search=True)
        logger.info("Scheduler: brief saved to %s", result["path"])
    except Exception as exc:
        logger.error("Scheduler: brief generation failed — %s", exc)


def _cron_parts(cron_expr: str) -> dict:
    """Parse a 5-field cron expression into CronTrigger kwargs."""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: {cron_expr!r}")
    keys = ("minute", "hour", "day", "month", "day_of_week")
    return dict(zip(keys, parts))


def start_scheduler(cron_expr: str) -> None:
    try:
        kwargs = _cron_parts(cron_expr)
        scheduler.add_job(
            _run_brief,
            CronTrigger(**kwargs),
            id=JOB_ID,
            replace_existing=True,
            misfire_grace_time=3600,
        )
        scheduler.start()
        logger.info("Scheduler started with cron: %s", cron_expr)
    except Exception as exc:
        logger.error("Failed to start scheduler: %s", exc)


def reschedule_brief(cron_expr: str) -> None:
    try:
        kwargs = _cron_parts(cron_expr)
        scheduler.reschedule_job(JOB_ID, trigger=CronTrigger(**kwargs))
        logger.info("Brief rescheduled to cron: %s", cron_expr)
    except Exception as exc:
        logger.error("Failed to reschedule: %s", exc)


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
