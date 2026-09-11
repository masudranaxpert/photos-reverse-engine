import asyncio
import json
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select, update

from app.database import get_db
from app.models import WebSession
from app.schemas import (
    AccountResetRequest,
    AccountResetResponse,
    WebSessionCreate,
    WebSessionDetailResponse,
    WebSessionResponse,
    WebSessionStatusResponse,
    WebSessionUpdate,
)
from app.security import get_current_admin
from app.services.web_service import get_web_client, sync_session_blob
from photos_engine import NativeWebClient

router = APIRouter(prefix="/api/web", tags=["Web Client & Cookie Sessions"])


# ── Session Management (CRUD) ──────────────────────────────────────────────────

@router.get("/sessions", response_model=List[WebSessionResponse])
async def list_web_sessions(current_admin: dict = Depends(get_current_admin)):
    """List all stored Google Photos web cookie sessions."""
    async with get_db() as db:
        stmt = select(WebSession).order_by(WebSession.id.desc())
        res = await db.execute(stmt)
        sessions = res.scalars().all()

    return [
        WebSessionResponse(
            id=s.id,
            session_id=s.session_id,
            name=s.name,
            account_email=s.account_email,
            is_active=s.is_active,
            has_blob=bool(s.session_blob and len(s.session_blob) > 0),
            created_at=str(s.created_at),
            updated_at=str(s.updated_at),
        )
        for s in sessions
    ]


@router.post("/sessions", response_model=WebSessionResponse)
async def create_web_session(
    req: WebSessionCreate,
    current_admin: dict = Depends(get_current_admin),
):
    """Replace the active web session. Only one session exists at any time."""
    raw_cookies = req.cookies.strip()
    if not raw_cookies:
        raise HTTPException(status_code=400, detail="Cookies cannot be empty")

    status = await NativeWebClient.check_status_async(raw_cookies)
    if not status.valid:
        raise HTTPException(status_code=400, detail=f"Cookie validation failed: {status.message}")

    account_email = status.account or ""

    client = None
    try:
        client = NativeWebClient(cookies=raw_cookies)
        session_blob = client.export_session_blob()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to initialize web client session: {exc}")
    finally:
        if client:
            client.close()

    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    sess_obj = WebSession(
        session_id=session_id,
        name=req.name.strip(),
        account_email=account_email,
        raw_cookies=raw_cookies,
        session_blob=session_blob,
        is_active=True,
    )

    async with get_db() as db:
        # Single-session system: wipe all existing sessions before inserting the new one
        await db.execute(delete(WebSession))
        db.add(sess_obj)
        await db.flush()
        await db.refresh(sess_obj)

    # Automatically trigger worker to resume any pending temporary files and deferred imports
    try:
        from app.services.background_worker import (
            enqueue_promote_job,
            enqueue_share_link_job,
            mark_cookies_valid_and_resume,
        )
        await enqueue_share_link_job()
        await enqueue_promote_job()
        await mark_cookies_valid_and_resume()
    except Exception as exc:
        logger.warning("Could not auto-enqueue jobs on session create: %s", exc)

    return WebSessionResponse(
        id=sess_obj.id,
        session_id=sess_obj.session_id,
        name=sess_obj.name,
        account_email=sess_obj.account_email,
        is_active=sess_obj.is_active,
        has_blob=bool(sess_obj.session_blob and len(sess_obj.session_blob) > 0),
        created_at=str(sess_obj.created_at),
        updated_at=str(sess_obj.updated_at),
    )


@router.get("/sessions/{session_id}", response_model=WebSessionDetailResponse)
async def get_web_session(
    session_id: str,
    current_admin: dict = Depends(get_current_admin),
):
    """Get full details of a specific web session including cookies."""
    async with get_db() as db:
        stmt = select(WebSession).where(WebSession.session_id == session_id.strip())
        res = await db.execute(stmt)
        sess = res.scalar_one_or_none()

    if not sess:
        raise HTTPException(status_code=404, detail="Web session not found")

    blob_json = None
    if sess.session_blob:
        try:
            blob_json = json.dumps(json.loads(sess.session_blob.decode("utf-8")), indent=2, ensure_ascii=False)
        except Exception:
            blob_json = None

    return WebSessionDetailResponse(
        id=sess.id,
        session_id=sess.session_id,
        name=sess.name,
        account_email=sess.account_email,
        raw_cookies=sess.raw_cookies,
        session_blob_json=blob_json,
        session_blob_hex=sess.session_blob.hex() if sess.session_blob else None,
        is_active=sess.is_active,
        has_blob=bool(sess.session_blob and len(sess.session_blob) > 0),
        created_at=str(sess.created_at),
        updated_at=str(sess.updated_at),
    )


@router.put("/sessions/{session_id}", response_model=WebSessionResponse)
async def update_web_session(
    session_id: str,
    req: WebSessionUpdate,
    current_admin: dict = Depends(get_current_admin),
):
    """Update session name, cookies, or active state."""
    async with get_db() as db:
        stmt = select(WebSession).where(WebSession.session_id == session_id.strip())
        res = await db.execute(stmt)
        sess = res.scalar_one_or_none()
        if not sess:
            raise HTTPException(status_code=404, detail="Web session not found")

        if req.name is not None:
            sess.name = req.name.strip()
        if req.is_active is not None:
            sess.is_active = req.is_active

        if req.cookies:
            raw_cookies = req.cookies.strip()
            status = await NativeWebClient.check_status_async(raw_cookies)
            if not status.valid:
                raise HTTPException(status_code=400, detail=f"Cookie verification failed: {status.message}")
            client = None
            try:
                client = NativeWebClient(cookies=raw_cookies)
                blob = client.export_session_blob()
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Failed to refresh session blob: {exc}")
            finally:
                if client:
                    client.close()

            sess.raw_cookies = raw_cookies
            sess.session_blob = blob
            sess.is_active = True
            if status.account:
                sess.account_email = status.account

        await db.flush()
        await db.refresh(sess)

    if req.cookies:
        try:
            from app.services.notice_service import resolve_notice
            await resolve_notice(f"cookies_{session_id}")
        except Exception:
            pass

    # Automatically trigger worker to resume any pending temporary files and deferred imports
    if req.cookies:
        try:
            from app.services.background_worker import (
                enqueue_promote_job,
                enqueue_share_link_job,
                mark_cookies_valid_and_resume,
            )
            await enqueue_share_link_job()
            await enqueue_promote_job()
            await mark_cookies_valid_and_resume()
        except Exception as exc:
            logger.warning("Could not auto-enqueue jobs on session update: %s", exc)

    return WebSessionResponse(
        id=sess.id,
        session_id=sess.session_id,
        name=sess.name,
        account_email=sess.account_email,
        is_active=sess.is_active,
        has_blob=bool(sess.session_blob and len(sess.session_blob) > 0),
        created_at=str(sess.created_at),
        updated_at=str(sess.updated_at),
    )


@router.delete("/sessions/{session_id}")
async def delete_web_session(
    session_id: str,
    current_admin: dict = Depends(get_current_admin),
):
    """Delete a web cookie session."""
    async with get_db() as db:
        stmt = delete(WebSession).where(WebSession.session_id == session_id.strip())
        res = await db.execute(stmt)
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Web session not found")
    return {"success": True, "message": f"Session '{session_id}' deleted successfully"}


@router.post("/sessions/{session_id}/check", response_model=WebSessionStatusResponse)
async def check_session_status(
    session_id: str,
    current_admin: dict = Depends(get_current_admin),
):
    """Verify live status of a stored session with Google Photos."""
    async with get_db() as db:
        stmt = select(WebSession).where(WebSession.session_id == session_id.strip())
        res = await db.execute(stmt)
        sess = res.scalar_one_or_none()

    if not sess:
        raise HTTPException(status_code=404, detail="Web session not found")

    status = await NativeWebClient.check_status_async(sess.raw_cookies)

    # Persist live validity to is_active in SQLite
    async with get_db() as db:
        await db.execute(
            update(WebSession)
            .where(WebSession.session_id == session_id.strip())
            .values(is_active=status.valid)
        )

    if not status.valid:
        from app.services.notice_service import record_notice
        await record_notice(
            title="Instant Session Expired",
            message=f"Instant Session '{session_id}' ({sess.account_email or 'No email'}) cookies are invalid: {status.message}. Please update cookies in dashboard.",
            level="error",
            source=f"cookies_{session_id}",
        )
    else:
        from app.services.notice_service import resolve_notice
        await resolve_notice(f"cookies_{session_id}")
        try:
            from app.services.background_worker import mark_cookies_valid_and_resume
            await mark_cookies_valid_and_resume()
        except Exception as exc:
            logger.warning("Could not auto-resume imports on session check: %s", exc)

    return WebSessionStatusResponse(
        valid=status.valid,
        account=status.account,
        message=status.message,
    )


@router.get("/quota")
async def get_storage_quota(
    session_id: Optional[str] = None,
    current_admin: dict = Depends(get_current_admin),
):
    """Retrieve Google Photos account storage quota and limits."""
    client, target_session_id = await get_web_client(session_id)
    try:
        quota = await client.get_storage_quota_async()
        await sync_session_blob(target_session_id, client)
        return {
            "usage_text": quota.usage_text,
            "used_display": quota.used_display,
            "total_display": quota.total_display,
            "used_percent": quota.used_percent,
            "free_percent": quota.free_percent,
            "used_bytes": quota.used_bytes,
            "total_bytes": quota.total_bytes,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch storage quota: {exc}")
    finally:
        client.close()


@router.post("/reset-account", response_model=AccountResetResponse)
async def reset_account(
    req: AccountResetRequest,
    current_admin: dict = Depends(get_current_admin),
):
    """Wipe Google Photos library: move all items to trash and permanently empty trash."""
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required to permanently wipe Google Photos library")

    client, session_id = await get_web_client(req.session_id)
    try:
        reset_res = client.reset_account(timeout_ms=180000)
        await sync_session_blob(session_id, client)
        if reset_res.success:
            from app.services.notice_service import resolve_notice
            await resolve_notice("quota")
        return AccountResetResponse(
            success=reset_res.success,
            total_deleted=reset_res.total_deleted,
            trash_emptied=reset_res.trash_emptied,
            message=reset_res.message,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Account reset failed: {exc}")
    finally:
        client.close()


@router.post("/delete")
async def delete_web_item(
    payload: dict,
    current_admin: dict = Depends(get_current_admin),
):
    """Bridge for dashboard confirmDeleteMedia: delete single item."""
    from app.routers.media import SingleDeleteRequest, delete_single_media

    media_key = payload.get("media_key") or None
    dedup_key = payload.get("dedup_key") or None
    drive_ref_id = payload.get("drive_ref_id") or None
    drive_id = payload.get("drive_id") or None
    return await delete_single_media(
        SingleDeleteRequest(
            media_key=media_key,
            dedup_key=dedup_key,
            drive_ref_id=drive_ref_id,
            drive_id=drive_id,
        ),
        current_admin=current_admin,
    )


@router.post("/clear-errors")
async def clear_all_error_media_web(current_admin: dict = Depends(get_current_admin)):
    """Bridge for dashboard clear error files."""
    from app.routers.media import clear_all_error_media
    return await clear_all_error_media(current_admin=current_admin)


@router.post("/requeue-errors")
async def requeue_all_error_media_web(current_admin: dict = Depends(get_current_admin)):
    """Bridge for dashboard requeue error files."""
    from app.routers.media import requeue_all_error_media
    return await requeue_all_error_media(current_admin=current_admin)


@router.post("/reset-media")
async def reset_media_web(
    req: dict,
    current_admin: dict = Depends(get_current_admin),
):
    """Bridge for dashboard reset all media."""
    from app.routers.media import MediaResetRequest, reset_all_media_database
    confirm_val = req.get("confirm", "")
    return await reset_all_media_database(MediaResetRequest(confirm=confirm_val), current_admin=current_admin)

