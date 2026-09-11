import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, select

from app.config import DOWNLOAD_CACHE_TTL_SECONDS
from app.database import get_db
from app.models import DownloadCache

logger = logging.getLogger(__name__)

# Fast in-memory cache: media_key -> (data_dict, monotonic_expiry)
_url_mem_cache: dict[str, tuple[dict, float]] = {}


def _utc_now_naive() -> datetime:
    """Return naive UTC datetime compatible with SQLite DateTime comparison."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def get_cached_url(media_key: str) -> Optional[dict]:
    """Retrieve non-expired download URL with memory L1 check and SQLite WAL fallback."""
    now_mono = time.monotonic()
    mem_entry = _url_mem_cache.get(media_key)
    if mem_entry:
        data, exp = mem_entry
        if now_mono < exp:
            return data
        _url_mem_cache.pop(media_key, None)

    now = _utc_now_naive()
    async with get_db(write=False) as db:
        stmt = select(DownloadCache).where(
            DownloadCache.media_key == media_key,
            DownloadCache.expires_at > now,
        )
        result = await db.execute(stmt)
        item = result.scalar_one_or_none()
        if item:
            data = {
                "download_url": item.download_url,
                "dedup_key": item.dedup_key,
                "source": item.source,
            }
            # Cache remaining TTL in memory (cap at 1800s)
            rem_sec = max(1.0, (item.expires_at - now).total_seconds())
            _url_mem_cache[media_key] = (data, now_mono + min(rem_sec, DOWNLOAD_CACHE_TTL_SECONDS))
            return data
    return None


async def set_cached_url(
    media_key: str,
    download_url: str,
    dedup_key: Optional[str] = None,
    source: str = "web",
    ttl_seconds: int = DOWNLOAD_CACHE_TTL_SECONDS,
) -> None:
    """Store direct download URL in memory and SQLite WAL cache with TTL."""
    if not media_key or not download_url:
        return

    data = {
        "download_url": download_url,
        "dedup_key": dedup_key,
        "source": source,
    }
    # Limit memory cache to avoid unbounded growth
    if len(_url_mem_cache) > 5000:
        _url_mem_cache.clear()
    _url_mem_cache[media_key] = (data, time.monotonic() + ttl_seconds)

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
    now_mono = time.monotonic()
    expired_keys = [k for k, (_, exp) in _url_mem_cache.items() if now_mono >= exp]
    for k in expired_keys:
        _url_mem_cache.pop(k, None)

    now = _utc_now_naive()
    async with get_db() as db:
        stmt = delete(DownloadCache).where(DownloadCache.expires_at <= now)
        res = await db.execute(stmt)
        deleted = res.rowcount
    if deleted > 0:
        logger.info("[cache cleanup] Removed %d expired entries", deleted)
    return deleted
