"""Background jobs dashboard API."""
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.database import get_db
from app.models import BackgroundJob
from app.schemas import JobResponse
from app.security import get_current_admin

router = APIRouter(prefix="/api/jobs", tags=["Background Jobs"])


@router.get("", response_model=List[JobResponse])
async def list_jobs(
    job_type: Optional[str] = Query(None, description="Filter by job type"),
    status: Optional[str] = Query(None, description="Filter by status: pending|running|done|failed"),
    limit: int = Query(50, ge=1, le=200),
    current_admin: dict = Depends(get_current_admin),
):
    """List background jobs for the dashboard, newest first."""
    async with get_db() as db:
        stmt = (
            select(BackgroundJob)
            .where(BackgroundJob.run_every_sec.isnot(None))
            .order_by(BackgroundJob.id.asc())
            .limit(limit)
        )
        if job_type:
            stmt = stmt.where(BackgroundJob.job_type == job_type)
        if status:
            stmt = stmt.where(BackgroundJob.status == status)
        res = await db.execute(stmt)
        jobs = res.scalars().all()

    return [
        JobResponse(
            id=j.id,
            job_type=j.job_type,
            status=j.status,
            payload=j.payload,
            result=j.result,
            run_every_sec=j.run_every_sec,
            next_run_at=str(j.next_run_at) if j.next_run_at else None,
            last_run_at=str(j.last_run_at) if j.last_run_at else None,
            created_at=str(j.created_at),
        )
        for j in jobs
    ]


from datetime import datetime, timedelta, timezone

DEFAULT_JOB_INTERVALS = {
    "pipeline_sweep": 20,
    "cookies_check": 300,
    "cache_cleanup": 1800,
    "daily_cleanup": 86400,
}


class JobUpdateRequest(BaseModel):
    run_every_sec: Optional[int] = None
    run_now: Optional[bool] = False
    trigger_now: Optional[bool] = False
    reset_to_default: Optional[bool] = False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.post("/{job_id}/run-now", response_model=JobResponse)
async def trigger_job_now(
    job_id: int,
    current_admin: dict = Depends(get_current_admin),
):
    """Force a background job to run immediately via APScheduler."""
    async with get_db() as db:
        stmt = select(BackgroundJob).where(BackgroundJob.id == job_id)
        res = await db.execute(stmt)
        job = res.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        job.status = "pending"
        job.next_run_at = _utc_now()
        await db.flush()
        await db.refresh(job)

    # Trigger immediately in APScheduler
    from app.services.scheduler import trigger_job_now as aps_trigger
    aps_trigger(job.job_type)

    return JobResponse(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        payload=job.payload,
        result=job.result,
        run_every_sec=job.run_every_sec,
        next_run_at=str(job.next_run_at) if job.next_run_at else None,
        last_run_at=str(job.last_run_at) if job.last_run_at else None,
        created_at=str(job.created_at),
    )


@router.patch("/{job_id}", response_model=JobResponse)
async def update_job(
    job_id: int,
    req: JobUpdateRequest,
    current_admin: dict = Depends(get_current_admin),
):
    """Update job interval (run_every_sec), reset to default, or trigger immediate execution."""
    async with get_db() as db:
        stmt = select(BackgroundJob).where(BackgroundJob.id == job_id)
        res = await db.execute(stmt)
        job = res.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        now = _utc_now()
        should_run_now = req.run_now or req.trigger_now
        from app.services.scheduler import reschedule_job, trigger_job_now as aps_trigger

        if req.reset_to_default:
            default_sec = DEFAULT_JOB_INTERVALS.get(job.job_type, 300)
            job.run_every_sec = default_sec
            job.status = "pending"
            job.next_run_at = now if should_run_now else (now + timedelta(seconds=default_sec))
            reschedule_job(job.job_type, default_sec)
            if should_run_now:
                aps_trigger(job.job_type)
        elif req.run_every_sec is not None and req.run_every_sec > 0:
            job.run_every_sec = req.run_every_sec
            job.status = "pending"
            if should_run_now:
                job.next_run_at = now
                aps_trigger(job.job_type)
            else:
                job.next_run_at = now + timedelta(seconds=req.run_every_sec)
            reschedule_job(job.job_type, req.run_every_sec)
        elif should_run_now:
            job.status = "pending"
            job.next_run_at = now
            aps_trigger(job.job_type)

        await db.flush()
        await db.refresh(job)

    return JobResponse(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        payload=job.payload,
        result=job.result,
        run_every_sec=job.run_every_sec,
        next_run_at=str(job.next_run_at) if job.next_run_at else None,
        last_run_at=str(job.last_run_at) if job.last_run_at else None,
        created_at=str(job.created_at),
    )
