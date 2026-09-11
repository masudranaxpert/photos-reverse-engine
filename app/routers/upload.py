"""
Single upload endpoint: POST /api/upload/{name}
Accepts a drive_id, pre-checks metadata via Google Drive API, handles quota-aware imports,
stores token, and queues background jobs.
"""
import asyncio
import logging
import uuid

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select

from app.database import get_db
from app.models import DriveRef
from app.schemas import UploadRequest, UploadResponse
from app.security import get_current_admin
from app.services.drive_api_service import get_drive_file_metadata
from app.services.signed_token_service import create_expiring_token

router = APIRouter(prefix="/api/upload", tags=["Upload"])

logger = logging.getLogger("photos_engine.upload")


def _build_download_url(request: Optional[Request], token: str) -> str:
    """Generate a clean 45-character URL-safe expiring download URL."""
    expiring_code = create_expiring_token(token)
    if not request:
        return f"/download/{expiring_code}"
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}/download/{expiring_code}"


async def _process_upload(
    drive_id_raw: str,
    label: Optional[str] = None,
    api_key_id: Optional[int] = None,
    request: Optional[Request] = None,
) -> UploadResponse:
    drive_id = drive_id_raw.strip()
    label = (label.strip() if label else "") or drive_id[:16]

    # ── 1. Pre-check: Ensure an active Google Photos web session exists ────────
    from app.services.web_service import get_active_session_row
    active_sess = await get_active_session_row()
    if not active_sess:
        logger.warning("[upload] Aborting upload for drive_id=%s: Instant Session is expired or offline.", drive_id)
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unavailable. Please try again later.",
        )

    # ── 2. Check for existing drive_ref (idempotent) ───────────────────────────
    async with get_db(write=False) as db:
        stmt = select(DriveRef).where(DriveRef.drive_id == drive_id)
        res = await db.execute(stmt)
        existing = res.scalar_one_or_none()

    if existing:
        if existing.file_status == "not_found":
            logger.info("[upload] drive_id=%s previously marked not_found", drive_id)
            raise HTTPException(
                status_code=404,
                detail="Google Drive file not found or inaccessible.",
            )
        if existing.file_status == "error":
            logger.info("[upload] drive_id=%s previously failed with error. Removing stale record to retry.", drive_id)
            async with get_db() as db:
                await db.execute(delete(DriveRef).where(DriveRef.id == existing.id))
            existing = None
        else:
            logger.info("[upload] drive_id=%s already exists, returning token=%s", drive_id, existing.token)
            return UploadResponse(
                token=existing.token,
                drive_id=drive_id,
                status="already_exists",
                filename=existing.filename,
                file_size=existing.file_size,
                download_url=_build_download_url(request, existing.token),
            )

    # ── 2. Query Google Drive API for exact file metadata ──────────────────────
    meta = await get_drive_file_metadata(drive_id)
    if meta.status == "not_found":
        logger.warning("[upload] Drive API returned not_found for drive_id=%s: %s", drive_id, meta.error_message)
        # Record file_status='not_found' so future calls immediately abort without overhead
        async with get_db() as db:
            dead_ref = DriveRef(
                drive_id=drive_id,
                token=uuid.uuid4().hex,
                label=label,
                file_status="not_found",
                error_message=meta.error_message or "Google Drive file not found or inaccessible.",
                api_key_id=api_key_id,
            )
            db.add(dead_ref)
        raise HTTPException(
            status_code=404,
            detail=meta.error_message or "Google Drive file not found or inaccessible.",
        )
    elif meta.status == "error":
        logger.error("[upload] Drive API error for drive_id=%s: %s", drive_id, meta.error_message)
        raise HTTPException(
            status_code=400,
            detail="Google Drive file could not be accessed. Please check file ID or try again later.",
        )

    filename = meta.filename
    file_size = meta.file_size
    mime_type = meta.mime_type or "video/*"
    if filename and (label == drive_id[:16] or not label):
        label = filename

    # ── 3. Persist DriveRef with pre-fetched metadata and status="queued" ───────
    token = uuid.uuid4().hex
    drive_ref_id: int | None = None

    for attempt in range(5):
        try:
            async with get_db() as db:
                drive_ref = DriveRef(
                    drive_id=drive_id,
                    token=token,
                    label=label,
                    filename=filename,
                    file_size=file_size,
                    file_status="queued",
                    api_key_id=api_key_id,
                )
                db.add(drive_ref)
                await db.commit()
                drive_ref_id = drive_ref.id
                break
        except Exception as exc:
            if "locked" in str(exc).lower() and attempt < 4:
                await asyncio.sleep(0.1 * (2 ** attempt))
                continue
            raise

    # ── 4. Queue async background import into Google Photos ────────────────────
    from app.services.background_worker import queue_drive_import
    await queue_drive_import(
        drive_ref_id=drive_ref_id,
        drive_id=drive_id,
        mime_type=mime_type,
        file_size=file_size,
        filename=filename,
    )

    logger.info(
        "[upload] QUEUED drive_id=%s token=%s name='%s' size=%s key_id=%s",
        drive_id, token, filename, file_size, api_key_id,
    )

    # ── 5. Immediately return response with token and file metadata ───────────
    return UploadResponse(
        token=token,
        drive_id=drive_id,
        status="queued",
        filename=filename,
        file_size=file_size,
        download_url=_build_download_url(request, token),
    )


@router.post("", response_model=UploadResponse)
async def upload_drive_file(
    req: UploadRequest,
    request: Request,
    current_auth: dict = Depends(get_current_admin),
):
    """
    Import a Google Drive file into Google Photos and return a download token.
    Requires an active API key (X-API-Key header or api_key query) or admin session.
    """
    api_key_id = current_auth.get("key_id") if current_auth.get("auth_type") == "api_key" else None
    return await _process_upload(req.drive_id, api_key_id=api_key_id, request=request)


@router.post("/{name}", response_model=UploadResponse, include_in_schema=False)
async def upload_by_name(
    name: str,
    req: UploadRequest,
    request: Request,
    current_auth: dict = Depends(get_current_admin),
):
    """Legacy alias supporting path-based names."""
    api_key_id = current_auth.get("key_id") if current_auth.get("auth_type") == "api_key" else None
    return await _process_upload(req.drive_id, label=name, api_key_id=api_key_id, request=request)
