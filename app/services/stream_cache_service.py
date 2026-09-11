import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, func, select

from app.config import STREAM_CACHE_TTL_SECONDS
from app.database import get_db
from app.models import StreamCache

logger = logging.getLogger(__name__)


def _utc_now_naive() -> datetime:
    """Return naive UTC datetime compatible with SQLite DateTime comparison."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def get_cached_stream(media_key: str) -> Optional[Dict[str, Any]]:
    """Retrieve non-expired parsed stream and manifest data for media_key."""
    now = _utc_now_naive()
    async with get_db(write=False) as db:
        stmt = select(StreamCache).where(
            StreamCache.media_key == media_key,
            StreamCache.expires_at > now,
        )
        result = await db.execute(stmt)
        item = result.scalar_one_or_none()
        if not item:
            return None

        try:
            videos = json.loads(item.video_streams)
        except Exception:
            videos = []

        try:
            audios = json.loads(item.audio_streams) if item.audio_streams else []
        except Exception:
            audios = []

        return {
            "id": item.id,
            "media_key": item.media_key,
            "drive_ref_id": item.drive_ref_id,
            "videos": videos,
            "audios": audios,
            "created_at": item.created_at,
            "expires_at": item.expires_at,
        }


async def is_stream_cached(media_key: str) -> bool:
    """Quickly check if an unexpired stream cache entry exists for media_key."""
    now = _utc_now_naive()
    async with get_db(write=False) as db:
        stmt = select(func.count(StreamCache.id)).where(
            StreamCache.media_key == media_key,
            StreamCache.expires_at > now,
        )
        count = (await db.execute(stmt)).scalar() or 0
        return count > 0


async def set_cached_stream(
    media_key: str,
    drive_ref_id: Optional[int] = None,
    video_streams: Optional[List[Dict[str, Any]]] = None,
    audio_streams: Optional[List[Dict[str, Any]]] = None,
    ttl_seconds: int = STREAM_CACHE_TTL_SECONDS,
) -> None:
    """Store or update parsed streaming tracks in SQLite with 20-minute validity."""
    if not media_key or not video_streams:
        return

    now = _utc_now_naive()
    expires_at = now + timedelta(seconds=ttl_seconds)
    video_json = json.dumps(video_streams)
    audio_json = json.dumps(audio_streams) if audio_streams else None

    async with get_db() as db:
        stmt = select(StreamCache).where(StreamCache.media_key == media_key)
        res = await db.execute(stmt)
        entry = res.scalar_one_or_none()

        if entry:
            entry.drive_ref_id = drive_ref_id or entry.drive_ref_id
            entry.video_streams = video_json
            entry.audio_streams = audio_json
            entry.expires_at = expires_at
        else:
            entry = StreamCache(
                media_key=media_key,
                drive_ref_id=drive_ref_id,
                video_streams=video_json,
                audio_streams=audio_json,
                created_at=now,
                expires_at=expires_at,
            )
            db.add(entry)

    logger.debug("[stream cache set] media_key=%s ttl=%ss", media_key, ttl_seconds)


async def cleanup_expired_stream_cache() -> int:
    """Delete expired entries from stream_cache table."""
    now = _utc_now_naive()
    async with get_db() as db:
        stmt = delete(StreamCache).where(StreamCache.expires_at <= now)
        res = await db.execute(stmt)
        deleted = res.rowcount
    if deleted > 0:
        logger.info("[stream cache cleanup] Removed %d expired entries", deleted)
    return deleted


_active_stream_fetches: set[str] = set()


async def fetch_and_cache_stream(
    media_key: str,
    drive_ref_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Fetch DASH streaming manifest in background, parse representations, and cache for 20 minutes."""
    if media_key in _active_stream_fetches:
        return None
    _active_stream_fetches.add(media_key)
    try:
        from app.services.streaming_service import get_streaming_data_for_media_key

        stream_data = await get_streaming_data_for_media_key(media_key)
        if stream_data and stream_data.get("videos"):
            await set_cached_stream(
                media_key=media_key,
                drive_ref_id=drive_ref_id,
                video_streams=stream_data["videos"],
                audio_streams=stream_data.get("audios"),
            )
            logger.info("[stream cache] Successfully cached stream for media_key=%s", media_key)
            return stream_data
    except Exception as exc:
        logger.warning("[stream cache] Failed background stream fetch for %s: %s", media_key, exc)
    finally:
        _active_stream_fetches.discard(media_key)
    return None
