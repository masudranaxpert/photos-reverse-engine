"""
Google Drive v3 API service for file metadata pre-fetching.
Fetches exact filename, file_size, and accessibility before importing to Google Photos.
"""
import asyncio
from dataclasses import dataclass
import json
import logging
import time
from typing import Optional
import urllib.error
import urllib.parse
import urllib.request

from sqlalchemy import select

from app.database import get_db
from app.models import SystemSetting

logger = logging.getLogger("photos_engine.drive_api")

# In-memory API key cache: (key_str, monotonic_expiry)
_api_key_cache: tuple[Optional[str], float] = (None, 0.0)


@dataclass
class DriveFileMetadata:
    drive_id: str
    filename: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    status: str = "ok"  # 'ok' | 'not_found' | 'error'
    error_message: Optional[str] = None


async def get_drive_api_key() -> Optional[str]:
    """Retrieve Google Drive API key with 60s in-memory cache and read-only query."""
    global _api_key_cache
    key, exp = _api_key_cache
    if key is not None and time.monotonic() < exp:
        return key

    try:
        async with get_db(write=False) as db:
            stmt = select(SystemSetting).where(SystemSetting.key == "google_drive_api_key")
            res = await db.execute(stmt)
            setting = res.scalar_one_or_none()
            if setting and setting.value and setting.value.strip():
                clean = setting.value.strip()
                _api_key_cache = (clean, time.monotonic() + 60.0)
                return clean
    except Exception as exc:
        logger.error("[drive_api] Failed to read API key from DB: %s", exc)

    return None


async def set_drive_api_key(api_key: str) -> None:
    """Save updated Google Drive API key to system_settings."""
    global _api_key_cache
    _api_key_cache = (None, 0.0)
    clean_key = api_key.strip()
    async with get_db() as db:
        stmt = select(SystemSetting).where(SystemSetting.key == "google_drive_api_key")
        res = await db.execute(stmt)
        setting = res.scalar_one_or_none()
        if setting:
            setting.value = clean_key
        else:
            setting = SystemSetting(
                key="google_drive_api_key",
                value=clean_key,
                description="Google Drive v3 API Key for file metadata validation",
            )
            db.add(setting)


async def get_drive_file_metadata(drive_id: str) -> DriveFileMetadata:
    """
    Fetch file metadata (name, size, mimeType) directly from Google Drive v3 API.
    Returns status='not_found' if file does not exist, is in trash, or inaccessible.
    Returns status='error' if API key is not configured or network error occurs.
    """
    clean_id = drive_id.strip()
    api_key = await get_drive_api_key()
    if not api_key:
        logger.warning("[drive_api] Drive API key is not set in database.")
        return DriveFileMetadata(
            drive_id=clean_id,
            status="error",
            error_message="Google Drive API key is not configured in Admin Settings. Please configure it first.",
        )

    url = f"https://www.googleapis.com/drive/v3/files/{clean_id}"
    params = {
        "fields": "id,name,size,mimeType,trashed",
        "key": api_key,
        "supportsAllDrives": "true",
    }
    query_str = urllib.parse.urlencode(params)
    target_url = f"{url}?{query_str}"
    req = urllib.request.Request(target_url, headers={"User-Agent": "PhotosEngine/1.0"})

    def _fetch():
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                return response.status, json.loads(response.read().decode("utf-8")), None
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(body)
            except Exception:
                err_json = {}
            return e.code, err_json, body
        except Exception as e:
            return 0, {}, str(e)

    try:
        status_code, data, raw_err = await asyncio.to_thread(_fetch)

        if status_code == 404:
            logger.warning("[drive_api] File %s not found (HTTP 404)", clean_id)
            return DriveFileMetadata(
                drive_id=clean_id,
                status="not_found",
                error_message="File not found or inaccessible in Google Drive.",
            )

        if status_code != 200:
            err_msg = data.get("error", {}).get("message", (raw_err or "")[:120])
            logger.warning("[drive_api] Drive API HTTP %d for %s: %s", status_code, clean_id, err_msg)

            if "notFound" in str(data) or status_code in (400, 403, 404):
                return DriveFileMetadata(
                    drive_id=clean_id,
                    status="not_found",
                    error_message=f"Google Drive file inaccessible or not found: {err_msg}",
                )
            return DriveFileMetadata(
                drive_id=clean_id,
                status="error",
                error_message=f"Drive API error ({status_code}): {err_msg}",
            )

        if data.get("trashed"):
            logger.warning("[drive_api] File %s is trashed", clean_id)
            return DriveFileMetadata(
                drive_id=clean_id,
                status="not_found",
                error_message="File is in Google Drive trash.",
            )

        raw_size = data.get("size")
        file_size = int(raw_size) if raw_size is not None else None
        filename = data.get("name") or None
        mime_type = data.get("mimeType") or "video/*"

        logger.info(
            "[drive_api] Fetched metadata for %s: name='%s' size=%s mime=%s",
            clean_id, filename, file_size, mime_type,
        )

        return DriveFileMetadata(
            drive_id=clean_id,
            filename=filename,
            file_size=file_size,
            mime_type=mime_type,
            status="ok",
        )

    except Exception as exc:
        logger.error("[drive_api] Request failed for %s: %s", clean_id, exc)
        return DriveFileMetadata(
            drive_id=clean_id,
            status="error",
            error_message=f"Network error querying Google Drive API: {exc}",
        )
