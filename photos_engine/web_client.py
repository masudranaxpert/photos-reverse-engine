"""
Google Photos Web Client utilizing httpcloak and reverse-engineered batchexecute RPCs.
Provides status verification, direct download generation, Drive-to-Photos import, and share link generation.
"""

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Union

import httpcloak
from .cookies.manager import SessionManager
from .cookies.store import BaseCookieStore, FileCookieStore
from .models import CookieStatus, DownloadInfo, DriveImportResult, PublicShareLink

logger = logging.getLogger(__name__)

# --- Endpoints ---
GLOBAL_URL = "https://photos.google.com"
MEDIA_URL = "https://photos.google.com/photo/{media_key}"
BATCHEXECUTE_URL = (
    "https://photos.google.com/_/PhotosUi/data/batchexecute"
    "?rpcids={rpcid}&source-path=/&f.sid={fsid}&bl={bl}&hl=en-GB&rt=c"
)

# --- Regex Patterns ---
F_SID_PATTERN = re.compile(r'"FdrFJe":"(.*?)"')
BL_PATTERN = re.compile(r'"cfb2h":"(.*?)"')
AT_PATTERN = re.compile(r'"SNlM0e":"(.*?)"')
ACCOUNT_KEY_PATTERN = re.compile(r'"oPEP7c"\s*:\s*"([^"]+@[^"]+)"')
EMAIL_PATTERN = re.compile(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
VIDEO_URL_PATTERN = re.compile(r"https://video-downloads\.googleusercontent\.com/[A-Za-z0-9_\-]+")
SHARE_LINK_PATTERN = re.compile(r'"(https://photos\.app\.goo\.gl/([^"]+))"')


def _safe_get(data: Any, *indices: int) -> Any:
    """Safely traverse nested lists/tuples by sequential indices."""
    curr = data
    for idx in indices:
        if not isinstance(curr, (list, tuple)) or idx < 0 or idx >= len(curr):
            return None
        curr = curr[idx]
    return curr


def _parse_batchexecute_body(body: str, target_rpc: str) -> Any:
    """Parse Google Photos batchexecute multi-chunk envelope for target RPC."""
    clean_body = body.strip()
    if clean_body.startswith(")]}'"):
        clean_body = clean_body[4:].strip()

    # Match chunks like: [["wrb.fr","rpcId","[\"json_payload\"]",null,null,null,"generic"]]
    for line in clean_body.splitlines():
        line = line.strip()
        if not line or not line.startswith("["):
            continue
        try:
            parsed = json.loads(line)
            if not isinstance(parsed, list):
                continue
            for chunk in parsed:
                if isinstance(chunk, list) and len(chunk) >= 3 and chunk[1] == target_rpc:
                    payload_str = chunk[2]
                    if isinstance(payload_str, str):
                        return json.loads(payload_str)
                    return payload_str
        except Exception:
            continue
    return None


class GooglePhotosWebClient:
    """
    Google Photos Web Client powered by httpcloak TLS emulation.
    Supports cookie session reuse, Google Drive import (SusGud), and direct download extraction.
    """

    def __init__(
        self,
        store: Optional[BaseCookieStore] = None,
        cookies_file: Optional[str] = None,
        session_manager: Optional[SessionManager] = None,
    ):
        if session_manager:
            self.session_manager = session_manager
        else:
            cookie_store = store or FileCookieStore(cookies_file or "cookies.txt")
            self.session_manager = SessionManager(store=cookie_store)

    def _get_session(self, session_id: str = "default") -> httpcloak.Session:
        return self.session_manager.get_session(session_id=session_id)

    def _parse_global_tokens(self, session: httpcloak.Session) -> Optional[Dict[str, str]]:
        """Fetch photos.google.com and extract tokens required for batchexecute RPCs."""
        cache_bust = f"{GLOBAL_URL}/?_t={int(time.time())}"
        try:
            resp = session.get(cache_bust, allow_redirects=False)
        except Exception as exc:
            logger.error("Failed to fetch global tokens: %s", exc)
            return None

        if resp.status_code != 200:
            return None

        body = resp.text
        f_sid = F_SID_PATTERN.search(body)
        bl = BL_PATTERN.search(body)
        at = AT_PATTERN.search(body)
        if not (f_sid and bl and at):
            return None

        return {
            "f.sid": f_sid.group(1),
            "bl": bl.group(1),
            "at": at.group(1),
        }

    def check_status(self, session_id: str = "default") -> CookieStatus:
        """
        Verify if stored cookies for session_id are active and retrieve the logged-in email.
        Persists verification status and email back to the store.
        """
        session = self._get_session(session_id)
        check_url = f"{GLOBAL_URL}/?_t={int(time.time())}"

        try:
            resp = session.get(check_url, allow_redirects=False)
        except Exception as exc:
            return CookieStatus(
                valid=False,
                session_id=session_id,
                message=f"Network error: {exc}",
            )

        final_url = str(resp.final_url or resp.url or "")
        loc_hdr = resp.headers.get("location", "")
        location = loc_hdr[0] if isinstance(loc_hdr, list) and loc_hdr else str(loc_hdr)

        is_auth_redirect = (
            "accounts.google.com" in location
            or "accounts.google.com" in final_url
            or "photos/about" in location
            or "photos/about" in final_url
        )

        if resp.status_code != 200 or is_auth_redirect:
            self.session_manager.invalidate(session_id)
            self.session_manager.store.save_session_blob(
                session_id,
                "",
                account="",
                is_valid=False,
            )
            return CookieStatus(
                valid=False,
                session_id=session_id,
                message="Cookies are expired, invalid, or redirected to login.",
            )

        account: Optional[str] = None
        match = ACCOUNT_KEY_PATTERN.search(resp.text)
        if match:
            account = match.group(1).strip()
        else:
            email_match = EMAIL_PATTERN.search(resp.text)
            if email_match:
                account = email_match.group(1).strip()

        # Persist valid state and fresh session blob
        self.session_manager.debounced_sync(
            session_id,
            session,
            account=account,
            is_valid=True,
            force=True,
        )

        return CookieStatus(
            valid=True,
            session_id=session_id,
            account=account,
            message=f"Cookies are valid (Account: {account or 'unknown'}).",
        )

    def get_download_url(self, media_key: str, session_id: str = "default") -> DownloadInfo:
        """
        Extract direct video download URL for a Google Photos media key.
        Tries direct page scrape first, falling back to VrseUb (GetItemInfo) RPC.
        """
        if not media_key:
            raise ValueError("media_key cannot be empty")

        session = self._get_session(session_id)

        # 1. Try direct media page scrape
        try:
            resp = session.get(MEDIA_URL.format(media_key=media_key), allow_redirects=False)
            if resp.status_code == 200:
                match = VIDEO_URL_PATTERN.search(resp.text)
                if match:
                    self.session_manager.debounced_sync(session_id, session)
                    return DownloadInfo(
                        media_key=media_key,
                        download_url=match.group(0),
                    )
        except Exception as exc:
            logger.debug("Direct page fetch failed for '%s': %s", media_key, exc)

        # 2. Fall back to VrseUb batchexecute RPC
        tokens = self._parse_global_tokens(session)
        if not tokens:
            raise RuntimeError("Failed to obtain Google Photos global session tokens")

        rpc_id = "VrseUb"
        url = BATCHEXECUTE_URL.format(
            rpcid=rpc_id,
            fsid=tokens["f.sid"],
            bl=tokens["bl"],
        )

        inner_data = json.dumps([media_key, None, None, None, None])
        f_req = json.dumps([[[rpc_id, inner_data, None, "1"]]])

        resp = session.post(
            url,
            data={"f.req": f_req, "at": tokens["at"]},
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        )

        if resp.status_code != 200:
            raise RuntimeError(f"VrseUb request failed with HTTP {resp.status_code}")

        data = _parse_batchexecute_body(resp.text, rpc_id)
        if not data:
            raise RuntimeError("Failed to parse VrseUb item info response")

        dedup_key = _safe_get(data, 0, 3) or ""
        download_url = _safe_get(data, 1) or ""
        if not download_url:
            download_url = _safe_get(data, 7) or ""

        self.session_manager.debounced_sync(session_id, session)
        return DownloadInfo(
            media_key=media_key,
            dedup_key=str(dedup_key),
            download_url=str(download_url),
        )

    def import_from_drive(
        self,
        drive_file_id: str,
        mime_type: str = "video/*",
        session_id: str = "default",
        cleanup: bool = False,
    ) -> DriveImportResult:
        """
        Import a Google Drive file into Google Photos using SusGud batchexecute RPC.
        Automatically resolves direct download URL via VrseUb, with optional auto-cleanup.
        """
        if not drive_file_id:
            raise ValueError("drive_file_id cannot be empty")

        session = self._get_session(session_id)
        tokens = self._parse_global_tokens(session)
        if not tokens:
            raise RuntimeError("Failed to obtain Google Photos global session tokens")

        rpc_id = "SusGud"
        url = BATCHEXECUTE_URL.format(
            rpcid=rpc_id,
            fsid=tokens["f.sid"],
            bl=tokens["bl"],
        )

        # Payload matching SusGud format: [[[drive_file_id, mime_type]]]
        inner_data = json.dumps([[[drive_file_id, mime_type]]])
        f_req = json.dumps([[[rpc_id, inner_data, None, "1"]]])

        resp = session.post(
            url,
            data={"f.req": f_req, "at": tokens["at"]},
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        )

        if resp.status_code != 200:
            raise RuntimeError(f"SusGud import request failed with HTTP {resp.status_code}")

        data = _parse_batchexecute_body(resp.text, rpc_id)
        if not data:
            raise RuntimeError("Failed to parse SusGud import response from Google Photos")

        # Response format: [[driveKey, [mediaKey, ..., dedupKey]]]
        items = _safe_get(data, 0)
        if not isinstance(items, list) or not items:
            raise RuntimeError(f"No imported media items returned in response: {data}")

        first_item = items[0]
        media_key = _safe_get(first_item, 1, 0) or ""
        dedup_key = _safe_get(first_item, 1, 3) or ""

        if not media_key:
            raise RuntimeError(f"media_key missing in import response: {first_item}")

        # Automatically fetch download URL using VrseUb
        download_url: Optional[str] = None
        try:
            info = self.get_download_url(media_key=media_key, session_id=session_id)
            download_url = info.download_url
            if not dedup_key:
                dedup_key = info.dedup_key
        except Exception as exc:
            logger.warning("Failed to automatically get download URL for imported media: %s", exc)

        # Optional cleanup
        if cleanup and dedup_key:
            try:
                self.delete_media(dedup_key=dedup_key, session_id=session_id, empty_trash=True)
            except Exception as exc:
                logger.warning("Post-import cleanup failed for dedup_key '%s': %s", dedup_key, exc)

        self.session_manager.debounced_sync(session_id, session)
        return DriveImportResult(
            drive_file_id=drive_file_id,
            media_key=str(media_key),
            dedup_key=str(dedup_key),
            download_url=download_url,
        )

    def create_share_link(self, media_key: str, session_id: str = "default") -> PublicShareLink:
        """Create a public photos.app.goo.gl link for a media key using SFKp8c RPC."""
        if not media_key:
            raise ValueError("media_key cannot be empty")

        session = self._get_session(session_id)
        tokens = self._parse_global_tokens(session)
        if not tokens:
            raise RuntimeError("Failed to obtain Google Photos global session tokens")

        rpc_id = "SFKp8c"
        url = BATCHEXECUTE_URL.format(
            rpcid=rpc_id,
            fsid=tokens["f.sid"],
            bl=tokens["bl"],
        )

        f_req = (
            f'[[["SFKp8c","[null,null,[null,1,null,null,1,null,[[[1,1],0],'
            f'[[1,2],0],[[2,1],1],[[2,2],1],[[3,1],1]]],[2,null,'
            f'[[[\\"{media_key}\\"]]],null,null,null,[1],0,null,null,null,'
            f'null,null,0],null,null,null,null,[1,2,3,5,6]]",null,'
            f'"generic"]]]'
        )

        resp = session.post(
            url,
            data={"f.req": f_req, "at": tokens["at"]},
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        )

        if resp.status_code != 200:
            raise RuntimeError(f"SFKp8c request failed with HTTP {resp.status_code}")

        match = SHARE_LINK_PATTERN.search(resp.text)
        if not match:
            raise RuntimeError("Could not find share link in response body")

        share_url = match.group(1).replace("\\", "")
        short_id = match.group(2).replace("\\", "")

        self.session_manager.debounced_sync(session_id, session)
        return PublicShareLink(
            share_url=share_url,
            envelope_key=short_id,
            auth_key="",
            media_keys=[media_key],
        )

    def delete_media(
        self,
        dedup_key: str,
        session_id: str = "default",
        empty_trash: bool = True,
    ) -> bool:
        """Move media to trash (XwAOJf) and optionally empty trash (vzCSKc)."""
        if not dedup_key:
            return False

        session = self._get_session(session_id)
        tokens = self._parse_global_tokens(session)
        if not tokens:
            raise RuntimeError("Failed to obtain Google Photos global session tokens")

        # 1. Move to Trash (XwAOJf)
        url_trash = BATCHEXECUTE_URL.format(
            rpcid="XwAOJf",
            fsid=tokens["f.sid"],
            bl=tokens["bl"],
        )
        inner_trash = json.dumps([None, 1, [dedup_key], 3])
        f_req_trash = json.dumps([[["XwAOJf", inner_trash, None, "1"]]])

        resp = session.post(
            url_trash,
            data={"f.req": f_req_trash, "at": tokens["at"]},
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        )
        if resp.status_code != 200:
            return False

        # 2. Empty Trash (vzCSKc)
        if empty_trash:
            url_empty = BATCHEXECUTE_URL.format(
                rpcid="vzCSKc",
                fsid=tokens["f.sid"],
                bl=tokens["bl"],
            )
            inner_empty = json.dumps([[], None, 1])
            f_req_empty = json.dumps([[["vzCSKc", inner_empty, None, "1"]]])
            session.post(
                url_empty,
                data={"f.req": f_req_empty, "at": tokens["at"]},
                headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            )

        self.session_manager.debounced_sync(session_id, session)
        return True

    def close(self) -> None:
        """Safely close all cached sessions and the underlying store."""
        self.session_manager.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
