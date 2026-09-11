import logging
import sys
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


async def get_active_session_row(session_id: Optional[str] = None) -> Optional[WebSession]:
    """Fetch active session record from SQLite web_sessions table via SQLAlchemy ORM."""
    async with get_db() as db:
        if session_id:
            stmt = select(WebSession).where(
                WebSession.session_id == session_id.strip(),
                WebSession.is_active.is_(True),
            )
            res = await db.execute(stmt)
            return res.scalar_one_or_none()

        stmt = select(WebSession).where(WebSession.is_active.is_(True)).order_by(WebSession.id.desc()).limit(1)
        res = await db.execute(stmt)
        return res.scalar_one_or_none()


async def get_web_client(session_id: Optional[str] = None) -> Tuple[NativeWebClient, str]:
    """
    Instantiate an active NativeWebClient from stored session blob or raw cookies.
    Returns (client, session_id).
    """
    session_row = await get_active_session_row(session_id)
    if not session_row:
        if session_id:
            # A specific session was requested but doesn't exist / is inactive → 404
            raise HTTPException(
                status_code=404,
                detail=f"Session '{session_id}' not found or inactive",
            )
        # No session requested and none active → service genuinely unavailable
        raise HTTPException(
            status_code=503,
            detail="Service is temporarily unavailable. Please try again in a few minutes.",
        )

    target_session_id = session_row.session_id
    blob = session_row.session_blob

    # Prefer restoring full live session from binary blob
    if blob and len(blob) > 0:
        try:
            client = NativeWebClient.from_blob(blob)
            return client, target_session_id
        except Exception as exc:
            logger.warning(
                "Failed to restore session from blob for '%s': %s. Re-initializing from raw cookies.",
                target_session_id,
                exc,
            )

    # Fallback to initializing from raw cookies string
    raw_cookies = session_row.raw_cookies or ""
    if not raw_cookies.strip():
        raise HTTPException(
            status_code=400,
            detail=f"Session '{target_session_id}' has neither valid blob nor raw cookies.",
        )

    try:
        client = NativeWebClient(cookies=raw_cookies)
    except Exception as exc:
        err_msg = str(exc)
        logger.error("Failed to initialize NativeWebClient for session '%s': %s", target_session_id, err_msg)
        if any(k in err_msg.lower() for k in ("302", "login", "expired", "unauthorized")):
            async with get_db() as db:
                await db.execute(
                    update(WebSession)
                    .where(WebSession.session_id == target_session_id)
                    .values(is_active=False)
                )
            from app.services.notice_service import record_notice
            await record_notice(
                title="Instant Session Expired",
                message=f"Instant Session '{target_session_id}' ({session_row.account_email or 'No email'}) cookies have expired or redirected to login (HTTP 302). Please export fresh cookies and update them in Cookie Sessions tab.",
                level="error",
                source=f"cookies_{target_session_id}",
            )
        raise HTTPException(
            status_code=503,
            detail="Service is temporarily busy. Please try again in a few minutes.",
        )

    # Persist the newly established session blob back to database
    await sync_session_blob(target_session_id, client)
    return client, target_session_id


async def sync_session_blob(session_id: str, client: NativeWebClient) -> None:
    """Save rotated cookies & TLS tickets from live client back to SQLite web_sessions table."""
    try:
        blob = client.export_session_blob()
        if blob and len(blob) > 0:
            async with get_db() as db:
                stmt = (
                    update(WebSession)
                    .where(WebSession.session_id == session_id)
                    .values(session_blob=blob)
                )
                await db.execute(stmt)
            logger.debug("Successfully synced session blob for '%s' to database.", session_id)
    except Exception as exc:
        logger.warning("Failed to sync session blob for '%s': %s", session_id, exc)
