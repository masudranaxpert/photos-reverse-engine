import logging
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import select, update

# Ensure photos_engine can be imported from parent directory
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR / "photos_engine") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "photos_engine"))

from photos_engine import NativeWebClient
from app.database import get_db
from app.models import WebSession

logger = logging.getLogger(__name__)

# 30-second TTL cache for the default active-session lookup.
# Stores (session_object, expire_timestamp); None means no active session.
_session_cache: tuple = (None, 0.0)
_SESSION_TTL = 30  # seconds

# Debounce blob sync: same session written at most once per interval.
_last_blob_sync: dict[str, float] = {}
_BLOB_SYNC_INTERVAL = 60  # seconds


def invalidate_session_cache() -> None:
    """Force next get_active_session_row() to bypass cache."""
    global _session_cache
    _session_cache = (None, 0.0)


async def get_active_session_row(session_id: Optional[str] = None, allow_inactive: bool = False) -> Optional[WebSession]:
    """Fetch session record from SQLite; default path uses a 30s TTL in-memory cache."""
    global _session_cache

    # Specific lookups and inactive-allowed lookups always hit the DB.
    if session_id or allow_inactive:
        async with get_db(write=False) as db:
            stmt = select(WebSession).where(WebSession.session_id == session_id.strip()) if session_id else \
                select(WebSession).where(WebSession.is_active.is_(True)).order_by(WebSession.id.desc()).limit(1)
            if session_id and not allow_inactive:
                stmt = stmt.where(WebSession.is_active.is_(True))
            res = await db.execute(stmt)
            return res.scalar_one_or_none()

    # Default path: latest active session with cache.
    cached_row, expires_at = _session_cache
    if time.monotonic() < expires_at:
        return cached_row

    async with get_db(write=False) as db:
        stmt = select(WebSession).where(WebSession.is_active.is_(True)).order_by(WebSession.id.desc()).limit(1)
        res = await db.execute(stmt)
        row = res.scalar_one_or_none()

    _session_cache = (row, time.monotonic() + _SESSION_TTL)
    return row


async def get_web_client(session_id: Optional[str] = None, allow_inactive: bool = False) -> Tuple[NativeWebClient, str]:
    """
    Restore an active NativeWebClient from the stored session_blob (single source of truth).
    Returns (client, session_id). Raises HTTP 503/404 on failure.
    """
    session_row = await get_active_session_row(session_id, allow_inactive=allow_inactive)
    if not session_row:
        if session_id:
            detail = f"Session '{session_id}' not found" if allow_inactive else f"Session '{session_id}' not found or inactive"
            raise HTTPException(
                status_code=404,
                detail=detail,
            )
        raise HTTPException(
            status_code=503,
            detail="Service is temporarily unavailable. Please try again in a few minutes.",
        )

    target_session_id = session_row.session_id
    blob = session_row.session_blob

    try:
        client = NativeWebClient.from_blob(blob)
        return client, target_session_id
    except Exception as exc:
        err_msg = str(exc)
        logger.error("Failed to restore session '%s' from blob: %s", target_session_id, err_msg)
        if any(k in err_msg.lower() for k in ("302", "login", "expired", "unauthorized")):
            async with get_db() as db:
                await db.execute(
                    update(WebSession)
                    .where(WebSession.session_id == target_session_id)
                    .values(is_active=False)
                )
            invalidate_session_cache()
            from app.services.notice_service import record_notice
            await record_notice(
                title="Instant Session Expired",
                message=f"Instant Session '{target_session_id}' ({session_row.account_email or 'No email'}) cookies have expired. Please export fresh cookies and update them in Cookie Sessions tab.",
                level="error",
                source=f"cookies_{target_session_id}",
            )
            raise HTTPException(
                status_code=503,
                detail="Service is temporarily unavailable. Please try again in a few minutes.",
            )
        raise HTTPException(
            status_code=503,
            detail="Service is temporarily busy. Please try again in a few minutes.",
        )


async def sync_session_blob(session_id: str, client: NativeWebClient, force: bool = False) -> None:
    """Persist rotated cookies & TLS tickets from live client back to the web_sessions table.

    Debounced to once per _BLOB_SYNC_INTERVAL per session_id to avoid 150
    concurrent tasks all writing the same row. Use force=True to bypass.
    """
    now = time.monotonic()
    if not force and now - _last_blob_sync.get(session_id, 0.0) < _BLOB_SYNC_INTERVAL:
        return  # Already synced recently; skip.
    _last_blob_sync[session_id] = now

    try:
        blob = client.export_session_blob()
        if blob and len(blob) > 0:
            async with get_db() as db:
                await db.execute(
                    update(WebSession)
                    .where(WebSession.session_id == session_id)
                    .values(session_blob=blob, is_active=True)
                )
            # Blob-only update — is_active unchanged, no need to invalidate session cache.
            logger.debug("Synced session blob for '%s'.", session_id)
    except Exception as exc:
        logger.warning("Failed to sync session blob for '%s': %s", session_id, exc)
