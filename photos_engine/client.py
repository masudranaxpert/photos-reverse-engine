"""
Native Python bindings for Google Photos Mobile Client (GPMC), powered directly by the Go core DLL.
"""

import ctypes
import json
import os
import platform
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .models import (
    CookieStatus,
    DownloadInfo,
    DriveImportResult,
    ExistResult,
    PublicShareLink,
    SaveResult,
    ShareInfo,
)
from .scraper import scrape_share_url


def _get_lib_path() -> str:
    """Get the path to the shared library based on platform, matching httpcloak style."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    else:
        arch = machine

    if system == "darwin":
        ext = ".dylib"
        os_name = "darwin"
    elif system == "windows":
        ext = ".dll"
        os_name = "windows"
    else:
        ext = ".so"
        os_name = "linux"

    lib_name = f"libphotos_engine-{os_name}-{arch}{ext}"

    search_paths = [
        Path(__file__).parent / "lib" / lib_name,
        Path(__file__).parent / lib_name,
        Path(__file__).parent.parent / "lib" / lib_name,
        Path.cwd() / "lib" / lib_name,
    ]

    env_path = os.environ.get("PHOTOS_ENGINE_LIB_PATH")
    if env_path:
        search_paths.insert(0, Path(env_path))

    for p in search_paths:
        if p.exists():
            return str(p)

    raise FileNotFoundError(
        f"Could not find photos_engine library ({lib_name}). "
        f"Searched in: {[str(p) for p in search_paths]}"
    )


def _load_auth_data() -> str:
    """Load AUTH_DATA from environment or .env files."""
    if auth := os.getenv("AUTH_DATA"):
        return auth

    for env_path in [Path(".env"), Path("../.env"), Path(__file__).resolve().parent.parent.parent / ".env"]:
        if env_path.is_file():
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("AUTH_DATA="):
                        return line[len("AUTH_DATA="):].strip().strip("'\"")
            except Exception:
                pass
    return ""


def _parse_c_json(lib, raw_ptr: Optional[int], func_name: str = "Go function") -> Any:
    """Parse JSON string allocated by Go runtime, free memory, and return data payload."""
    if not raw_ptr:
        raise RuntimeError(f"{func_name} returned null pointer")
    try:
        json_str = ctypes.string_at(raw_ptr).decode("utf-8")
    finally:
        lib.GPMC_FreeString(raw_ptr)

    result = json.loads(json_str)
    if not result.get("success", False):
        err = result.get("error", f"Unknown error in {func_name}")
        raise RuntimeError(f"{func_name} failed: {err}")

    return result.get("data")


class PhotosEngineClient:
    """
    Direct in-process Python client for Google Photos operations, powered by the Go core library.
    """

    def __init__(self, auth_data: Optional[str] = None, dll_path: Optional[str] = None):
        self.auth_data = auth_data or _load_auth_data()
        if not self.auth_data:
            raise ValueError("AUTH_DATA must be provided or set in environment / .env")

        self.dll_path = dll_path or _get_lib_path()
        self._lib = ctypes.CDLL(self.dll_path)
        self._setup_bindings()

        # Initialize Go client handle via JSON envelope to preserve initialization errors
        if hasattr(self._lib, "GPMC_CreateClient"):
            raw_ptr = self._lib.GPMC_CreateClient(self.auth_data.encode("utf-8"))
            data = _parse_c_json(self._lib, raw_ptr, "GPMC_CreateClient")
            self._handle = data["handle"]
        else:
            handle = self._lib.GPMC_NewClient(self.auth_data.encode("utf-8"))
            if handle == 0:
                raise RuntimeError("Failed to initialize Go GPMC Client")
            self._handle = handle

    def _setup_bindings(self):
        """Configure ctypes argument and return types for exported Go C-ABI functions."""
        c_ull = ctypes.c_ulonglong
        c_char_p = ctypes.c_char_p
        c_void_p = ctypes.c_void_p
        c_ll = ctypes.c_longlong

        if hasattr(self._lib, "GPMC_CreateClient"):
            self._lib.GPMC_CreateClient.argtypes = [c_char_p]
            self._lib.GPMC_CreateClient.restype = c_void_p

        self._lib.GPMC_NewClient.argtypes = [c_char_p]
        self._lib.GPMC_NewClient.restype = c_ull

        self._lib.GPMC_CloseClient.argtypes = [c_ull]
        self._lib.GPMC_CloseClient.restype = None

        self._lib.GPMC_GetToken.argtypes = [c_ull, c_ll]
        self._lib.GPMC_GetToken.restype = c_void_p

        self._lib.GPMC_GetDownloadURL.argtypes = [c_ull, c_char_p, c_ll]
        self._lib.GPMC_GetDownloadURL.restype = c_void_p

        self._lib.GPMC_CreateAlbum.argtypes = [c_ull, c_char_p, c_char_p, c_ll]
        self._lib.GPMC_CreateAlbum.restype = c_void_p

        self._lib.GPMC_CreateShareLink.argtypes = [c_ull, c_char_p, c_ll]
        self._lib.GPMC_CreateShareLink.restype = c_void_p

        self._lib.GPMC_DeletePermanently.argtypes = [c_ull, c_char_p, c_ll]
        self._lib.GPMC_DeletePermanently.restype = c_void_p

        self._lib.GPMC_DeleteByMediaKey.argtypes = [c_ull, c_char_p, c_ll]
        self._lib.GPMC_DeleteByMediaKey.restype = c_void_p

        self._lib.GPMC_ImportSharedMedia.argtypes = [c_ull, c_char_p, c_char_p, c_char_p, c_ll]
        self._lib.GPMC_ImportSharedMedia.restype = c_void_p

        self._lib.GPMC_FindMediaByHash.argtypes = [c_ull, c_char_p, c_ll]
        self._lib.GPMC_FindMediaByHash.restype = c_void_p

        self._lib.GPMC_FreeString.argtypes = [c_void_p]
        self._lib.GPMC_FreeString.restype = None

    def _call(self, func, *args, timeout: Optional[float] = None) -> Any:
        """Call a Go CGo function with timeout, parse JSON response, and free C memory."""
        timeout_ms = int(timeout * 1000) if timeout else 0
        raw_ptr = func(self._handle, *args, ctypes.c_longlong(timeout_ms))
        return _parse_c_json(self._lib, raw_ptr, func.__name__)

    def __del__(self):
        if hasattr(self, "_handle") and self._handle and hasattr(self, "_lib"):
            try:
                self._lib.GPMC_CloseClient(self._handle)
            except Exception:
                pass

    def get_token(self, timeout: Optional[float] = None) -> str:
        """Get a valid OAuth2 Bearer token from Go's thread-safe caching TokenManager."""
        return self._call(self._lib.GPMC_GetToken, timeout=timeout)

    def get_download_url(self, media_key: str, timeout: Optional[float] = None) -> DownloadInfo:
        """Retrieve direct download URL, filename, file size, SHA-1, and dedup key."""
        data = self._call(self._lib.GPMC_GetDownloadURL, media_key.encode("utf-8"), timeout=timeout)
        return DownloadInfo(
            media_key=data.get("media_key", media_key),
            filename=data.get("filename", ""),
            file_size=data.get("file_size", 0),
            download_url=data.get("download_url", ""),
            sha1_hex=data.get("sha1_hex", ""),
            dedup_key=data.get("dedup_key", ""),
        )

    def create_album(self, album_name: str, media_keys: List[str], timeout: Optional[float] = None) -> ShareInfo:
        """Create a shared album containing the specified media keys."""
        keys_json = json.dumps(media_keys).encode("utf-8")
        data = self._call(self._lib.GPMC_CreateAlbum, album_name.encode("utf-8"), keys_json, timeout=timeout)
        return ShareInfo(
            album_name=data.get("album_name", album_name),
            album_media_key=data.get("album_media_key", ""),
            media_keys=data.get("media_keys", media_keys),
        )

    def create_share_link(self, media_keys: Union[str, List[str]], timeout: Optional[float] = None) -> PublicShareLink:
        """
        Generate a public photos.app.goo.gl link for single or multiple media keys.

        Args:
            media_keys: Single media key string or list of media key strings.
            timeout: Optional network timeout in seconds.

        Returns:
            PublicShareLink dataclass containing share_url, envelope_key, auth_key.
        """
        if isinstance(media_keys, str):
            keys = [media_keys]
        else:
            keys = list(media_keys)

        keys_json = json.dumps(keys).encode("utf-8")
        data = self._call(self._lib.GPMC_CreateShareLink, keys_json, timeout=timeout)
        return PublicShareLink(
            share_url=data.get("share_url", ""),
            envelope_key=data.get("envelope_key", ""),
            auth_key=data.get("auth_key", ""),
            media_keys=data.get("media_keys", keys),
        )

    def delete_permanently(self, dedup_key: str, timeout: Optional[float] = None) -> bool:
        """Permanently delete media item by its deduplication key."""
        return bool(self._call(self._lib.GPMC_DeletePermanently, dedup_key.encode("utf-8"), timeout=timeout))

    def delete_by_media_key(self, media_key: str, timeout: Optional[float] = None) -> bool:
        """Resolve media key, move to trash, and delete the item permanently."""
        return bool(self._call(self._lib.GPMC_DeleteByMediaKey, media_key.encode("utf-8"), timeout=timeout))

    def import_shared_media(
        self, media_keys: List[str], auth_key: str, album_key: str, timeout: Optional[float] = None
    ) -> SaveResult:
        """Import shared album items into user's account spoofing Pixel XL original quality."""
        keys_json = json.dumps(media_keys).encode("utf-8")
        data = self._call(
            self._lib.GPMC_ImportSharedMedia,
            keys_json,
            auth_key.encode("utf-8"),
            album_key.encode("utf-8"),
            timeout=timeout,
        )
        status = data.get("status", 0)
        status_msg = data.get("status_message") or ""
        if not status_msg:
            if status == 2:
                status_msg = "Successfully imported into library"
            elif status == 1:
                status_msg = "Media is still processing on Google Photos servers. Not ready for import yet."
            else:
                status_msg = f"Import completed with status {status}"

        return SaveResult(
            original_keys=data.get("original_keys") or media_keys,
            new_keys=data.get("new_keys") or [],
            status=status,
            status_message=status_msg,
        )

    def find_by_hash(self, sha1_hex: str, timeout: Optional[float] = None) -> ExistResult:
        """Check if an item exists in the Google Photos library by SHA-1 hash."""
        data = self._call(self._lib.GPMC_FindMediaByHash, sha1_hex.encode("utf-8"), timeout=timeout)
        return ExistResult(
            exists=data.get("exists", False),
            media_key=data.get("media_key"),
        )

    def is_file_in_library(self, file_path: Union[str, Path]) -> ExistResult:
        """Compute SHA-1 of local file and check if it already exists in Google Photos."""
        import hashlib
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")

        h = hashlib.sha1()
        with open(path, "rb") as f:
            while chunk := f.read(1024 * 1024):
                h.update(chunk)
        return self.find_by_hash(h.hexdigest())

    def import_share_url(
        self,
        share_url: str,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Complete end-to-end import workflow:
        1. Scrapes share URL using httpcloak and selectolax
        2. Imports shared media into user's account with Pixel XL original quality spoofing
        3. Returns detailed summary
        """
        scraped = scrape_share_url(share_url)
        if not scraped.media_keys:
            return {
                "success": False,
                "error": "No media keys found in share URL",
                "scraped": scraped,
            }

        import_result = self.import_shared_media(
            media_keys=scraped.media_keys,
            auth_key=scraped.auth_key,
            album_key=scraped.album_key,
            timeout=timeout,
        )

        return {
            "success": import_result.status == 2,
            "status": import_result.status,
            "status_message": import_result.status_message,
            "is_processing": import_result.is_processing,
            "scraped": scraped,
            "media_count": len(scraped.media_keys),
            "import_result": import_result,
        }


# Backwards-compatible alias
GPMCClient = PhotosEngineClient


class NativeWebClient:
    """
    Native Google Photos Web Client powered directly by the compiled Go core DLL.
    Provides direct access to Go's GPWC implementation for cookies, Drive import, and download URLs.
    """

    def __init__(self, cookies: str, dll_path: Optional[str] = None):
        self.cookies = (cookies or "").strip()
        if not self.cookies:
            raise ValueError("Cookies cannot be empty")

        self.dll_path = dll_path or _get_lib_path()
        self._lib = ctypes.CDLL(self.dll_path)
        self._setup_bindings()

        if hasattr(self._lib, "GPWC_CreateClient"):
            raw_ptr = self._lib.GPWC_CreateClient(self.cookies.encode("utf-8"))
            data = _parse_c_json(self._lib, raw_ptr, "GPWC_CreateClient")
            self._handle = data["handle"]
        else:
            handle = self._lib.GPWC_NewClient(self.cookies.encode("utf-8"))
            if handle == 0:
                raise RuntimeError("Failed to initialize Go GPWC Client")
            self._handle = handle

    def _setup_bindings(self):
        c_ull = ctypes.c_ulonglong
        c_char_p = ctypes.c_char_p
        c_void_p = ctypes.c_void_p

        if hasattr(self._lib, "GPWC_CreateClient"):
            self._lib.GPWC_CreateClient.argtypes = [c_char_p]
            self._lib.GPWC_CreateClient.restype = c_void_p

        self._lib.GPWC_NewClient.argtypes = [c_char_p]
        self._lib.GPWC_NewClient.restype = c_ull

        self._lib.GPWC_CloseClient.argtypes = [c_ull]
        self._lib.GPWC_CloseClient.restype = None

        self._lib.GPWC_CheckStatus.argtypes = [c_char_p]
        self._lib.GPWC_CheckStatus.restype = c_void_p

        self._lib.GPWC_GetDownloadURL.argtypes = [c_ull, c_char_p]
        self._lib.GPWC_GetDownloadURL.restype = c_void_p

        self._lib.GPWC_ImportFromDrive.argtypes = [c_ull, c_char_p, c_char_p, ctypes.c_int]
        self._lib.GPWC_ImportFromDrive.restype = c_void_p

        self._lib.GPWC_CreateShareLink.argtypes = [c_ull, c_char_p]
        self._lib.GPWC_CreateShareLink.restype = c_void_p

        self._lib.GPMC_FreeString.argtypes = [c_void_p]
        self._lib.GPMC_FreeString.restype = None

    def _call(self, func, *args) -> Any:
        raw_ptr = func(self._handle, *args)
        return _parse_c_json(self._lib, raw_ptr, func.__name__)

    @classmethod
    def check_status(cls, cookies: str, dll_path: Optional[str] = None) -> CookieStatus:
        """Perform a quick cookie verification using the Go core without keeping a persistent client."""
        lib_path = dll_path or _get_lib_path()
        lib = ctypes.CDLL(lib_path)
        lib.GPWC_CheckStatus.argtypes = [ctypes.c_char_p]
        lib.GPWC_CheckStatus.restype = ctypes.c_void_p
        lib.GPMC_FreeString.argtypes = [ctypes.c_void_p]
        lib.GPMC_FreeString.restype = None

        raw_ptr = lib.GPWC_CheckStatus(cookies.encode("utf-8"))
        try:
            data = _parse_c_json(lib, raw_ptr, "GPWC_CheckStatus")
            return CookieStatus(
                valid=data.get("valid", False),
                account=data.get("account"),
                message=data.get("message", ""),
            )
        except Exception as exc:
            return CookieStatus(valid=False, message=str(exc))

    def get_download_url(self, media_key: str) -> DownloadInfo:
        """Retrieve direct download URL for a media key using Go core VrseUb RPC."""
        data = self._call(self._lib.GPWC_GetDownloadURL, media_key.encode("utf-8"))
        return DownloadInfo(
            media_key=data.get("media_key", media_key),
            download_url=data.get("download_url", ""),
            dedup_key=data.get("dedup_key", ""),
        )

    def import_from_drive(
        self,
        drive_file_id: str,
        mime_type: str = "video/*",
        cleanup: bool = False,
    ) -> DriveImportResult:
        """Import Google Drive file to Photos via Go core SusGud RPC."""
        data = self._call(
            self._lib.GPWC_ImportFromDrive,
            drive_file_id.encode("utf-8"),
            mime_type.encode("utf-8"),
            1 if cleanup else 0,
        )
        return DriveImportResult(
            drive_file_id=data.get("drive_file_id", drive_file_id),
            media_key=data.get("media_key", ""),
            dedup_key=data.get("dedup_key", ""),
            download_url=data.get("download_url"),
        )

    def create_share_link(self, media_key: str) -> PublicShareLink:
        """Create public photos.app.goo.gl link via Go core SFKp8c RPC."""
        data = self._call(self._lib.GPWC_CreateShareLink, media_key.encode("utf-8"))
        return PublicShareLink(
            share_url=data.get("share_url", ""),
            envelope_key=data.get("envelope_key", ""),
            auth_key=data.get("auth_key", ""),
            media_keys=[media_key],
        )

    def close(self):
        """Release Go client handle."""
        if hasattr(self, "_handle") and self._handle and hasattr(self, "_lib"):
            try:
                self._lib.GPWC_CloseClient(self._handle)
                self._handle = 0
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        self.close()

