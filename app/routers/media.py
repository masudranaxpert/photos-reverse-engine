"""Media repository router: list + stats. Delete removed (handled by background worker)."""
import json
import math
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, delete, func, or_, select

from app.database import get_db
from app.models import ApiKey, BackgroundJob, DownloadCache, DriveRef, MobileAccount, PermanentItem, StreamCache, TempImport, WebSession
from app.security import get_current_admin

router = APIRouter(prefix="/api/media", tags=["Media Files & Dashboard"])


class MediaItemResponse(BaseModel):
    id: int
    drive_id: str
    token: str
    title: Optional[str] = None
    filename: Optional[str] = None
    file_size: Optional[int] = None
    media_key: Optional[str] = None
    dedup_key: Optional[str] = None
    share_url: Optional[str] = None
    email: Optional[str] = None
    stage: str
    source: str
    drive_file_id: Optional[str] = None
    download_url: Optional[str] = None
    error_message: Optional[str] = None
    api_key_id: Optional[int] = None
    api_key_name: Optional[str] = None
    visitor_count: int = 0
    created_at: str


class MediaListResponse(BaseModel):
    items: List[MediaItemResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class DashboardStatsResponse(BaseModel):
    total_media: int
    active_web_sessions: int
    active_mobile_accounts: int
    cached_download_urls: int
    cached_stream_urls: int = 0
    permanent_count: int = 0
    temp_count: int = 0


@router.get("", response_model=MediaListResponse)
async def list_media_files(
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=100),
    search: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    current_admin: dict = Depends(get_current_admin),
):
    """Retrieve paginated media files repository mapped to active DriveRefs and imports."""
    offset = (page - 1) * page_size

    async with get_db(write=False) as db:
        base_query = (
            select(DriveRef, PermanentItem, TempImport, ApiKey.name)
            .outerjoin(PermanentItem, PermanentItem.drive_ref_id == DriveRef.id)
            .outerjoin(TempImport, TempImport.drive_ref_id == DriveRef.id)
            .outerjoin(ApiKey, ApiKey.id == DriveRef.api_key_id)
        )
        count_query = (
            select(func.count(DriveRef.id))
            .outerjoin(PermanentItem, PermanentItem.drive_ref_id == DriveRef.id)
            .outerjoin(TempImport, TempImport.drive_ref_id == DriveRef.id)
        )

        if search and search.strip():
            term = f"%{search.strip()}%"
            search_filter = or_(
                DriveRef.drive_id.ilike(term),
                DriveRef.label.ilike(term),
                DriveRef.filename.ilike(term),
                DriveRef.token.ilike(term),
                PermanentItem.media_key.ilike(term),
                TempImport.media_key.ilike(term),
            )
            base_query = base_query.where(search_filter)
            count_query = count_query.where(search_filter)

        if source and source.strip() and source.strip().lower() != "all":
            src = source.strip().lower()
            if src == "permanent":
                src_filter = PermanentItem.id.isnot(None)
            elif src == "temp":
                src_filter = and_(TempImport.id.isnot(None), PermanentItem.id.is_(None))
            else:
                src_filter = DriveRef.file_status == src
            base_query = base_query.where(src_filter)
            count_query = count_query.where(src_filter)

        total_res = await db.execute(count_query)
        total = total_res.scalar() or 0

        stmt = base_query.order_by(DriveRef.id.desc()).limit(page_size).offset(offset)
        rows_res = await db.execute(stmt)
        rows = rows_res.all()

    items = []
    for drive_ref, perm, temp, api_key_name in rows:
        media_key = perm.media_key if perm else (temp.media_key if temp else None)
        dedup_key = temp.dedup_key if temp else None
        title = drive_ref.filename or drive_ref.label or f"Drive_{drive_ref.drive_id[:12]}"
        item_stage = "permanent" if perm else ("temp" if temp else drive_ref.file_status)
        share_url = temp.share_url if temp else None
        email = perm.email if perm else None
        items.append(
            MediaItemResponse(
                id=drive_ref.id,
                drive_id=drive_ref.drive_id,
                token=drive_ref.token,
                title=title,
                filename=drive_ref.filename,
                file_size=drive_ref.file_size,
                media_key=media_key,
                dedup_key=dedup_key,
                share_url=share_url,
                email=email,
                stage=item_stage,
                source=item_stage,
                drive_file_id=drive_ref.drive_id,
                download_url=f"/download/{drive_ref.token}",
                error_message=drive_ref.error_message,
                api_key_id=drive_ref.api_key_id,
                api_key_name=api_key_name,
                visitor_count=drive_ref.visitor_count or 0,
                created_at=str(drive_ref.created_at),
            )
        )

    total_pages = max(1, math.ceil(total / page_size)) if total > 0 else 1

    return MediaListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(current_admin: dict = Depends(get_current_admin)):
    """Summary counts for top dashboard metrics."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with get_db(write=False) as db:
        c1 = await db.execute(select(func.count(DriveRef.id)))
        total_media = c1.scalar() or 0

        c2 = await db.execute(
            select(func.count(WebSession.id)).where(WebSession.is_active.is_(True))
        )
        active_web = c2.scalar() or 0

        c3 = await db.execute(
            select(func.count(MobileAccount.id)).where(MobileAccount.is_active.is_(True))
        )
        active_mobile = c3.scalar() or 0

        c4 = await db.execute(
            select(func.count(DownloadCache.media_key)).where(DownloadCache.expires_at > now)
        )
        cached_links = c4.scalar() or 0

        c_stream = await db.execute(
            select(func.count(StreamCache.id)).where(StreamCache.expires_at > now)
        )
        cached_streams = c_stream.scalar() or 0

        c_perm = await db.execute(select(func.count(PermanentItem.id)))
        perm_cnt = c_perm.scalar() or 0

        c_temp = await db.execute(select(func.count(TempImport.id)))
        temp_cnt = c_temp.scalar() or 0

    return DashboardStatsResponse(
        total_media=total_media,
        active_web_sessions=active_web,
        active_mobile_accounts=active_mobile,
        cached_download_urls=cached_links,
        cached_stream_urls=cached_streams,
        permanent_count=perm_cnt,
        temp_count=temp_cnt,
    )


class CachedUrlItem(BaseModel):
    media_key: str
    dedup_key: Optional[str] = None
    source: str
    download_url: str
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    remaining_sec: int


class CachedUrlsResponse(BaseModel):
    items: List[CachedUrlItem]
    total: int
    page: int
    limit: int
    totalPages: int


@router.get("/cached-urls", response_model=CachedUrlsResponse)
async def list_cached_urls(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    status: Optional[str] = Query("all"),
    current_admin: dict = Depends(get_current_admin),
):
    """Paginated list of 30-minute cached download URLs with search and source filtering."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    filters = []

    search_str = search.strip() if isinstance(search, str) and search.strip() else None
    if search_str:
        term = f"%{search_str}%"
        filters.append(
            or_(
                DownloadCache.media_key.ilike(term),
                DownloadCache.dedup_key.ilike(term),
            )
        )

    source_str = source.strip().lower() if isinstance(source, str) and source.strip() else None
    if source_str and source_str != "all":
        filters.append(DownloadCache.source == source_str)

    status_str = status.strip().lower() if isinstance(status, str) and status.strip() else "all"
    if status_str == "active":
        filters.append(DownloadCache.expires_at > now)
    elif status_str == "expired":
        filters.append(DownloadCache.expires_at <= now)

    async with get_db(write=False) as db:
        count_stmt = select(func.count(DownloadCache.media_key))
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = (await db.execute(count_stmt)).scalar() or 0

        total_pages = max(1, math.ceil(total / limit)) if total > 0 else 1

        stmt = (
            select(DownloadCache)
            .order_by(DownloadCache.expires_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        if filters:
            stmt = stmt.where(*filters)
        res = await db.execute(stmt)
        cached_items = res.scalars().all()

    items = []
    for c in cached_items:
        rem = 0
        if c.expires_at:
            exp = c.expires_at.replace(tzinfo=None) if c.expires_at.tzinfo else c.expires_at
            rem = max(0, int((exp - now).total_seconds()))
        items.append(
            CachedUrlItem(
                media_key=c.media_key,
                dedup_key=c.dedup_key,
                source=c.source,
                download_url=c.download_url,
                created_at=c.created_at,
                expires_at=c.expires_at,
                remaining_sec=rem,
            )
        )

    return CachedUrlsResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
        totalPages=total_pages,
    )


@router.delete("/cached-urls/{media_key}")
async def delete_cached_url(
    media_key: str,
    current_admin: dict = Depends(get_current_admin),
):
    """Evict a specific cached URL entry."""
    async with get_db() as db:
        res = await db.execute(delete(DownloadCache).where(DownloadCache.media_key == media_key))
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Cached URL not found")
    return {"message": "Cached URL evicted successfully", "media_key": media_key}


@router.post("/cached-urls/cleanup")
async def purge_expired_cache(
    current_admin: dict = Depends(get_current_admin),
):
    """Purge all expired download cache entries immediately."""
    from app.services.cache_service import cleanup_expired_cache
    deleted = await cleanup_expired_cache()
    return {"message": f"Purged {deleted} expired cached URLs", "deleted": deleted}


class StreamCacheItem(BaseModel):
    id: int
    media_key: str
    drive_ref_id: Optional[int] = None
    filename: Optional[str] = None
    token: Optional[str] = None
    video_count: int = 0
    resolutions: List[str] = []
    has_audio: bool = False
    videos: Optional[List[Any]] = None
    audios: Optional[List[Any]] = None
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    remaining_sec: int = 0


class StreamCacheResponse(BaseModel):
    items: List[StreamCacheItem]
    total: int
    page: int
    limit: int
    totalPages: int


@router.get("/stream-cache", response_model=StreamCacheResponse)
async def list_stream_cache(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None),
    status: Optional[str] = Query("all"),
    current_admin: dict = Depends(get_current_admin),
):
    """Paginated list of 20-minute cached DASH stream representations with search and status filtering."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    filters = []

    search_str = search.strip() if isinstance(search, str) and search.strip() else None
    if search_str:
        term = f"%{search_str}%"
        filters.append(
            or_(
                StreamCache.media_key.ilike(term),
                DriveRef.filename.ilike(term),
                DriveRef.token.ilike(term),
            )
        )

    status_str = status.strip().lower() if isinstance(status, str) and status.strip() else "all"
    if status_str == "active":
        filters.append(StreamCache.expires_at > now)
    elif status_str == "expired":
        filters.append(StreamCache.expires_at <= now)

    async with get_db(write=False) as db:
        count_stmt = select(func.count(StreamCache.id)).outerjoin(
            DriveRef, StreamCache.drive_ref_id == DriveRef.id
        )
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = (await db.execute(count_stmt)).scalar() or 0

        total_pages = max(1, math.ceil(total / limit)) if total > 0 else 1

        stmt = (
            select(StreamCache, DriveRef.filename, DriveRef.token)
            .outerjoin(DriveRef, StreamCache.drive_ref_id == DriveRef.id)
            .order_by(StreamCache.expires_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        if filters:
            stmt = stmt.where(*filters)
        res = await db.execute(stmt)
        rows = res.all()

    items = []
    for s, filename, token in rows:
        rem = 0
        if s.expires_at:
            exp = s.expires_at.replace(tzinfo=None) if s.expires_at.tzinfo else s.expires_at
            rem = max(0, int((exp - now).total_seconds()))

        video_count = 0
        resolutions = []
        has_audio = False
        try:
            vids = json.loads(s.video_streams) if s.video_streams else []
            video_count = len(vids)
            for v in vids:
                lbl = v.get("label") or v.get("resolution")
                if lbl and lbl not in resolutions:
                    resolutions.append(lbl)
        except Exception:
            pass

        try:
            auds = json.loads(s.audio_streams) if s.audio_streams else []
            has_audio = len(auds) > 0
        except Exception:
            pass

        items.append(
            StreamCacheItem(
                id=s.id,
                media_key=s.media_key,
                drive_ref_id=s.drive_ref_id,
                filename=filename,
                token=token,
                video_count=video_count,
                resolutions=resolutions,
                has_audio=has_audio,
                videos=vids,
                audios=auds,
                created_at=s.created_at,
                expires_at=s.expires_at,
                remaining_sec=rem,
            )
        )

    return StreamCacheResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
        totalPages=total_pages,
    )


@router.delete("/stream-cache/{id}")
async def delete_stream_cache(
    id: int,
    current_admin: dict = Depends(get_current_admin),
):
    """Evict a specific stream cache entry by id."""
    async with get_db() as db:
        res = await db.execute(delete(StreamCache).where(StreamCache.id == id))
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Stream cache entry not found")
    return {"message": "Stream cache entry evicted successfully", "id": id}


@router.post("/stream-cache/cleanup")
async def purge_expired_stream_cache_endpoint(
    current_admin: dict = Depends(get_current_admin),
):
    """Purge all expired stream cache entries immediately."""
    from app.services.stream_cache_service import cleanup_expired_stream_cache
    deleted = await cleanup_expired_stream_cache()
    return {"message": f"Purged {deleted} expired stream cache entries", "deleted": deleted}


class SingleDeleteRequest(BaseModel):
    media_key: Optional[str] = None
    dedup_key: Optional[str] = None
    drive_id: Optional[str] = None
    drive_ref_id: Optional[int] = None


@router.post("/clear-temp")
async def clear_all_temp_media(current_admin: dict = Depends(get_current_admin)):
    """
    Delete all items from the temporary queue:
    - Attempts to delete items from Google Photos via web client (if valid cookies exist).
    - Removes all TempImport records from the database.
    - Removes unpromoted DriveRef records (those without a PermanentItem).
    - Evicts corresponding entries from DownloadCache.
    """
    from app.services.web_service import get_web_client

    async with get_db(write=False) as db:
        res = await db.execute(select(TempImport))
        temp_items = res.scalars().all()
        if not temp_items:
            return {"success": True, "deleted_count": 0, "message": "Temporary queue is already empty"}

        temp_ids = [t.id for t in temp_items]
        drive_ref_ids = list(set([t.drive_ref_id for t in temp_items]))
        media_keys = list(set([t.media_key for t in temp_items if t.media_key]))

    # 1. Attempt Google Photos web deletion outside of DB transaction
    gp_msg = "skipped"
    try:
        client, _ = await get_web_client()
        try:
            loop = asyncio.get_running_loop()
            reset_res = await loop.run_in_executor(None, client.reset_account, 30000)
            gp_msg = f"Cleaned {reset_res.total_deleted} items in Google Photos"
        except Exception as e:
            gp_msg = f"Google Photos cleanup failed/skipped: {e}"
        finally:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, client.close)
    except Exception as e:
        gp_msg = f"No active web session ({e})"

    # 2. Fast DB write
    async with get_db() as db:
        if media_keys:
            await db.execute(delete(DownloadCache).where(DownloadCache.media_key.in_(media_keys)))

        await db.execute(delete(TempImport).where(TempImport.id.in_(temp_ids)))

        perm_refs_res = await db.execute(
            select(PermanentItem.drive_ref_id).where(PermanentItem.drive_ref_id.in_(drive_ref_ids))
        )
        preserved_ref_ids = set(perm_refs_res.scalars().all())
        unpromoted_ref_ids = [rid for rid in drive_ref_ids if rid not in preserved_ref_ids]

        if unpromoted_ref_ids:
            await db.execute(delete(DriveRef).where(DriveRef.id.in_(unpromoted_ref_ids)))

    return {
        "success": True,
        "deleted_count": len(temp_ids),
        "message": f"Successfully deleted {len(temp_ids)} temporary item(s). ({gp_msg})",
    }


@router.post("/clear-permanent")
async def clear_all_permanent_media(current_admin: dict = Depends(get_current_admin)):
    """
    Delete all items from the permanent library:
    - Attempts to delete items from Google Photos via mobile client (if active account exists).
    - Removes all PermanentItem records from the database.
    - Removes associated DriveRef records (if not linked to TempImport).
    - Evicts corresponding entries from DownloadCache.
    """
    from app.services.mobile_service import get_mobile_client

    async with get_db(write=False) as db:
        res = await db.execute(select(PermanentItem))
        perm_items = res.scalars().all()
        if not perm_items:
            return {"success": True, "deleted_count": 0, "message": "Permanent library is already empty"}

        perm_ids = [p.id for p in perm_items]
        drive_ref_ids = list(set([p.drive_ref_id for p in perm_items]))
        media_keys = list(set([p.media_key for p in perm_items if p.media_key]))

    # 1. Attempt mobile client delete outside DB transaction
    mobile_cleaned = 0
    try:
        mobile_client, _ = await get_mobile_client(client_type="streaming")
        for mk in media_keys:
            try:
                if hasattr(mobile_client, "delete_by_media_key_async"):
                    await mobile_client.delete_by_media_key_async(mk)
                else:
                    mobile_client.delete_by_media_key(mk)
                mobile_cleaned += 1
            except Exception:
                pass
    except Exception:
        pass

    # 2. Fast DB write
    async with get_db() as db:
        if media_keys:
            await db.execute(delete(DownloadCache).where(DownloadCache.media_key.in_(media_keys)))
            await db.execute(delete(StreamCache).where(StreamCache.media_key.in_(media_keys)))

        await db.execute(delete(PermanentItem).where(PermanentItem.id.in_(perm_ids)))

        temp_refs_res = await db.execute(
            select(TempImport.drive_ref_id).where(TempImport.drive_ref_id.in_(drive_ref_ids))
        )
        preserved_ref_ids = set(temp_refs_res.scalars().all())
        dangling_ref_ids = [rid for rid in drive_ref_ids if rid not in preserved_ref_ids]

        if dangling_ref_ids:
            await db.execute(delete(DriveRef).where(DriveRef.id.in_(dangling_ref_ids)))

    return {
        "success": True,
        "deleted_count": len(perm_ids),
        "message": f"Successfully deleted {len(perm_ids)} permanent item(s). ({mobile_cleaned} removed from Google Photos)",
    }


@router.post("/clear-errors")
async def clear_all_error_media(current_admin: dict = Depends(get_current_admin)):
    """
    Delete all media files with error, unsupported, or not_found status:
    - Removes DriveRefs where file_status in ('error', 'unsupported', 'not_found') or non-ok with error_message.
    - Cleans up any linked TempImport or PermanentItem rows.
    """
    async with get_db() as db:
        stmt = select(DriveRef.id).where(
            or_(
                DriveRef.file_status.in_(["error", "unsupported", "not_found"]),
                and_(DriveRef.error_message.isnot(None), DriveRef.file_status != "ok"),
            )
        )
        res = await db.execute(stmt)
        error_ref_ids = res.scalars().all()
        if not error_ref_ids:
            return {"success": True, "deleted_count": 0, "message": "No error files to delete"}

        await db.execute(delete(TempImport).where(TempImport.drive_ref_id.in_(error_ref_ids)))
        await db.execute(delete(PermanentItem).where(PermanentItem.drive_ref_id.in_(error_ref_ids)))
        await db.execute(delete(DriveRef).where(DriveRef.id.in_(error_ref_ids)))
        await db.commit()

    return {
        "success": True,
        "deleted_count": len(error_ref_ids),
        "message": f"Successfully deleted {len(error_ref_ids)} error file(s)",
    }


@router.post("/requeue-errors")
async def requeue_all_error_media(current_admin: dict = Depends(get_current_admin)):
    """
    Reset only retryable error media files (file_status == 'error') back to queued and restart import.
    Note: Permanently dead/unworkable files ('unsupported' and 'not_found') are never re-queued.
    """
    from app.services.background_worker import auto_requeue_error_imports

    count = await auto_requeue_error_imports(force=True)
    return {
        "success": True,
        "requeued_count": count,
        "message": f"Successfully re-queued {count} error file(s)" if count > 0 else "No retryable error files found",
    }


class MediaResetRequest(BaseModel):
    confirm: str


@router.post("/reset-all")
async def reset_all_media_database(
    req: MediaResetRequest,
    current_admin: dict = Depends(get_current_admin),
):
    """
    Completely wipe all media data from database:
    - Removes all DownloadCache records.
    - Removes all PermanentItem records.
    - Removes all TempImport records.
    - Removes all DriveRef records.
    - Cleans one-shot media processing background jobs.
    Preserves admins, settings, api keys, and web/mobile sessions.
    """
    if req.confirm.strip().upper() != "RESET":
        raise HTTPException(
            status_code=400,
            detail="Confirmation text must be 'RESET' to wipe all media records.",
        )

    async with get_db() as db:
        c_cache = (await db.execute(delete(DownloadCache))).rowcount
        c_perm = (await db.execute(delete(PermanentItem))).rowcount
        c_temp = (await db.execute(delete(TempImport))).rowcount
        c_drive = (await db.execute(delete(DriveRef))).rowcount

        await db.execute(
            delete(BackgroundJob).where(
                BackgroundJob.job_type.in_(["cleanup", "share_link", "promote", "drive_import"]),
                BackgroundJob.run_every_sec.is_(None),
            )
        )
        await db.commit()

    return {
        "success": True,
        "deleted": {
            "drive_refs": c_drive,
            "temp_imports": c_temp,
            "permanent_items": c_perm,
            "cached_urls": c_cache,
        },
        "message": f"Successfully wiped all media database ({c_drive} Drive files, {c_temp} temporary items, {c_perm} permanent items, {c_cache} cached links).",
    }


@router.post("/delete")
async def delete_single_media(
    req: SingleDeleteRequest,
    current_admin: dict = Depends(get_current_admin),
):
    """Delete an individual media item from temporary, permanent storage, or dead DriveRef."""
    from app.services.mobile_service import get_mobile_client

    temp_id: int | None = None
    temp_dedup_key: str | None = None
    temp_ref_id: int | None = None
    perm_id: int | None = None
    perm_media_key: str | None = None
    perm_ref_id: int | None = None
    dead_ref_id: int | None = None
    media_keys_to_evict: list[str] = []

    async with get_db(write=False) as db:
        temp_item = None
        perm_item = None
        drive_ref = None

        if req.media_key:
            media_keys_to_evict.append(req.media_key)
            temp_stmt = select(TempImport).where(
                or_(
                    TempImport.media_key == req.media_key,
                    (TempImport.dedup_key == req.dedup_key) if req.dedup_key else False,
                )
            )
            temp_item = (await db.execute(temp_stmt)).scalars().first()

            perm_stmt = select(PermanentItem).where(PermanentItem.media_key == req.media_key)
            perm_item = (await db.execute(perm_stmt)).scalars().first()

        if not temp_item and not perm_item:
            if req.drive_ref_id:
                drive_ref = await db.get(DriveRef, req.drive_ref_id)
            elif req.drive_id:
                drive_ref = (
                    await db.execute(select(DriveRef).where(DriveRef.drive_id == req.drive_id))
                ).scalars().first()

            if drive_ref:
                temp_item = (
                    await db.execute(select(TempImport).where(TempImport.drive_ref_id == drive_ref.id))
                ).scalars().first()
                perm_item = (
                    await db.execute(select(PermanentItem).where(PermanentItem.drive_ref_id == drive_ref.id))
                ).scalars().first()

        if not temp_item and not perm_item and not drive_ref:
            raise HTTPException(status_code=404, detail="Media item or reference not found")

        if temp_item:
            temp_id = temp_item.id
            temp_dedup_key = temp_item.dedup_key
            temp_ref_id = temp_item.drive_ref_id
            if temp_item.media_key and temp_item.media_key not in media_keys_to_evict:
                media_keys_to_evict.append(temp_item.media_key)

        if perm_item:
            perm_id = perm_item.id
            perm_media_key = perm_item.media_key
            perm_ref_id = perm_item.drive_ref_id
            if perm_item.media_key and perm_item.media_key not in media_keys_to_evict:
                media_keys_to_evict.append(perm_item.media_key)

        if drive_ref and not temp_item and not perm_item:
            dead_ref_id = drive_ref.id

    # 1. External API deletions outside DB transaction
    if temp_dedup_key:
        try:
            from app.services.web_service import get_web_client
            client, _ = await get_web_client()
            try:
                if hasattr(client, "delete_permanently_async"):
                    await client.delete_permanently_async(temp_dedup_key)
            finally:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, client.close)
        except Exception:
            pass

    if perm_media_key:
        try:
            mobile_client, _ = await get_mobile_client(client_type="streaming")
            if hasattr(mobile_client, "delete_by_media_key_async"):
                await mobile_client.delete_by_media_key_async(perm_media_key)
            elif hasattr(mobile_client, "delete_by_media_key"):
                mobile_client.delete_by_media_key(perm_media_key)
        except Exception:
            pass

    # 2. Fast DB write
    async with get_db() as db:
        for mk in media_keys_to_evict:
            await db.execute(delete(DownloadCache).where(DownloadCache.media_key == mk))
            await db.execute(delete(StreamCache).where(StreamCache.media_key == mk))

        if temp_id:
            await db.execute(delete(TempImport).where(TempImport.id == temp_id))
            if temp_ref_id:
                has_perm = (
                    await db.execute(
                        select(PermanentItem.id).where(PermanentItem.drive_ref_id == temp_ref_id)
                    )
                ).scalar()
                if not has_perm:
                    await db.execute(delete(DriveRef).where(DriveRef.id == temp_ref_id))

        if perm_id:
            await db.execute(delete(PermanentItem).where(PermanentItem.id == perm_id))
            if perm_ref_id:
                has_temp = (
                    await db.execute(
                        select(TempImport.id).where(TempImport.drive_ref_id == perm_ref_id)
                    )
                ).scalar()
                if not has_temp:
                    await db.execute(delete(DriveRef).where(DriveRef.id == perm_ref_id))

        if dead_ref_id:
            await db.execute(delete(DriveRef).where(DriveRef.id == dead_ref_id))

    return {"success": True, "message": "Media item deleted successfully"}

