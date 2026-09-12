"""
app/services/scheduler.py - Unified APScheduler service for background jobs.
Replaces manual worker loop with production-grade AsyncIOScheduler.
"""

import json
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import delete, select, update

from app.database import get_db, utc_now_naive
from app.logging_config import logger
from app.models import BackgroundJob

# Default intervals in seconds
DEFAULT_JOB_INTERVALS: Dict[str, int] = {
    "pipeline_sweep": 30,    # Share link generation & promotion sweep (30s)
    "cookies_check": 300,    # Active session cookies validation (5 min)
    "cache_cleanup": 1800,   # Expired download cache cleanup (30 min)
    "daily_cleanup": 86400,  # 24-hour sweep of orphaned temp items
    "stream_cache_cleanup": 60,  # 20-min stream cache expiry cleanup (every 1 min)
}

# Global AsyncIOScheduler instance
scheduler = AsyncIOScheduler(timezone=timezone.utc)


async def _run_managed_job(
    job_type: str,
    task_func: Callable[[], Coroutine[Any, Any, Optional[Dict[str, Any]]]],
) -> None:
    """
    Wrapper around scheduled tasks.
    Updates DB status to 'running', executes the coroutine, then records 'done' or 'failed'.
    """
    now = utc_now_naive()
    async with get_db() as db:
        await db.execute(
            update(BackgroundJob)
            .where(BackgroundJob.job_type == job_type)
            .values(status="running", last_run_at=now)
        )

    try:
        result = await task_func()
        result_json = json.dumps(result or {})

        # Determine next run time from APScheduler
        aps_job = scheduler.get_job(job_type)
        next_run = aps_job.next_run_time.replace(tzinfo=None) if (aps_job and aps_job.next_run_time) else None

        async with get_db() as db:
            await db.execute(
                update(BackgroundJob)
                .where(BackgroundJob.job_type == job_type)
                .values(
                    status="pending",
                    result=result_json,
                    last_run_at=utc_now_naive(),
                    next_run_at=next_run,
                )
            )
    except Exception as exc:
        logger.exception("[scheduler] Job '{}' failed: {}", job_type, exc)
        err_json = json.dumps({"error": str(exc)})
        async with get_db() as db:
            await db.execute(
                update(BackgroundJob)
                .where(BackgroundJob.job_type == job_type)
                .values(status="failed", result=err_json, last_run_at=utc_now_naive())
            )


# ────────────────────────── Scheduled Job Runners ──────────────────────────

from app.services.background_worker import (
    run_cache_cleanup_logic,
    run_cookies_check_logic,
    run_daily_cleanup_logic,
    run_pipeline_sweep_logic,
    run_stream_cache_cleanup_logic,
)

JOB_TASK_MAP = {
    "pipeline_sweep": run_pipeline_sweep_logic,
    "cookies_check": run_cookies_check_logic,
    "cache_cleanup": run_cache_cleanup_logic,
    "daily_cleanup": run_daily_cleanup_logic,
    "stream_cache_cleanup": run_stream_cache_cleanup_logic,
}


# ────────────────────────── Lifecycle Management ──────────────────────────


async def ensure_jobs_in_db() -> Dict[str, int]:
    """Ensure all recurring job definitions exist in SQLite with configured intervals."""
    intervals = {}
    async with get_db() as db:
        # Clean up any legacy retired one-off jobs
        await db.execute(
            delete(BackgroundJob).where(
                BackgroundJob.job_type.in_(["quota_check", "share_link", "promote", "cleanup"])
            )
        )

        for job_type, default_sec in DEFAULT_JOB_INTERVALS.items():
            stmt = select(BackgroundJob).where(BackgroundJob.job_type == job_type).limit(1)
            res = await db.execute(stmt)
            existing = res.scalar_one_or_none()

            if existing is None:
                job = BackgroundJob(
                    job_type=job_type,
                    status="pending",
                    run_every_sec=default_sec,
                    next_run_at=utc_now_naive(),
                )
                db.add(job)
                intervals[job_type] = default_sec
            else:
                sec = default_sec if (existing.run_every_sec == 20 and job_type == "pipeline_sweep") else (existing.run_every_sec or default_sec)
                existing.run_every_sec = sec
                existing.status = "pending"
                intervals[job_type] = sec

    return intervals


async def start_scheduler() -> None:
    """Initialize jobs and start APScheduler within the running event loop."""
    logger.info("[scheduler] Initializing APScheduler...")
    intervals = await ensure_jobs_in_db()

    for job_type, task_func in JOB_TASK_MAP.items():
        interval_sec = intervals.get(job_type, DEFAULT_JOB_INTERVALS.get(job_type, 60))
        scheduler.add_job(
            _run_managed_job,
            trigger=IntervalTrigger(seconds=interval_sec),
            args=[job_type, task_func],
            id=job_type,
            name=job_type,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("[scheduler] Registered job '{}' (interval: {}s)", job_type, interval_sec)

    scheduler.start()
    logger.info("[scheduler] APScheduler successfully started with {} jobs.", len(JOB_TASK_MAP))


async def stop_scheduler() -> None:
    """Gracefully shutdown APScheduler."""
    if scheduler.running:
        logger.info("[scheduler] Shutting down APScheduler...")
        scheduler.shutdown(wait=False)
        logger.info("[scheduler] APScheduler shut down.")


def trigger_job_now(job_type: str) -> bool:
    """Trigger an immediate execution of a scheduled job."""
    job = scheduler.get_job(job_type)
    if job:
        job.modify(next_run_time=datetime.now(timezone.utc))
        logger.info("[scheduler] Job '{}' triggered for immediate execution.", job_type)
        return True
    logger.warning("[scheduler] Cannot trigger unknown job '{}'", job_type)
    return False


def reschedule_job(job_type: str, interval_sec: int) -> bool:
    """Update execution interval for a scheduled job dynamically."""
    if interval_sec <= 0:
        return False
    job = scheduler.get_job(job_type)
    if job:
        scheduler.reschedule_job(job_type, trigger=IntervalTrigger(seconds=interval_sec))
        logger.info("[scheduler] Job '{}' rescheduled to every {}s.", job_type, interval_sec)
        return True
    return False
