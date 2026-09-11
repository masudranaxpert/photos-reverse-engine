import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, select

from app.config import DOWNLOAD_CACHE_TTL_SECONDS
from app.database import get_db
from app.models import DownloadCache

logger = logging.getLogger(__name__)


def _utc_now_naive() -> datetime:
    """Return naive UTC datetime compatible with SQLite DateTime comparison."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def get_cached_url(media_key: str) -> Optional[dict]:
    """Retrieve non-expired download URL for media_key from SQLite WAL cache."""
    now = _utc_now_naive()
    async with get_db() as db:
        stmt = select(DownloadCache).where(
            DownloadCache.media_key == media_key,
            DownloadCache.expires_at > now,
        )
        result = await db.execute(stmt)
        item = result.scalar_one_or_none()
        if item:
            return {
                "download_url": item.download_url,
                "dedup_key": item.dedup_key,
                "source": item.source,
            }
    return None


async def set_cached_url(
    media_key: str,
    download_url: str,
    dedup_key: Optional[str] = None,
    source: str = "web",
    ttl_seconds: int = DOWNLOAD_CACHE_TTL_SECONDS,
) -> None:
    """Store direct download URL in SQLite WAL cache with 30-minute expiration."""
    if not media_key or not download_url:
        return

    expires_at = _utc_now_naive() + timedelta(seconds=ttl_seconds)
    async with get_db() as db:
        cache_entry = DownloadCache(
            media_key=media_key,
            download_url=download_url,
            dedup_key=dedup_key,
            source=source,
            expires_at=expires_at,
        )
        await db.merge(cache_entry)
    logger.debug("[cache set] media_key=%s ttl=%ss", media_key, ttl_seconds)


async def cleanup_expired_cache() -> int:
    """Delete expired entries from download_cache using SQLAlchemy delete."""
    now = _utc_now_naive()
    async with get_db() as db:
        stmt = delete(DownloadCache).where(DownloadCache.expires_at <= now)
        res = await db.execute(stmt)
        deleted = res.rowcount
    if deleted > 0:
        logger.info("[cache cleanup] Removed %d expired entries", deleted)
    return deleted
