"""
notice_service.py — Manage system alerts and notice board state.
Ensures notices are up to date and deduplicated.
"""
from datetime import datetime, timezone
import logging
from typing import Dict, List

from math import ceil

from sqlalchemy import delete, func, select, update

from app.database import get_db
from app.models import SystemNotice

logger = logging.getLogger("photos_engine.notices")

# Hard cap: the audit log table never keeps more than the newest N rows.
AUDIT_LOG_MAX_ROWS = 50


async def record_notice(
    title: str,
    message: str,
    level: str = "warning",
    source: str = "system",
) -> None:
    """Upsert an active notice by source so we keep latest info without spamming rows."""
    try:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        async with get_db() as db:
            stmt = (
                select(SystemNotice)
                .where(SystemNotice.source == source, SystemNotice.is_active == True)
                .order_by(SystemNotice.id.desc())
                .limit(1)
            )
            res = await db.execute(stmt)
            existing = res.scalar_one_or_none()

            if existing:
                existing.title = title
                existing.message = message
                existing.level = level
                existing.updated_at = now
            else:
                notice = SystemNotice(
                    title=title,
                    message=message,
                    level=level,
                    source=source,
                    is_active=True,
                )
                db.add(notice)
        # Keep the audit table bounded regardless of how many notices stream in.
        await prune_audit_log()
    except Exception as exc:
        logger.error("[notice] Failed to record notice: %s", exc)


async def resolve_notice(source: str) -> None:
    """Deactivate active notices for a given source."""
    try:
        async with get_db() as db:
            stmt = (
                update(SystemNotice)
                .where(SystemNotice.source == source, SystemNotice.is_active == True)
                .values(is_active=False)
            )
            await db.execute(stmt)
    except Exception as exc:
        logger.error("[notice] Failed to resolve notice for %s: %s", source, exc)


async def dismiss_notice(notice_id: int) -> bool:
    """Dismiss a single notice by ID."""
    try:
        async with get_db() as db:
            stmt = (
                update(SystemNotice)
                .where(SystemNotice.id == notice_id)
                .values(is_active=False)
            )
            res = await db.execute(stmt)
            return res.rowcount > 0
    except Exception as exc:
        logger.error("[notice] Failed to dismiss notice %d: %s", notice_id, exc)
        return False


async def clear_all_notices() -> int:
    """Dismiss all active notices."""
    try:
        async with get_db() as db:
            stmt = (
                update(SystemNotice)
                .where(SystemNotice.is_active == True)
                .values(is_active=False)
            )
            res = await db.execute(stmt)
            return res.rowcount
    except Exception as exc:
        logger.error("[notice] Failed to clear notices: %s", exc)
        return 0


async def get_active_notices() -> List[dict]:
    """Return all currently active notices."""
    try:
        async with get_db() as db:
            stmt = (
                select(SystemNotice)
                .where(SystemNotice.is_active == True)
                .order_by(SystemNotice.updated_at.desc(), SystemNotice.id.desc())
            )
            res = await db.execute(stmt)
            rows = res.scalars().all()
            return [
                {
                    "id": r.id,
                    "level": r.level,
                    "title": r.title,
                    "message": r.message,
                    "source": r.source,
                    "created_at": str(r.created_at),
                    "updated_at": str(r.updated_at),
                }
                for r in rows
            ]
    except Exception as exc:
        logger.error("[notice] Failed to fetch active notices: %s", exc)
        return []


async def prune_audit_log(keep: int = AUDIT_LOG_MAX_ROWS) -> None:
    """Delete audit rows outside the newest `keep` entries."""
    try:
        async with get_db() as db:
            newest = (
                select(SystemNotice.id)
                .order_by(SystemNotice.id.desc())
                .limit(keep)
                .scalar_subquery()
            )
            stmt = delete(SystemNotice).where(SystemNotice.id.not_in(newest))
            await db.execute(stmt)
    except Exception as exc:
        logger.error("[notice] Failed to prune audit log: %s", exc)


async def get_notices_paginated(
    page: int = 1,
    page_size: int = AUDIT_LOG_MAX_ROWS,
    status: str = "all",
) -> Dict:
    """Return audit log rows newest-first, paginated. status: all | active."""
    empty = {"notices": [], "total": 0, "page": 1, "page_size": page_size, "total_pages": 1}
    try:
        size = min(max(1, page_size), 100)
        async with get_db() as db:
            base = select(SystemNotice)
            if status == "active":
                base = base.where(SystemNotice.is_active == True)  # noqa: E712
            count_res = await db.execute(select(func.count()).select_from(base.subquery()))
            total = int(count_res.scalar() or 0)
            total_pages = max(1, ceil(total / size))
            current = min(max(1, page), total_pages)
            stmt = (
                base.order_by(SystemNotice.updated_at.desc(), SystemNotice.id.desc())
                .offset((current - 1) * size)
                .limit(size)
            )
            res = await db.execute(stmt)
            rows = res.scalars().all()
            return {
                "notices": [
                    {
                        "id": r.id,
                        "level": r.level,
                        "title": r.title,
                        "message": r.message,
                        "source": r.source,
                        "is_active": r.is_active,
                        "created_at": str(r.created_at),
                        "updated_at": str(r.updated_at),
                    }
                    for r in rows
                ],
                "total": total,
                "page": current,
                "page_size": size,
                "total_pages": total_pages,
            }
    except Exception as exc:
        logger.error("[notice] Failed to fetch paginated notices: %s", exc)
        return empty
