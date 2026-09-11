"""Quota-aware cleanup: checks storage thresholds and purges oldest temp imports."""
import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Optional

from sqlalchemy import select

from app.database import get_db
from app.models import DriveRef, TempImport, WebSession

logger = logging.getLogger(__name__)

GB = 1024 ** 3
TB = 1024 ** 4

# Trigger cleanup when used_bytes >= used_threshold AND total_bytes <= total_threshold.
# bytes_to_free: how much to clear (must exceed the new upload to guarantee space).
QUOTA_THRESHOLDS = [
    (13 * GB, 17 * GB, 2 * GB),     # ~13 GB used of 15 GB (standard free tier) → free 2 GB
    (95 * GB, 110 * GB, 5 * GB),    # ~95 GB used of 100 GB → free 5 GB
    (900 * GB, 1100 * GB, 50 * GB), # ~900 GB of 1 TB
    (1 * TB, 5 * TB, 500 * GB),
]


async def check_and_clean_quota(web_client, session_id: str) -> Optional[int]:
    """
    Fetch current quota; if a threshold is breached, delete oldest temp imports
    from Google Photos until enough space is freed.
    Returns bytes freed, or None if quota is fine.
    """
    try:
        if hasattr(web_client, "get_storage_quota_async"):
            quota = await web_client.get_storage_quota_async()
        else:
            quota = web_client.get_storage_quota()
    except Exception as exc:
        logger.warning("[quota] Failed to fetch quota for %s: %s", session_id, exc)
        return None

    used = quota.used_bytes
    total = quota.total_bytes

    target_free: Optional[int] = None
    for used_thresh, total_thresh, to_free in QUOTA_THRESHOLDS:
        if used >= used_thresh and total <= total_thresh:
            target_free = to_free
            break

    if target_free is None:
        return None  # quota is fine

    logger.warning(
        "[quota] Threshold breached: used=%d total=%d → freeing %d bytes from temp",
        used, total, target_free,
    )

    freed = await _delete_oldest_temp(web_client, target_free)
    logger.info("[quota] Freed ~%d bytes by deleting %d temp items", freed, freed)
    return freed


async def free_space_from_temp(target_bytes: int, web_client) -> int:
    """
    Delete oldest TempImport rows (by imported_at ASC) until target_bytes freed.
    Uses actual file_size if available, falling back to 100MB estimate.
    """
    return await _delete_oldest_temp(web_client, target_bytes)


def _is_cookie_expired_error(exc: Exception) -> bool:
    """Detect if exception is caused by expired session cookies or authentication redirect."""
    msg = str(exc).lower()
    return any(k in msg for k in ("302", "login", "expired", "unauthorized", "redirected to login", "session is expired", "cookies are expired", "cookies are invalid"))


async def _delete_oldest_temp(web_client, target_bytes: int) -> int:
    """
    Delete oldest TempImport rows (by imported_at ASC) until target_bytes freed:
    1. Verifies that active WebSession cookies exist; aborts immediately if cookies are inactive/expired.
    2. Retries deletion from Google Photos up to 3 times per item.
    3. If deletion fails after 3 retries (non-cookie error), logs warning and still purges DB row.
    4. If cookies expire midway, halts the entire delete process immediately.
    """
    # Verify active web session before starting
    async with get_db(write=False) as db:
        active_sess = (await db.execute(
            select(WebSession).where(WebSession.is_active.is_(True)).limit(1)
        )).scalar_one_or_none()
    if not active_sess:
        logger.warning("[quota] Web session is inactive or cookies are expired. Halting delete process until new cookies are provided.")
        return 0

    freed = 0
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    async with get_db(write=False) as db:
        stmt = (
            select(TempImport, DriveRef.file_size)
            .outerjoin(DriveRef, TempImport.drive_ref_id == DriveRef.id)
            .where(
                TempImport.dedup_key.isnot(None),
                TempImport.imported_at <= cutoff,
            )
            .order_by(TempImport.imported_at.asc())
            .limit(500)
        )
        res = await db.execute(stmt)
        candidates = res.all()

    DEFAULT_AVG_BYTES = 100 * 1024 * 1024  # 100 MB fallback

    deleted_ids = []
    for item, ref_size in candidates:
        if freed >= target_bytes:
            break

        delete_success = False
        cookie_expired = False
        last_err = None

        # Retry up to 3 times
        for attempt in range(1, 4):
            try:
                if hasattr(web_client, "delete_permanently_async"):
                    res = await web_client.delete_permanently_async(item.dedup_key)
                elif hasattr(web_client, "delete_permanently"):
                    res = web_client.delete_permanently(item.dedup_key)
                elif hasattr(web_client, "delete_by_dedup_key"):
                    res = web_client.delete_by_dedup_key(item.dedup_key)
                else:
                    res = True
                delete_success = bool(res)
                break
            except Exception as exc:
                last_err = exc
                if _is_cookie_expired_error(exc):
                    cookie_expired = True
                    break
                if attempt < 3:
                    await asyncio.sleep(0.5)

        # Halt delete process completely if cookies are expired
        if cookie_expired:
            logger.error(
                "[quota] Cookies expired/unauthorized while deleting temp item %s: %s. Halting delete process until new cookies are provided.",
                item.media_key, last_err,
            )
            from sqlalchemy import update as sa_update
            async with get_db() as db:
                await db.execute(
                    sa_update(WebSession)
                    .where(WebSession.session_id == active_sess.session_id)
                    .values(is_active=False)
                )
            break

        item_size = ref_size or DEFAULT_AVG_BYTES
        if delete_success:
            freed += item_size
            deleted_ids.append(item.id)
            logger.info(
                "[quota] Evicted temp media_key=%s (share_url=%s) size=%s from Google Photos and DB",
                item.media_key, bool(item.share_url), item_size,
            )
        else:
            logger.warning(
                "[quota] Could not delete temp item %s from Google Photos after 3 retries (%s). Purging from DB to prevent deadlock.",
                item.media_key, last_err,
            )
            deleted_ids.append(item.id)

    if deleted_ids:
        from sqlalchemy import delete as sa_delete
        async with get_db() as db:
            await db.execute(
                sa_delete(TempImport).where(TempImport.id.in_(deleted_ids))
            )
        logger.info("[quota] Purged %d temp_import rows from DB (freed ~%d bytes)", len(deleted_ids), freed)

    return freed
