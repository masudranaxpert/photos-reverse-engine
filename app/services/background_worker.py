"""Background worker and scheduled task handlers."""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models import BackgroundJob, DriveRef, PermanentItem, SystemSetting, TempImport
from app.services.mobile_service import extract_email_from_auth_data, get_mobile_client
from app.services.web_service import get_web_client

logger = logging.getLogger("photos_engine.worker")


def _utc_now() -> datetime:
    """Return naive UTC datetime for SQLite compatibility."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def run_cookies_check_logic() -> dict:
    """Validate web sessions via quota ping, rotate cookies in blob, and update status."""
    from app.models import WebSession
    from app.services.web_service import sync_session_blob
    from photos_engine import NativeWebClient

    async with get_db(write=False) as db:
        res = await db.execute(select(WebSession))
        sessions = res.scalars().all()

    results = {}
    for sess in sessions:
        client = None
        try:
            client = NativeWebClient.from_blob(sess.session_blob)
            quota = await asyncio.get_event_loop().run_in_executor(None, client.get_storage_quota)
            await sync_session_blob(sess.session_id, client)

            results[sess.session_id] = {"valid": True, "account": sess.account_email, "usage": quota.usage_text}
            logger.info(
                "[cookies_check] Session '%s' OK — PSIDTS rotated & blob synced. Quota: %s",
                sess.session_id, quota.usage_text,
            )
            async with get_db() as db2:
                await db2.execute(
                    update(WebSession)
                    .where(WebSession.session_id == sess.session_id)
                    .values(is_active=True)
                )
            from app.services.notice_service import resolve_notice
            await resolve_notice(f"cookies_{sess.session_id}")

        except Exception as exc:
            err_msg = str(exc)
            is_auth_expired = any(k in err_msg.lower() for k in (
                "302", "login", "expired", "unauthorized",
                "redirected to login", "returned status 302",
            ))
            results[sess.session_id] = {"valid": False, "error": err_msg}

            if is_auth_expired:
                logger.warning("[cookies_check] Session '%s' EXPIRED: %s", sess.session_id, err_msg)
                async with get_db() as db2:
                    await db2.execute(
                        update(WebSession)
                        .where(WebSession.session_id == sess.session_id)
                        .values(is_active=False)
                    )
                from app.services.web_service import invalidate_session_cache
                invalidate_session_cache()
                from app.services.notice_service import record_notice
                await record_notice(
                    title="Instant Session Expired",
                    message=f"Instant Session '{sess.name}' ({sess.account_email or 'No email'}) cookies expired. Please export fresh cookies and update in dashboard.",
                    level="error",
                    source=f"cookies_{sess.session_id}",
                )
            else:
                logger.error(
                    "[cookies_check] Session '%s' transient error (session kept alive): %s",
                    sess.session_id, err_msg,
                )
        finally:
            if client:
                try:
                    client.close()
                except Exception:
                    pass

    global _web_cookies_ok
    any_valid = any(v.get("valid") for v in results.values())
    if any_valid:
        if not _web_cookies_ok:
            logger.info("[cookies_check] Valid session restored — import gate re-opened.")
            await mark_cookies_valid_and_resume()
        else:
            _web_cookies_ok = True
    elif sessions:
        if _web_cookies_ok:
            logger.warning("[cookies_check] All sessions invalid — import gate closed until cookies updated.")
        _web_cookies_ok = False
    else:
        _web_cookies_ok = True

    return {"sessions": results}


async def run_cache_cleanup_logic() -> dict:
    """Delete expired download_cache entries."""
    from app.services.cache_service import cleanup_expired_cache
    deleted = await cleanup_expired_cache()
    return {"deleted": deleted}


async def run_stream_cache_cleanup_logic() -> dict:
    """Delete expired stream_cache entries."""
    from app.services.stream_cache_service import cleanup_expired_stream_cache
    deleted = await cleanup_expired_stream_cache()
    return {"deleted": deleted}


async def run_daily_cleanup_logic() -> dict:
    """Purge temporary imports older than 24h from Google Photos and DB."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
    freed = 0
    deleted_count = 0

    client = None
    try:
        client, _ = await get_web_client()
    except Exception as exc:
        logger.warning("[daily_cleanup] Web client unavailable (cookies expired/offline): %s. Halting daily cleanup.", exc)
        return {"deleted_count": 0, "freed_bytes": 0, "skipped": "cookies_offline"}

    async with get_db() as db:
        stmt = (
            select(TempImport, DriveRef.file_size)
            .outerjoin(DriveRef, TempImport.drive_ref_id == DriveRef.id)
            .where(TempImport.imported_at < cutoff)
            .order_by(TempImport.imported_at.asc())
            .limit(200)
        )
        res = await db.execute(stmt)
        stale_items = res.all()

    deleted_ids = []
    try:
        for item, ref_size in stale_items:
            delete_success = False
            cookie_expired = False
            last_err = None

            if item.dedup_key:
                for attempt in range(1, 4):
                    try:
                        if hasattr(client, "delete_permanently_async"):
                            res = await client.delete_permanently_async(item.dedup_key)
                        elif hasattr(client, "delete_permanently"):
                            res = client.delete_permanently(item.dedup_key)
                        elif hasattr(client, "delete_by_dedup_key"):
                            res = client.delete_by_dedup_key(item.dedup_key)
                        else:
                            res = True
                        delete_success = bool(res)
                        break
                    except Exception as exc:
                        last_err = exc
                        msg = str(exc).lower()
                        if any(k in msg for k in ("302", "login", "expired", "unauthorized", "redirected to login", "session is expired", "cookies are expired", "cookies are invalid")):
                            cookie_expired = True
                            break
                        if attempt < 3:
                            await asyncio.sleep(0.5)

            if cookie_expired:
                logger.error("[daily_cleanup] Active cookies expired while deleting temp item %s. Halting cleanup until cookies updated.", item.media_key)
                break

            if delete_success or not item.dedup_key:
                freed += ref_size or (100 * 1024 * 1024)
                deleted_ids.append(item.id)
                deleted_count += 1
            else:
                logger.warning("[daily_cleanup] Failed to delete temp item %s from Google Photos after 3 retries (%s). Purging from DB.", item.media_key, last_err)
                deleted_ids.append(item.id)
    finally:
        if client:
            client.close()

    if deleted_ids:
        from sqlalchemy import delete as sa_delete
        async with get_db() as db:
            await db.execute(sa_delete(TempImport).where(TempImport.id.in_(deleted_ids)))

    return {"deleted_count": deleted_count, "freed_bytes": freed}


async def trigger_pipeline_sweep() -> None:
    """Trigger recurring pipeline_sweep immediately."""
    try:
        from app.services.scheduler import trigger_job_now
        triggered = trigger_job_now("pipeline_sweep")
        if triggered:
            return
    except Exception:
        pass

    async with get_db() as db:
        await db.execute(
            update(BackgroundJob)
            .where(BackgroundJob.job_type == "pipeline_sweep")
            .values(status="pending", next_run_at=_utc_now())
        )


async def enqueue_share_link_job() -> int:
    """Trigger pipeline_sweep to process new imports."""
    await trigger_pipeline_sweep()
    return 0


_import_sem: asyncio.Semaphore = asyncio.Semaphore(1)
_import_sem_capacity: int = 1
_promote_lock: asyncio.Lock = asyncio.Lock()
_pipeline_sweep_lock: asyncio.Lock = asyncio.Lock()
_web_cookies_ok: bool = True
_active_import_ref_ids: set[int] = set()


async def auto_requeue_error_imports(force: bool = False) -> int:
    """Requeue retryable error imports."""
    global _web_cookies_ok
    if not _web_cookies_ok and not force:
        logger.debug("[auto_requeue] Web cookies invalid — skipping auto-requeue until cookies restored.")
        return 0

    async with get_db() as db:
        stmt = (
            select(DriveRef)
            .outerjoin(PermanentItem, PermanentItem.drive_ref_id == DriveRef.id)
            .outerjoin(TempImport, TempImport.drive_ref_id == DriveRef.id)
            .where(
                or_(
                    DriveRef.file_status == "error",
                    and_(
                        DriveRef.file_status.notin_(["unsupported", "not_found"]),
                        PermanentItem.id.is_(None),
                        TempImport.id.is_(None),
                    ),
                )
            )
        )
        res = await db.execute(stmt)
        error_refs = res.scalars().all()
        if not error_refs:
            return 0

        requeued_items = []
        for r in error_refs:
            if r.id in _active_import_ref_ids:
                continue
            r.file_status = "queued"
            r.error_message = None
            requeued_items.append({
                "id": r.id,
                "drive_id": r.drive_id,
                "file_size": r.file_size,
                "filename": r.filename,
            })
        await db.commit()

    for item in requeued_items:
        await queue_drive_import(
            drive_ref_id=item["id"],
            drive_id=item["drive_id"],
            file_size=item["file_size"],
            filename=item["filename"],
        )
    return len(requeued_items)


async def mark_cookies_valid_and_resume() -> int:
    """Open import gate and requeue deferred imports."""
    global _web_cookies_ok
    was_down = not _web_cookies_ok
    _web_cookies_ok = True
    if was_down:
        logger.info("[cookie_gate] Cookies valid — import gate OPENED. Auto-requeueing deferred files...")
        count = await auto_requeue_error_imports()
        if count > 0:
            logger.info("[cookie_gate] Auto-requeued %d deferred/error file(s).", count)
        return count
    return 0


async def _get_import_concurrency() -> int:
    """Read max_concurrent_imports from settings, clamped to [1, 150]."""
    try:
        async with get_db(write=False) as db:
            row = await db.get(SystemSetting, "max_concurrent_imports")
            if row:
                # Hard ceiling: 150 — beyond this Google starts 429-ing.
                return max(1, min(150, int(row.value)))
    except Exception:
        pass
    return 1


async def _refresh_import_semaphore() -> asyncio.Semaphore:
    """Resize import semaphore if max_concurrent_imports changed."""
    global _import_sem, _import_sem_capacity
    desired = await _get_import_concurrency()
    if desired != _import_sem_capacity:
        _import_sem = asyncio.Semaphore(desired)
        _import_sem_capacity = desired
        logger.info("[drive_import] Import semaphore resized to %d concurrent slots", desired)
    return _import_sem


async def queue_drive_import(
    drive_ref_id: int,
    drive_id: str,
    mime_type: str = "video/*",
    file_size: Optional[int] = None,
    filename: Optional[str] = None,
) -> None:
    """Queue background Drive import into Google Photos."""
    if drive_ref_id in _active_import_ref_ids:
        logger.debug("[drive_import] Ref ID %d already active — skipping duplicate queue.", drive_ref_id)
        return
    _active_import_ref_ids.add(drive_ref_id)
    asyncio.create_task(
        _execute_drive_import_async(drive_ref_id, drive_id, mime_type, file_size, filename)
    )


async def _execute_drive_import_async(
    drive_ref_id: int,
    drive_id: str,
    mime_type: str = "video/*",
    file_size: Optional[int] = None,
    filename: Optional[str] = None,
) -> bool:
    """Import Drive file to Photos, handle quota limits, and record TempImport."""
    from app.services.web_service import get_web_client, sync_session_blob
    from app.services.quota_service import free_space_from_temp
    from app.services.notice_service import record_notice
    global _web_cookies_ok
    sem_held = False

    try:
        if not _web_cookies_ok:
            logger.warning(
                "[drive_import] Import gate CLOSED (cookies invalid) — skipping drive_id=%s. Will retry when cookies restored.",
                drive_id,
            )
            async with get_db() as db:
                await db.execute(
                    update(DriveRef)
                    .where(DriveRef.id == drive_ref_id)
                    .values(file_status="error", error_message="Cookies expired — import deferred")
                )
            return False

        sem = await _refresh_import_semaphore()
        logger.info("[drive_import] Waiting for import slot (cap=%d): drive_id=%s (ref_id=%d)", _import_sem_capacity, drive_id, drive_ref_id)
        await sem.acquire()
        sem_held = True

        media_key_out: str | None = None
        dedup_key_out: str | None = None

        if not _web_cookies_ok:
            logger.warning(
                "[drive_import] Import gate closed while waiting in slot — deferring drive_id=%s (ref_id=%d)",
                drive_id, drive_ref_id,
            )
            async with get_db() as db:
                await db.execute(
                    update(DriveRef)
                    .where(DriveRef.id == drive_ref_id)
                    .values(file_status="error", error_message="Cookies expired — import deferred")
                )
            return False

        logger.info("[drive_import] Slot acquired — starting import for drive_id=%s (ref_id=%d)", drive_id, drive_ref_id)
        client = None
        session_id = None
        try:
            client, session_id = await get_web_client()

            try:
                # Quota check is a sync blocking call — offload to executor.
                loop = asyncio.get_event_loop()
                quota = await loop.run_in_executor(None, client.get_storage_quota)
                available_bytes = quota.total_bytes - quota.used_bytes
                needed_bytes = file_size or (2 * 1024 * 1024 * 1024)
                if available_bytes < needed_bytes:
                    logger.info("[drive_import] Staging storage low (%d MB free, need %d MB). Triggering sweep...", available_bytes // (1024 * 1024), needed_bytes // (1024 * 1024))
                    await trigger_pipeline_sweep()
            except Exception as q_err:
                logger.debug("[drive_import] Pre-import quota check: %s", q_err)

            import_res = None
            try:
                import_res = await client.import_from_drive_async(
                    drive_file_id=drive_id,
                    mime_type=mime_type or "video/*",
                    cleanup=False,
                )
                await sync_session_blob(session_id, client)
            except Exception as exc:
                internal_msg = str(exc)
                if any(k in internal_msg.lower() for k in ("quota", "storage", "full", "space", "limit")):
                    needed_bytes = file_size or (500 * 1024 * 1024)
                    logger.warning(
                        "[drive_import] Quota limit encountered for drive_id=%s (size=%s). Sweeping pipeline...",
                        drive_id, file_size,
                    )
                    await run_pipeline_sweep_logic()
                    try:
                        import_res = await client.import_from_drive_async(
                            drive_file_id=drive_id,
                            mime_type=mime_type or "video/*",
                            cleanup=False,
                        )
                        await sync_session_blob(session_id, client)
                    except Exception as retry_exc:
                        freed = await free_space_from_temp(needed_bytes, client)
                        if freed > 0:
                            import_res = await client.import_from_drive_async(
                                drive_file_id=drive_id,
                                mime_type=mime_type or "video/*",
                                cleanup=False,
                            )
                            await sync_session_blob(session_id, client)
                        else:
                            raise retry_exc
                else:
                    raise

            media_key_out = import_res.media_key
            dedup_key_out = import_res.dedup_key

            logger.info(
                "[drive_import] Completed drive_id=%s media_key=%s dedup_key=%s",
                drive_id, media_key_out, dedup_key_out,
            )

            async with get_db() as db:
                await db.execute(
                    update(DriveRef)
                    .where(DriveRef.id == drive_ref_id)
                    .values(file_status="ok", error_message=None)
                )
                existing_temp = (
                    await db.execute(select(TempImport).where(TempImport.drive_ref_id == drive_ref_id))
                ).scalar_one_or_none()
                if not existing_temp:
                    db.add(TempImport(
                        drive_ref_id=drive_ref_id,
                        media_key=media_key_out,
                        dedup_key=dedup_key_out or None,
                    ))

        except Exception as exc:
            logger.error("[drive_import] Background import failed for drive_id=%s: %s", drive_id, exc)
            internal_msg = str(exc)
            file_desc = filename or drive_id

            if any(k in internal_msg.lower() for k in ("503", "302", "service temporarily unavailable", "cookies are expired", "session is expired", "instant session", "redirected to login", "unauthorized")):
                _web_cookies_ok = False
                logger.warning(
                    "[drive_import] Cookies/service offline for drive_id=%s — closing import gate, marking error.",
                    drive_id,
                )
                async with get_db() as db:
                    await db.execute(
                        update(DriveRef)
                        .where(DriveRef.id == drive_ref_id)
                        .values(file_status="error", error_message=internal_msg)
                    )
                return False
            if any(k in internal_msg.lower() for k in ("quota", "storage", "full", "space", "limit")):
                await record_notice(
                    title="Google Photos Storage Full",
                    message=f"Storage quota exceeded while importing '{file_desc}'. Free up space or empty trash to resume.",
                    level="error",
                    source="quota",
                )
                file_status_val = "error"
            elif "status 3" in internal_msg or "unsupported" in internal_msg.lower():
                await record_notice(
                    title="Unsupported File Format",
                    message=f"Google Photos rejected '{file_desc}'. Only photos and videos can be imported (archives like .rar/.zip are not supported).",
                    level="warning",
                    source="format_rejected",
                )
                file_status_val = "unsupported"
            else:
                file_status_val = "error"

            async with get_db() as db:
                await db.execute(
                    update(DriveRef)
                    .where(DriveRef.id == drive_ref_id)
                    .values(file_status=file_status_val, error_message=internal_msg)
                )
            return False
        finally:
            if client:
                client.close()

        if media_key_out:
            try:
                # Decouple: schedule a sweep run via scheduler, not a direct recursive call.
                await trigger_pipeline_sweep()
            except Exception as sw_err:
                logger.warning("[drive_import] Post-import sweep trigger warning: %s", sw_err)

        return True
    finally:
        if sem_held:
            sem.release()
        _active_import_ref_ids.discard(drive_ref_id)


async def enqueue_promote_job() -> int:
    """Trigger pipeline_sweep to promote items without creating duplicate job rows."""
    await trigger_pipeline_sweep()
    return 0


async def run_pipeline_sweep_logic() -> dict:
    """Sweep queued drive imports, generate share links, and promote ready items with single-flight lock."""
    if _pipeline_sweep_lock.locked():
        logger.debug("[pipeline_sweep] Sweep already in progress — skipping concurrent execution.")
        return {"status": "skipped", "reason": "sweep_already_running"}

    async with _pipeline_sweep_lock:
        return await _run_pipeline_sweep_logic_internal()


async def _run_pipeline_sweep_logic_internal() -> dict:
    """Internal implementation for pipeline sweep."""
    async with get_db(write=False) as db:
        queued_refs = (await db.execute(
            select(DriveRef).where(DriveRef.file_status == "queued").limit(5)
        )).scalars().all()

    for qref in queued_refs:
        try:
            await queue_drive_import(
                drive_ref_id=qref.id,
                drive_id=qref.drive_id,
                mime_type="video/*",
                file_size=qref.file_size,
                filename=qref.filename,
            )
        except Exception as exc:
            logger.warning("[sweep/drive_import] Error queueing ref_id=%d: %s", qref.id, exc)

    async with get_db(write=False) as db:
        pending_share = (await db.execute(
            select(TempImport).where(TempImport.share_url.is_(None)).limit(20)
        )).scalars().all()
    generated = 0
    if pending_share:
        client = None
        try:
            client, _ = await get_web_client()
            for it in pending_share:
                try:
                    link = await client.create_share_link_async(it.media_key)
                    async with get_db() as db:
                        await db.execute(
                            update(TempImport)
                            .where(TempImport.id == it.id)
                            .values(share_url=link.share_url)
                        )
                    generated += 1
                    logger.info("[sweep/share_link] Generated share_url for media_key=%s", it.media_key)
                except Exception as exc:
                    logger.warning("[sweep/share_link] Share link pending/not ready for media_key=%s: %s", it.media_key, exc)
        except Exception as exc:
            logger.error("[sweep/share_link] Client session error: %s", exc)
        finally:
            if client:
                client.close()

    now = _utc_now()
    async with get_db(write=False) as db:
        pending_promote = (await db.execute(
            select(TempImport).where(
                TempImport.share_url.isnot(None),
                or_(TempImport.promote_after.is_(None), TempImport.promote_after <= now),
            ).limit(20)
        )).scalars().all()
    promoted = 0
    if pending_promote:
        try:
            mobile_client, mobile_account = await get_mobile_client()
            for item in pending_promote:
                try:
                    result = await mobile_client.import_share_url_async(item.share_url)
                    import_result = result.get("import_result") if isinstance(result, dict) else result
                    status = (
                        import_result.get("status") if isinstance(import_result, dict)
                        else getattr(import_result, "status", None)
                    )
                    new_keys = (
                        import_result.get("new_keys") if isinstance(import_result, dict)
                        else getattr(import_result, "new_keys", None)
                        or getattr(import_result, "new_media_keys", None)
                    ) or []

                    if status == 1:
                        retry_at = _utc_now() + timedelta(minutes=3)
                        async with get_db() as db:
                            await db.execute(
                                update(TempImport)
                                .where(TempImport.id == item.id)
                                .values(promote_after=retry_at)
                            )
                        logger.info(
                            "[sweep/promote] media_key=%s still transcoding, retry after %s",
                            item.media_key, retry_at.strftime("%H:%M:%S"),
                        )
                        continue

                    if status == 2:
                        permanent_key = new_keys[0] if new_keys else item.media_key
                        async with _promote_lock:
                            try:
                                async with get_db() as db:
                                    db.add(PermanentItem(
                                        drive_ref_id=item.drive_ref_id,
                                        media_key=permanent_key,
                                        email=mobile_account.email,
                                    ))
                                    await db.execute(delete(TempImport).where(TempImport.id == item.id))
                            except IntegrityError:
                                logger.info(
                                    "[sweep/promote] media_key=%s already promoted by concurrent sweep — removing temp row",
                                    item.media_key,
                                )
                                async with get_db() as db:
                                    await db.execute(delete(TempImport).where(TempImport.id == item.id))
                                continue

                        try:
                            web_client, _ = await get_web_client()
                            try:
                                if item.dedup_key:
                                    await web_client.delete_permanently_async(item.dedup_key)
                                logger.info("[sweep/promote] Cleaned up temporary item media_key=%s (dedup=%s) from web account", item.media_key, item.dedup_key)
                            finally:
                                web_client.close()
                        except Exception as exc:
                            logger.warning("[sweep/promote] Non-fatal temp cleanup warning: %s", exc)

                        promoted += 1
                        logger.info(
                            "[sweep/promote] Promoted media_key=%s -> permanent_key=%s",
                            item.media_key, permanent_key,
                        )
                        continue

                    retry_at = _utc_now() + timedelta(minutes=5)
                    async with get_db() as db:
                        await db.execute(
                            update(TempImport)
                            .where(TempImport.id == item.id)
                            .values(promote_after=retry_at)
                        )
                    logger.warning(
                        "[sweep/promote] Unexpected status=%s for media_key=%s, will retry after %s",
                        status, item.media_key, retry_at.strftime("%H:%M:%S"),
                    )
                except Exception as exc:
                    logger.warning("[sweep/promote] Failed for media_key=%s: %s", item.media_key, exc)
        except Exception as exc:
            logger.warning("[sweep/promote] Mobile client error: %s", exc)

    return {"share_generated": generated, "promoted": promoted}
