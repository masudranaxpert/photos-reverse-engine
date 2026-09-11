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
        async with get_db(write=False) as db:
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


async def _resolve_token(token: str) -> tuple[DriveRef | None, PermanentItem | None, TempImport | None, str]:
    """
    Resolve token_or_signed → (drive_ref, permanent_item, temp_import, token_status).
    token_status: 'valid' | 'expired' | 'not_found'
    """
    from app.services.signed_token_service import verify_expiring_token

    raw_token = token
    token_status = "valid"

    if len(token) == 45:
        extracted_token, verify_status = verify_expiring_token(token)
        if verify_status == "expired":
            token_status = "expired"
            raw_token = extracted_token
        elif verify_status == "valid":
            token_status = "valid"
            raw_token = extracted_token
        else:
            return None, None, None, "not_found"

    if not raw_token:
        return None, None, None, "not_found"

    async with get_db(write=False) as db:
        stmt = select(DriveRef).where(DriveRef.token == raw_token)
        res = await db.execute(stmt)
        drive_ref = res.scalar_one_or_none()

    if not drive_ref:
        return None, None, None, "not_found"

    if token_status == "expired":
        return drive_ref, None, None, "expired"

    async with get_db(write=False) as db:
        stmt = select(PermanentItem).where(PermanentItem.drive_ref_id == drive_ref.id).limit(1)
        res = await db.execute(stmt)
        perm = res.scalar_one_or_none()

    if perm:
        return drive_ref, perm, None, "valid"

    async with get_db(write=False) as db:
        stmt = (
            select(TempImport)
            .where(TempImport.drive_ref_id == drive_ref.id)
            .order_by(TempImport.id.desc())
            .limit(1)
        )
        res = await db.execute(stmt)
        temp = res.scalar_one_or_none()

    return drive_ref, None, temp, "valid"


_active_url_fetches: dict[str, asyncio.Task] = {}


async def _fetch_download_url_direct(media_key: str, source: str, timeout: float = 12.0) -> str | None:
    """Resolve download URL via appropriate client with timeout."""
    if source == "permanent":
        try:
            from app.services.mobile_service import get_mobile_client
            client, _ = await get_mobile_client()
            info = await client.get_download_url_async(media_key, timeout=timeout)
            if info.download_url:
                await set_cached_url(media_key, info.download_url, dedup_key=getattr(info, "dedup_key", None), source="mobile")
                return info.download_url
        except Exception as exc:
            logger.warning("[download] Mobile URL resolve failed for %s: %s", media_key, exc)
    else:
        try:
            from app.services.web_service import get_web_client
            client, _ = await get_web_client()
            try:
                info = await client.get_download_url_async(media_key, timeout=timeout)
                if info.download_url:
                    await set_cached_url(media_key, info.download_url, dedup_key=getattr(info, "dedup_key", None), source="web")
                    return info.download_url
            finally:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, client.close)
        except Exception as exc:
            logger.warning("[download] Web URL resolve failed for %s: %s", media_key, exc)

    return None


async def _get_download_url(media_key: str, source: str, timeout: float = 5.0) -> str | None:
    """Try cache first, then resolve via single-flight deduplicated task."""
    cached = await get_cached_url(media_key)
    if cached and cached.get("download_url"):
        return cached["download_url"]

    task = _active_url_fetches.get(media_key)
    if task is None or task.done():
        task = asyncio.create_task(_fetch_download_url_direct(media_key, source, timeout=25.0))
        _active_url_fetches[media_key] = task

    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
    except (asyncio.TimeoutError, TimeoutError):
        return None
    except Exception:
        return None
    finally:
        if task.done():
            _active_url_fetches.pop(media_key, None)


async def _increment_visitor_count(drive_ref_id: int, token: str) -> None:
    """Increment visitor count asynchronously in background without blocking response."""
    try:
        async with get_db() as db:
            await db.execute(
                update(DriveRef)
                .where(DriveRef.id == drive_ref_id)
                .values(visitor_count=DriveRef.visitor_count + 1)
            )
    except Exception as exc:
        logger.warning("[download] Failed to update visitor count for %s: %s", token, exc)


def _record_unique_visit(
    request: Request,
    response: Response,
    drive_ref_id: int,
    token: str,
    background_tasks: BackgroundTasks | None = None,
) -> None:
    """Record visitor view if no 24h cookie present, offloading DB write to background."""
    cookie_key = f"viewed_{token}"
    if not request.cookies.get(cookie_key):
        if background_tasks is not None:
            background_tasks.add_task(_increment_visitor_count, drive_ref_id, token)
        else:
            asyncio.create_task(_increment_visitor_count, drive_ref_id, token)
        response.set_cookie(
            key=cookie_key,
            value="1",
            max_age=86400,
            httponly=True,
            samesite="lax",
        )


@router.get("/api/download/{token}", response_model=DownloadTokenResponse)
async def get_download_info(token: str):
    """JSON status for a token: returns download_url when ready."""
    drive_ref, perm, temp, token_status = await _resolve_token(token)

    if token_status == "expired":
        return DownloadTokenResponse(
            token=token,
            status="expired",
            download_url=None,
            filename=drive_ref.filename if drive_ref else None,
            file_size=drive_ref.file_size if drive_ref else None,
            is_permanent=False,
            has_stream_cache=False,
        )

    if not drive_ref or token_status == "not_found":
        raise HTTPException(status_code=404, detail="Token not found")

    if perm:
        download_url = await _get_download_url(perm.media_key, "permanent")
        has_stream_cache = await is_stream_cached(perm.media_key)
        return DownloadTokenResponse(
            token=token,
            status="ready" if download_url else "processing",
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
            status="ready" if download_url else "processing",
            download_url=download_url,
            filename=drive_ref.filename,
            file_size=drive_ref.file_size,
            is_permanent=False,
            has_stream_cache=False,
        )

    # drive_ref exists but no temp or permanent (edge case: mid-import or error)
    return DownloadTokenResponse(
        token=token,
        status="failed" if drive_ref.file_status in ("error", "not_found", "unsupported") else "processing",
        filename=drive_ref.filename,
        file_size=drive_ref.file_size,
        is_permanent=False,
        has_stream_cache=False,
    )


@router.get("/download/{token}", response_class=HTMLResponse)
async def download_page(request: Request, token: str, background_tasks: BackgroundTasks):
    brand_name = await _resolve_brand_name(request)
    drive_ref, perm, temp, token_status = await _resolve_token(token)

    if token_status == "expired":
        return templates.TemplateResponse(
            request=request,
            name="download.html",
            context={
                "status": "expired",
                "token": token,
                "brand_name": brand_name,
                "filename": drive_ref.filename if drive_ref else None,
                "file_size": drive_ref.file_size if drive_ref else None,
            },
        )

    if not drive_ref or token_status == "not_found":
        return templates.TemplateResponse(
            request=request,
            name="download.html",
            context={"status": "not_found", "token": token, "brand_name": brand_name},
        )

    # White-label: file imported via an API key → show that key's name
    if not brand_name and drive_ref.api_key_id:
        async with get_db(write=False) as db:
            res = await db.execute(select(ApiKey).where(ApiKey.id == drive_ref.api_key_id))
            importer_key = res.scalar_one_or_none()
        if importer_key and importer_key.is_active:
            brand_name = importer_key.name

    # iOS detection: iPhone/iPad/iPod WebKit cannot play dual DASH stream
    ua = request.headers.get("user-agent", "")
    is_ios = any(dev in ua for dev in ("iPhone", "iPad", "iPod")) or ("Macintosh" in ua and "Mobile" in ua)

    context = {
        "token": token,
        "status": "processing",
        "download_url": None,
        "filename": drive_ref.filename,
        "file_size": drive_ref.file_size,
        "brand_name": brand_name,
        "is_permanent": False,
        "has_stream_cache": False,
        "is_ios": is_ios,
    }

    if perm:
        download_url = await _get_download_url(perm.media_key, "permanent", timeout=6.0)
        has_stream_cache = await is_stream_cached(perm.media_key)
        if not has_stream_cache:
            background_tasks.add_task(fetch_and_cache_stream, perm.media_key, drive_ref.id)

        context.update({
            "status": "ready" if download_url else "processing",
            "download_url": download_url,
            "is_permanent": True,
            "has_stream_cache": has_stream_cache,
        })
    elif temp:
        download_url = await _get_download_url(temp.media_key, "temp", timeout=6.0)
        context.update({
            "status": "ready" if download_url else "processing",
            "download_url": download_url,
            "is_permanent": False,
            "has_stream_cache": False,
        })
    else:
        if drive_ref.file_status in ("error", "not_found", "unsupported"):
            context["status"] = "failed"

    response = templates.TemplateResponse(request=request, name="download.html", context=context)
    _record_unique_visit(request, response, drive_ref.id, token, background_tasks=background_tasks)
    return response


@router.get("/player/{token}", response_class=HTMLResponse)
@router.get("/embed/{token}", response_class=HTMLResponse)
async def player_page(request: Request, token: str):
    """Serve dedicated full-browser or iframe-embeddable ArtPlayer."""
    drive_ref, perm, temp, token_status = await _resolve_token(token)
    if token_status == "expired":
        raise HTTPException(status_code=410, detail="Streaming link has expired.")
    if not drive_ref or token_status == "not_found":
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
    response = templates.TemplateResponse(request=request, name="player.html", context=context)
    _record_unique_visit(request, response, drive_ref.id, token)
    return response


@router.get("/api/download/{token}/manifest")
async def get_streaming_manifest(token: str):
    """Fetch direct streaming video and audio streams for a permanent item."""
    drive_ref, perm, temp, token_status = await _resolve_token(token)
    if token_status == "expired":
        raise HTTPException(status_code=410, detail="Streaming link has expired.")
    if not drive_ref or token_status == "not_found":
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
    drive_ref, perm, temp, token_status = await _resolve_token(token)
    if token_status == "expired":
        raise HTTPException(status_code=410, detail="Streaming link has expired.")
    if not drive_ref or not perm or token_status == "not_found":
        raise HTTPException(status_code=404, detail="Not found or not a permanent item")

    try:
        from app.services.streaming_service import get_streaming_data_for_media_key

        stream_data = await get_streaming_data_for_media_key(perm.media_key)
        return Response(content=stream_data["manifest"], media_type="application/dash+xml")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))




