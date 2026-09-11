"""
Download token router.
GET /download/{token}     → beautiful HTML page
GET /api/download/{token} → JSON status/download_url
"""
import asyncio
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy import select, update

from app.config import STREAM_MANIFEST_THROTTLE_SECONDS
from app.database import get_db
from app.models import ApiKey, DriveRef, PermanentItem, TempImport
from app.schemas import DownloadTokenResponse
from app.services.cache_service import get_cached_url, set_cached_url
from app.services.stream_cache_service import (
    fetch_and_cache_stream,
    get_cached_stream,
    is_stream_cached,
    set_cached_stream,
)

router = APIRouter(tags=["Download"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

logger = logging.getLogger("photos_engine.download")


async def _resolve_brand_name(request: Request) -> str | None:
    """
    White-label branding: when a download request carries a valid, active API key
    (X-API-Key header, ?api_key= query, or Bearer gpmc_… token), the page header
    shows that key's name instead of the default "Instant Engine" brand.
    """
    candidates = []
    header_key = request.headers.get("x-api-key")
    if header_key and header_key.strip():
        candidates.append(header_key.strip())
    query_key = request.query_params.get("api_key")
    if query_key and query_key.strip():
        candidates.append(query_key.strip())
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        bearer = auth[7:].strip()
        if bearer.startswith("gpmc_") or bearer.count(".") != 2:
            candidates.append(bearer)

    for candidate in candidates:
        async with get_db() as db:
            res = await db.execute(
                select(ApiKey).where(ApiKey.key == candidate, ApiKey.is_active.is_(True))
            )
            key_obj = res.scalar_one_or_none()
        if not key_obj:
            continue
        if key_obj.expires_at:
            now_utc = datetime.now(timezone.utc)
            exp_utc = key_obj.expires_at
            if exp_utc.tzinfo is None:
                exp_utc = exp_utc.replace(tzinfo=timezone.utc)
            if now_utc > exp_utc:
                continue
        return key_obj.name
    return None


async def _resolve_token(token: str) -> tuple[DriveRef | None, PermanentItem | None, TempImport | None]:
    """Resolve token → (drive_ref, permanent_item, temp_import). Any can be None."""
    async with get_db() as db:
        stmt = select(DriveRef).where(DriveRef.token == token)
        res = await db.execute(stmt)
        drive_ref = res.scalar_one_or_none()

    if not drive_ref:
        return None, None, None

    async with get_db() as db:
        stmt = select(PermanentItem).where(PermanentItem.drive_ref_id == drive_ref.id).limit(1)
        res = await db.execute(stmt)
        perm = res.scalar_one_or_none()

    if perm:
        return drive_ref, perm, None

    async with get_db() as db:
        stmt = (
            select(TempImport)
            .where(TempImport.drive_ref_id == drive_ref.id)
            .order_by(TempImport.id.desc())
            .limit(1)
        )
        res = await db.execute(stmt)
        temp = res.scalar_one_or_none()

    return drive_ref, None, temp


async def _get_download_url(media_key: str, source: str) -> str | None:
    """Try cache first, then resolve via appropriate client."""
    cached = await get_cached_url(media_key)
    if cached and cached.get("download_url"):
        return cached["download_url"]

    if source == "permanent":
        # Use mobile client for permanent items
        try:
            from app.services.mobile_service import get_mobile_client
            client, _ = await get_mobile_client()
            info = await client.get_download_url_async(media_key)
            if info.download_url:
                await set_cached_url(media_key, info.download_url, dedup_key=getattr(info, "dedup_key", None), source="mobile")
                return info.download_url
        except Exception as exc:
            logger.warning("[download] Mobile URL resolve failed for %s: %s", media_key, exc)
    else:
        # Use web client for temp items
        try:
            from app.services.web_service import get_web_client, sync_session_blob
            client, session_id = await get_web_client()
            info = await client.get_download_url_async(media_key)
            await sync_session_blob(session_id, client)
            client.close()
            if info.download_url:
                await set_cached_url(media_key, info.download_url, dedup_key=getattr(info, "dedup_key", None), source="web")
                return info.download_url
        except Exception as exc:
            logger.warning("[download] Web URL resolve failed for %s: %s", media_key, exc)

    return None


@router.get("/api/download/{token}", response_model=DownloadTokenResponse)
async def get_download_info(token: str):
    """JSON status for a token: returns download_url when ready."""
    drive_ref, perm, temp = await _resolve_token(token)

    if not drive_ref:
        raise HTTPException(status_code=404, detail="Token not found")

    if perm:
        download_url = await _get_download_url(perm.media_key, "permanent")
        has_stream_cache = await is_stream_cached(perm.media_key)
        return DownloadTokenResponse(
            token=token,
            drive_id=drive_ref.drive_id,
            status="ready",
            download_url=download_url,
            filename=drive_ref.filename,
            file_size=drive_ref.file_size,
            is_permanent=True,
            has_stream_cache=has_stream_cache,
        )

    if temp:
        download_url = await _get_download_url(temp.media_key, "temp")
        return DownloadTokenResponse(
            token=token,
            drive_id=drive_ref.drive_id,
            status="ready" if download_url else "processing",
            download_url=download_url,
            filename=drive_ref.filename,
            file_size=drive_ref.file_size,
            share_url=temp.share_url,
            is_permanent=False,
            has_stream_cache=False,
        )

    # drive_ref exists but no temp or permanent (edge case: mid-import)
    return DownloadTokenResponse(
        token=token,
        drive_id=drive_ref.drive_id,
        status="processing",
        filename=drive_ref.filename,
        file_size=drive_ref.file_size,
        is_permanent=False,
        has_stream_cache=False,
    )


@router.get("/download/{token}", response_class=HTMLResponse)
async def download_page(request: Request, token: str, background_tasks: BackgroundTasks):
    brand_name = await _resolve_brand_name(request)
    drive_ref, perm, temp = await _resolve_token(token)
    if not drive_ref:
        return templates.TemplateResponse(
            request=request,
            name="download.html",
            context={"status": "not_found", "token": token, "brand_name": brand_name},
        )

    # White-label: file imported via an API key → show that key's name
    if not brand_name and drive_ref.api_key_id:
        async with get_db() as db:
            res = await db.execute(select(ApiKey).where(ApiKey.id == drive_ref.api_key_id))
            importer_key = res.scalar_one_or_none()
        if importer_key and importer_key.is_active:
            brand_name = importer_key.name

    context = {
        "token": token,
        "drive_id": drive_ref.drive_id,
        "status": "processing",
        "download_url": None,
        "filename": drive_ref.filename,
        "file_size": drive_ref.file_size,
        "share_url": None,
        "brand_name": brand_name,
        "is_permanent": False,
        "has_stream_cache": False,
    }

    if perm:
        download_url = await _get_download_url(perm.media_key, "permanent")
        has_stream_cache = await is_stream_cached(perm.media_key)
        if not has_stream_cache:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            last_chk = perm.last_manifest_check.replace(tzinfo=None) if perm.last_manifest_check else None
            if last_chk is None or (now - last_chk).total_seconds() >= STREAM_MANIFEST_THROTTLE_SECONDS:
                async with get_db() as db:
                    await db.execute(
                        update(PermanentItem)
                        .where(PermanentItem.id == perm.id)
                        .values(last_manifest_check=now)
                    )
                background_tasks.add_task(fetch_and_cache_stream, perm.media_key, drive_ref.id)

        context.update({
            "status": "ready",
            "download_url": download_url,
            "is_permanent": True,
            "has_stream_cache": has_stream_cache,
        })
    elif temp:
        download_url = await _get_download_url(temp.media_key, "temp")
        context.update({
            "status": "ready" if download_url else "processing",
            "download_url": download_url,
            "share_url": temp.share_url,
            "is_permanent": False,
            "has_stream_cache": False,
        })

    return templates.TemplateResponse(request=request, name="download.html", context=context)


@router.get("/player/{token}", response_class=HTMLResponse)
@router.get("/embed/{token}", response_class=HTMLResponse)
async def player_page(request: Request, token: str):
    """Serve dedicated full-browser or iframe-embeddable ArtPlayer."""
    drive_ref, perm, temp = await _resolve_token(token)
    if not drive_ref:
        raise HTTPException(status_code=404, detail="Token not found")
    if not perm:
        raise HTTPException(
            status_code=400,
            detail="Streaming is only available for items stored permanently in the Google Photos library.",
        )

    context = {
        "token": token,
        "filename": drive_ref.filename,
    }
    return templates.TemplateResponse(request=request, name="player.html", context=context)


@router.get("/api/download/{token}/manifest")
async def get_streaming_manifest(token: str):
    """Fetch direct streaming video and audio streams for a permanent item."""
    drive_ref, perm, temp = await _resolve_token(token)
    if not drive_ref:
        raise HTTPException(status_code=404, detail="Token not found")
    if not perm:
        raise HTTPException(
            status_code=400,
            detail="Streaming is only available for items stored permanently in the Google Photos library.",
        )

    # 1. Try 20-min stream cache first
    cached_stream = await get_cached_stream(perm.media_key)
    if cached_stream and cached_stream.get("videos"):
        return {
            "success": True,
            "ready": True,
            "filename": drive_ref.filename,
            "media_key": perm.media_key,
            "videos": cached_stream["videos"],
            "audios": cached_stream.get("audios") or [],
        }

    try:
        from app.services.streaming_service import get_streaming_data_for_media_key

        stream_data = await get_streaming_data_for_media_key(perm.media_key)
        if stream_data and stream_data.get("videos"):
            await set_cached_stream(
                media_key=perm.media_key,
                drive_ref_id=drive_ref.id,
                video_streams=stream_data["videos"],
                audio_streams=stream_data.get("audios"),
            )
        return {
            "success": True,
            "ready": True,
            "filename": drive_ref.filename,
            "media_key": perm.media_key,
            "videos": stream_data["videos"],
            "audios": stream_data["audios"],
        }
    except Exception as exc:
        err_msg = str(exc)
        if "not ready" in err_msg or "404" in err_msg:
            return JSONResponse(
                status_code=422,
                content={
                    "success": False,
                    "ready": False,
                    "detail": "Video is still being processed by Google Photos. Streaming will be available once processing completes.",
                },
            )
        logger.warning("[download] DASH manifest fetch failed for token %s: %s", token, exc)
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch streaming manifest from Google Photos: {exc}",
        )


@router.get("/api/download/{token}/manifest.mpd")
async def get_streaming_manifest_mpd(token: str):
    """Serve DASH .mpd XML manifest directly for video players."""
    drive_ref, perm, temp = await _resolve_token(token)
    if not drive_ref or not perm:
        raise HTTPException(status_code=404, detail="Not found or not a permanent item")

    try:
        from app.services.mobile_service import get_mobile_client

        client, _ = await get_mobile_client()
        manifest = await client.get_stream_manifest_async(perm.media_key, protocol="dash")
        return Response(content=manifest, media_type="application/dash+xml")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))




