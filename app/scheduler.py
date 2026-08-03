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


DEFAULT_CRON = "0 6 * * *"


def _cron_parts(cron_expr: str) -> dict:
    """Parse a 5-field cron expression into CronTrigger kwargs."""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: {cron_expr!r} (expected 5 fields)")
    keys = ("minute", "hour", "day", "month", "day_of_week")
    return dict(zip(keys, parts))


def build_trigger(cron_expr: str) -> CronTrigger:
    """Validate a cron expression and build its trigger. Raises ValueError."""
    try:
        return CronTrigger(**_cron_parts(cron_expr))
    except ValueError:
        raise
    except Exception as exc:  # APScheduler raises assorted types for bad fields
        raise ValueError(f"Invalid cron expression: {cron_expr!r} — {exc}") from exc


def start_scheduler(cron_expr: str) -> None:
    """Start the scheduler, falling back to the default cron if `cron_expr` is bad.

    A bad cron used to abort the whole function before `scheduler.start()`, so
    the app ran with no scheduled briefs at all and only a log line to say so.
    """
    try:
        trigger = build_trigger(cron_expr)
    except ValueError as exc:
        logger.error("%s — falling back to default cron %s", exc, DEFAULT_CRON)
        trigger = build_trigger(DEFAULT_CRON)
        cron_expr = DEFAULT_CRON

    try:
        scheduler.add_job(
            _run_brief,
            trigger,
            id=JOB_ID,
            replace_existing=True,
            misfire_grace_time=3600,
        )
        if not scheduler.running:
            scheduler.start()
        logger.info("Scheduler started with cron: %s", cron_expr)
    except Exception as exc:
        logger.error("Failed to start scheduler: %s", exc)


def reschedule_brief(cron_expr: str) -> None:
    """Apply a new cron to the brief job. Raises ValueError on a bad expression."""
    trigger = build_trigger(cron_expr)  # validate before touching the scheduler
    try:
        scheduler.reschedule_job(JOB_ID, trigger=trigger)
    except Exception:
        # Job missing (scheduler never started cleanly) — (re)create it.
        scheduler.add_job(
            _run_brief, trigger, id=JOB_ID, replace_existing=True, misfire_grace_time=3600
        )
    logger.info("Brief rescheduled to cron: %s", cron_expr)


def scheduler_status() -> dict:
    """Introspection for the settings endpoint."""
    job = scheduler.get_job(JOB_ID) if scheduler.running else None
    return {
        "running": scheduler.running,
        "next_run": job.next_run_time.isoformat() if job and job.next_run_time else None,
    }


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
