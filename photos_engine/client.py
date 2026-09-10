"""
Native Python bindings for Google Photos Mobile Client (GPMC), powered directly by the Go core DLL.
"""

import asyncio
import ctypes
import json
import os
import platform
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .models import (
    AccountResetResult,
    CookieStatus,
    DownloadInfo,
    DriveBatchImportResult,
    DriveBatchItem,
    DriveImportItemResult,
    DriveImportResult,
    ExistResult,
    PublicShareLink,
    SaveResult,
    ScrapedShare,
    ShareInfo,
    StorageQuota,
)


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


_loaded_libs: Dict[str, ctypes.CDLL] = {}


def _get_cdll(dll_path: Optional[str] = None) -> ctypes.CDLL:
    path = dll_path or _get_lib_path()
    if path not in _loaded_libs:
        lib = ctypes.CDLL(path)
        if hasattr(lib, "GPMC_FreeString"):
            lib.GPMC_FreeString.argtypes = [ctypes.c_void_p]
            lib.GPMC_FreeString.restype = None
        if hasattr(lib, "GPMC_ScrapeShareURL"):
            lib.GPMC_ScrapeShareURL.argtypes = [ctypes.c_char_p, ctypes.c_longlong]
            lib.GPMC_ScrapeShareURL.restype = ctypes.c_void_p
        _loaded_libs[path] = lib
    return _loaded_libs[path]


def scrape_share_url(
    url: str,
    dll_path: Optional[str] = None,
    timeout: Optional[float] = None,
) -> ScrapedShare:
    """
    Fetch and parse a Google Photos shared album URL to extract album_key, auth_key, and media_keys.
    Executed directly via the native Go core engine.

    Args:
        url: Public Google Photos share URL (photos.app.goo.gl or photos.google.com/share/...)
        dll_path: Optional custom path to compiled Go shared library
        timeout: Optional network timeout in seconds

    Returns:
        ScrapedShare dataclass containing parsed keys
    """
    lib = _get_cdll(dll_path)
    timeout_ms = int(timeout * 1000) if timeout else 0
    raw_ptr = lib.GPMC_ScrapeShareURL(url.encode("utf-8"), ctypes.c_longlong(timeout_ms))
    data = _parse_c_json(lib, raw_ptr, "GPMC_ScrapeShareURL")
    return ScrapedShare(
        share_url=data.get("share_url", url),
        album_key=data.get("album_key", ""),
        auth_key=data.get("auth_key", ""),
        media_keys=data.get("media_keys") or [],
    )


ASYNC_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_int64, ctypes.c_char_p, ctypes.c_char_p)


class _AsyncCallbackManager:
    """
    Manages native async callbacks from Go goroutines for photos_engine.
    Bridges Go's goroutines and Python's asyncio via loop.call_soon_threadsafe.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._pending: Dict[int, Tuple[asyncio.Future, asyncio.AbstractEventLoop, float]] = {}
        self._callback_ref: Optional[ASYNC_CALLBACK] = None
        self._lib = None

    def _on_callback(self, callback_id: int, response_json: Optional[bytes], error: Optional[bytes]):
        """Called by Go runtime on a background OS thread when Goroutine completes."""
        with self._lock:
            if callback_id not in self._pending:
                return
            future, loop, start_time = self._pending.pop(callback_id)

        if error and error != b"":
            err_str = error.decode("utf-8")
            try:
                err_data = json.loads(err_str)
                err_msg = err_data.get("error", err_str)
            except Exception:
                err_msg = err_str
            loop.call_soon_threadsafe(future.set_exception, RuntimeError(err_msg))
        elif response_json:
            try:
                data = json.loads(response_json.decode("utf-8"))
                if not data.get("success", False):
                    loop.call_soon_threadsafe(
                        future.set_exception,
                        RuntimeError(data.get("error", "Unknown Go error"))
                    )
                else:
                    loop.call_soon_threadsafe(future.set_result, data.get("data"))
            except Exception as e:
                loop.call_soon_threadsafe(future.set_exception, RuntimeError(f"Failed to parse Go response: {e}"))
        else:
            loop.call_soon_threadsafe(future.set_exception, RuntimeError("No response received from Go engine"))

    def _ensure_callback(self, lib):
        if self._callback_ref is None:
            self._lib = lib
            self._callback_ref = ASYNC_CALLBACK(self._on_callback)

    def register_request(self, lib) -> Tuple[int, asyncio.Future]:
        self._ensure_callback(lib)
        callback_id = lib.GPMC_RegisterCallback(self._callback_ref)
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        start_time = time.perf_counter()

        with self._lock:
            self._pending[callback_id] = (future, loop, start_time)

        def _on_future_done(fut: asyncio.Future, _cid: int = callback_id, _lib=lib, _self=self) -> None:
            if fut.cancelled():
                try:
                    _lib.GPMC_CancelRequest(_cid)
                    _lib.GPMC_UnregisterCallback(_cid)
                except Exception:
                    pass
                with _self._lock:
                    _self._pending.pop(_cid, None)

        future.add_done_callback(_on_future_done)
        return callback_id, future


_async_manager: Optional[_AsyncCallbackManager] = None
_async_manager_lock = threading.Lock()


def _get_async_manager() -> _AsyncCallbackManager:
    global _async_manager
    if _async_manager is None:
        with _async_manager_lock:
            if _async_manager is None:
                _async_manager = _AsyncCallbackManager()
    return _async_manager


def _setup_async_lib(lib: ctypes.CDLL) -> None:
    """Configure ctypes bindings for async Go C-ABI functions."""
    if hasattr(lib, "_gpmc_async_initialized"):
        return

    c_ull = ctypes.c_ulonglong
    c_char_p = ctypes.c_char_p
    c_ll = ctypes.c_longlong
    c_int = ctypes.c_int
    c_i64 = ctypes.c_int64

    if hasattr(lib, "GPMC_RegisterCallback"):
        lib.GPMC_RegisterCallback.argtypes = [ASYNC_CALLBACK]
        lib.GPMC_RegisterCallback.restype = c_i64
        lib.GPMC_UnregisterCallback.argtypes = [c_i64]
        lib.GPMC_UnregisterCallback.restype = None
        lib.GPMC_CancelRequest.argtypes = [c_i64]
        lib.GPMC_CancelRequest.restype = None

    if hasattr(lib, "GPMC_GetToken_Async"):
        lib.GPMC_GetToken_Async.argtypes = [c_ull, c_ll, c_i64]
        lib.GPMC_GetToken_Async.restype = None

    if hasattr(lib, "GPMC_GetDownloadURL_Async"):
        lib.GPMC_GetDownloadURL_Async.argtypes = [c_ull, c_char_p, c_ll, c_i64]
        lib.GPMC_GetDownloadURL_Async.restype = None

    if hasattr(lib, "GPMC_CreateShareLink_Async"):
        lib.GPMC_CreateShareLink_Async.argtypes = [c_ull, c_char_p, c_ll, c_i64]
        lib.GPMC_CreateShareLink_Async.restype = None

    if hasattr(lib, "GPMC_DeletePermanently_Async"):
        lib.GPMC_DeletePermanently_Async.argtypes = [c_ull, c_char_p, c_ll, c_i64]
        lib.GPMC_DeletePermanently_Async.restype = None

    if hasattr(lib, "GPMC_DeleteByMediaKey_Async"):
        lib.GPMC_DeleteByMediaKey_Async.argtypes = [c_ull, c_char_p, c_ll, c_i64]
        lib.GPMC_DeleteByMediaKey_Async.restype = None

    if hasattr(lib, "GPMC_ImportSharedMedia_Async"):
        lib.GPMC_ImportSharedMedia_Async.argtypes = [c_ull, c_char_p, c_char_p, c_char_p, c_ll, c_i64]
        lib.GPMC_ImportSharedMedia_Async.restype = None

    if hasattr(lib, "GPMC_ScrapeShareURL_Async"):
        lib.GPMC_ScrapeShareURL_Async.argtypes = [c_char_p, c_ll, c_i64]
        lib.GPMC_ScrapeShareURL_Async.restype = None

    if hasattr(lib, "GPWC_CheckStatus_Async"):
        lib.GPWC_CheckStatus_Async.argtypes = [c_char_p, c_ll, c_i64]
        lib.GPWC_CheckStatus_Async.restype = None

    if hasattr(lib, "GPWC_GetDownloadURL_Async"):
        lib.GPWC_GetDownloadURL_Async.argtypes = [c_ull, c_char_p, c_ll, c_i64]
        lib.GPWC_GetDownloadURL_Async.restype = None

    if hasattr(lib, "GPWC_ImportFromDrive_Async"):
        lib.GPWC_ImportFromDrive_Async.argtypes = [c_ull, c_char_p, c_char_p, c_int, c_ll, c_i64]
        lib.GPWC_ImportFromDrive_Async.restype = None

    if hasattr(lib, "GPWC_CreateShareLink_Async"):
        lib.GPWC_CreateShareLink_Async.argtypes = [c_ull, c_char_p, c_ll, c_i64]
        lib.GPWC_CreateShareLink_Async.restype = None

    if hasattr(lib, "GPWC_GetStorageQuota_Async"):
        lib.GPWC_GetStorageQuota_Async.argtypes = [c_ull, c_ll, c_i64]
        lib.GPWC_GetStorageQuota_Async.restype = None

    lib._gpmc_async_initialized = True


async def scrape_share_url_async(
    url: str,
    dll_path: Optional[str] = None,
    timeout: Optional[float] = None,
) -> ScrapedShare:
    """Fetch and parse a Google Photos shared album URL asynchronously using Go goroutines."""
    lib = _get_cdll(dll_path)
    _setup_async_lib(lib)
    manager = _get_async_manager()
    callback_id, future = manager.register_request(lib)
    timeout_ms = int(timeout * 1000) if timeout else 0
    lib.GPMC_ScrapeShareURL_Async(url.encode("utf-8"), ctypes.c_longlong(timeout_ms), ctypes.c_int64(callback_id))
    data = await future
    return ScrapedShare(
        share_url=data.get("share_url", url),
        album_key=data.get("album_key", ""),
        auth_key=data.get("auth_key", ""),
        media_keys=data.get("media_keys") or [],
    )


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

        if hasattr(self._lib, "GPMC_ScrapeShareURL"):
            self._lib.GPMC_ScrapeShareURL.argtypes = [c_char_p, c_ll]
            self._lib.GPMC_ScrapeShareURL.restype = c_void_p

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

    def scrape_share_url(self, share_url: str, timeout: Optional[float] = None) -> ScrapedShare:
        """Fetch and extract album_key, auth_key, and media_keys from a share URL via Go core engine."""
        return scrape_share_url(share_url, dll_path=self.dll_path, timeout=timeout)

    def import_share_url(
        self,
        share_url: str,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Complete end-to-end import workflow:
        1. Scrapes share URL via Go core engine
        2. Imports shared media into user's account with Pixel XL original quality spoofing
        3. Returns detailed summary
        """
        scraped = self.scrape_share_url(share_url, timeout=timeout)
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

    async def _call_async(self, func, *args, timeout: Optional[float] = None) -> Any:
        """Call a Go CGo async function using native goroutines and asyncio.Future."""
        _setup_async_lib(self._lib)
        manager = _get_async_manager()
        callback_id, future = manager.register_request(self._lib)
        timeout_ms = int(timeout * 1000) if timeout else 0
        func(self._handle, *args, ctypes.c_longlong(timeout_ms), ctypes.c_int64(callback_id))
        return await future

    async def get_token_async(self, timeout: Optional[float] = None) -> str:
        """Get a valid OAuth2 Bearer token asynchronously using Go goroutines."""
        return await self._call_async(self._lib.GPMC_GetToken_Async, timeout=timeout)

    async def get_download_url_async(self, media_key: str, timeout: Optional[float] = None) -> DownloadInfo:
        """Retrieve direct download URL asynchronously using Go goroutines."""
        data = await self._call_async(self._lib.GPMC_GetDownloadURL_Async, media_key.encode("utf-8"), timeout=timeout)
        return DownloadInfo(
            media_key=data.get("media_key", media_key),
            filename=data.get("filename", ""),
            file_size=data.get("file_size", 0),
            download_url=data.get("download_url", ""),
            sha1_hex=data.get("sha1_hex", ""),
            dedup_key=data.get("dedup_key", ""),
        )

    async def create_share_link_async(self, media_keys: Union[str, List[str]], timeout: Optional[float] = None) -> PublicShareLink:
        """Generate a public photos.app.goo.gl link asynchronously using Go goroutines."""
        if isinstance(media_keys, str):
            keys = [media_keys]
        else:
            keys = list(media_keys)
        keys_json = json.dumps(keys).encode("utf-8")
        data = await self._call_async(self._lib.GPMC_CreateShareLink_Async, keys_json, timeout=timeout)
        return PublicShareLink(
            share_url=data.get("share_url", ""),
            envelope_key=data.get("envelope_key", ""),
            auth_key=data.get("auth_key", ""),
            media_keys=data.get("media_keys", keys),
        )

    async def delete_permanently_async(self, dedup_key: str, timeout: Optional[float] = None) -> bool:
        """Permanently delete media item by its dedup key asynchronously using Go goroutines."""
        res = await self._call_async(self._lib.GPMC_DeletePermanently_Async, dedup_key.encode("utf-8"), timeout=timeout)
        return bool(res)

    async def delete_by_media_key_async(self, media_key: str, timeout: Optional[float] = None) -> bool:
        """Permanently delete media item by media key asynchronously using Go goroutines."""
        res = await self._call_async(self._lib.GPMC_DeleteByMediaKey_Async, media_key.encode("utf-8"), timeout=timeout)
        return bool(res)

    async def import_shared_media_async(
        self, media_keys: List[str], auth_key: str, album_key: str, timeout: Optional[float] = None
    ) -> SaveResult:
        """Import shared photos/videos into user's account asynchronously using Go goroutines."""
        keys_json = json.dumps(media_keys).encode("utf-8")
        data = await self._call_async(
            self._lib.GPMC_ImportSharedMedia_Async,
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
            new_keys=data.get("new_keys") or data.get("new_media_keys") or [],
            status=status,
            status_message=status_msg,
        )

    async def scrape_share_url_async(self, share_url: str, timeout: Optional[float] = None) -> ScrapedShare:
        """Fetch and extract album_key, auth_key, and media_keys asynchronously using Go goroutines."""
        return await scrape_share_url_async(share_url, dll_path=self.dll_path, timeout=timeout)

    async def import_share_url_async(
        self,
        share_url: str,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Complete end-to-end import workflow asynchronously using Go goroutines."""
        scraped = await self.scrape_share_url_async(share_url, timeout=timeout)
        if not scraped.media_keys:
            return {
                "success": False,
                "error": "No media keys found in share URL",
                "scraped": scraped,
            }

        import_result = await self.import_shared_media_async(
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

    def __init__(self, cookies: Optional[str] = None, dll_path: Optional[str] = None, _handle: Optional[int] = None):
        self.dll_path = dll_path or _get_lib_path()
        self._lib = ctypes.CDLL(self.dll_path)
        self._setup_bindings()

        if _handle is not None:
            self._handle = _handle
            self.cookies = ""
            return

        self.cookies = (cookies or "").strip()
        if not self.cookies:
            raise ValueError("Cookies cannot be empty")

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

        if hasattr(self._lib, "GPWC_CreateClientFromBlob"):
            self._lib.GPWC_CreateClientFromBlob.argtypes = [c_char_p]
            self._lib.GPWC_CreateClientFromBlob.restype = c_void_p

        if hasattr(self._lib, "GPWC_ExportSessionBlob"):
            self._lib.GPWC_ExportSessionBlob.argtypes = [c_ull]
            self._lib.GPWC_ExportSessionBlob.restype = c_void_p

        if hasattr(self._lib, "GPWC_ExportCookies"):
            self._lib.GPWC_ExportCookies.argtypes = [c_ull]
            self._lib.GPWC_ExportCookies.restype = c_void_p

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

        if hasattr(self._lib, "GPWC_GetStorageQuota"):
            self._lib.GPWC_GetStorageQuota.argtypes = [c_ull]
            self._lib.GPWC_GetStorageQuota.restype = c_void_p

        if hasattr(self._lib, "GPWC_BatchImportFromDrive"):
            self._lib.GPWC_BatchImportFromDrive.argtypes = [c_ull, c_char_p, ctypes.c_int, ctypes.c_longlong]
            self._lib.GPWC_BatchImportFromDrive.restype = c_void_p

        if hasattr(self._lib, "GPWC_ResetAccount"):
            self._lib.GPWC_ResetAccount.argtypes = [c_ull, ctypes.c_longlong]
            self._lib.GPWC_ResetAccount.restype = c_void_p

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

    def get_storage_quota(self) -> StorageQuota:
        """Retrieve Google Photos account storage quota and usage limits."""
        data = self._call(self._lib.GPWC_GetStorageQuota)
        return StorageQuota(
            usage_text=data.get("usage_text", ""),
            used_display=data.get("used_display", ""),
            total_display=data.get("total_display", ""),
            used_percent=float(data.get("used_percent", 0.0)),
            free_percent=float(data.get("free_percent", 0.0)),
            used_bytes=int(data.get("used_bytes", 0)),
            total_bytes=int(data.get("total_bytes", 0)),
        )

    async def _call_async(self, func, *args, timeout: Optional[float] = None) -> Any:
        """Call a Go CGo async function on WebClient using native goroutines and asyncio.Future."""
        _setup_async_lib(self._lib)
        manager = _get_async_manager()
        callback_id, future = manager.register_request(self._lib)
        timeout_ms = int(timeout * 1000) if timeout else 0
        func(self._handle, *args, ctypes.c_longlong(timeout_ms), ctypes.c_int64(callback_id))
        return await future

    @classmethod
    async def check_status_async(cls, cookies: str, dll_path: Optional[str] = None, timeout: Optional[float] = None) -> CookieStatus:
        """Perform cookie verification asynchronously using native Go goroutines."""
        lib_path = dll_path or _get_lib_path()
        lib = ctypes.CDLL(lib_path)
        _setup_async_lib(lib)
        manager = _get_async_manager()
        callback_id, future = manager.register_request(lib)
        timeout_ms = int(timeout * 1000) if timeout else 0
        lib.GPWC_CheckStatus_Async(cookies.encode("utf-8"), ctypes.c_longlong(timeout_ms), ctypes.c_int64(callback_id))
        try:
            data = await future
            return CookieStatus(
                valid=data.get("valid", False),
                account=data.get("account"),
                message=data.get("message", ""),
            )
        except Exception as exc:
            return CookieStatus(valid=False, message=str(exc))

    async def get_download_url_async(self, media_key: str, timeout: Optional[float] = None) -> DownloadInfo:
        """Retrieve direct download URL asynchronously using Go goroutines."""
        data = await self._call_async(self._lib.GPWC_GetDownloadURL_Async, media_key.encode("utf-8"), timeout=timeout)
        return DownloadInfo(
            media_key=data.get("media_key", media_key),
            download_url=data.get("download_url", ""),
            dedup_key=data.get("dedup_key", ""),
        )

    async def import_from_drive_async(
        self,
        drive_file_id: str,
        mime_type: str = "video/*",
        cleanup: bool = False,
        timeout: Optional[float] = 300.0,  # 5 min; large files need more than Go's 45s default
    ) -> DriveImportResult:
        """Import Google Drive file to Photos asynchronously using Go goroutines."""
        data = await self._call_async(
            self._lib.GPWC_ImportFromDrive_Async,
            drive_file_id.encode("utf-8"),
            mime_type.encode("utf-8"),
            1 if cleanup else 0,
            timeout=timeout,
        )
        return DriveImportResult(
            drive_file_id=data.get("drive_file_id", drive_file_id),
            media_key=data.get("media_key", ""),
            dedup_key=data.get("dedup_key", ""),
            download_url=data.get("download_url"),
        )

    async def create_share_link_async(self, media_key: str, timeout: Optional[float] = None) -> PublicShareLink:
        """Create public photos.app.goo.gl link asynchronously using Go goroutines."""
        data = await self._call_async(self._lib.GPWC_CreateShareLink_Async, media_key.encode("utf-8"), timeout=timeout)
        return PublicShareLink(
            share_url=data.get("share_url", ""),
            envelope_key=data.get("envelope_key", ""),
            auth_key=data.get("auth_key", ""),
            media_keys=[media_key],
        )

    async def get_storage_quota_async(self, timeout: Optional[float] = None) -> StorageQuota:
        """Retrieve Google Photos storage quota asynchronously using Go goroutines."""
        data = await self._call_async(self._lib.GPWC_GetStorageQuota_Async, timeout=timeout)
        return StorageQuota(
            usage_text=data.get("usage_text", ""),
            used_display=data.get("used_display", ""),
            total_display=data.get("total_display", ""),
            used_percent=float(data.get("used_percent", 0.0)),
            free_percent=float(data.get("free_percent", 0.0)),
            used_bytes=int(data.get("used_bytes", 0)),
            total_bytes=int(data.get("total_bytes", 0)),
        )

    def batch_import_from_drive(
        self,
        items: List[Any],
        cleanup: bool = False,
        timeout_ms: int = 120000,
    ) -> DriveBatchImportResult:
        """Batch import multiple Google Drive files via Go core SusGud RPC."""
        parsed_items = []
        for it in items:
            if hasattr(it, "drive_file_id") and hasattr(it, "mime_type"):
                parsed_items.append({"drive_file_id": it.drive_file_id, "mime_type": it.mime_type})
            elif isinstance(it, dict):
                parsed_items.append({
                    "drive_file_id": it.get("drive_file_id", it.get("id", "")),
                    "mime_type": it.get("mime_type", it.get("mime", "video/*")),
                })
            elif isinstance(it, (list, tuple)):
                parsed_items.append({
                    "drive_file_id": it[0],
                    "mime_type": it[1] if len(it) > 1 else "video/*",
                })
            else:
                parsed_items.append({"drive_file_id": str(it), "mime_type": "video/*"})

        items_json = json.dumps(parsed_items)
        data = self._call(
            self._lib.GPWC_BatchImportFromDrive,
            items_json.encode("utf-8"),
            1 if cleanup else 0,
            timeout_ms,
        )

        item_results = []
        for raw_it in data.get("items", []):
            item_results.append(
                DriveImportItemResult(
                    drive_file_id=raw_it.get("drive_file_id", ""),
                    media_key=raw_it.get("media_key", ""),
                    dedup_key=raw_it.get("dedup_key", ""),
                    download_url=raw_it.get("download_url"),
                    width=raw_it.get("width", 0),
                    height=raw_it.get("height", 0),
                    file_size=raw_it.get("file_size", 0),
                    status=raw_it.get("status", 0),
                    error=raw_it.get("error", ""),
                )
            )

        return DriveBatchImportResult(
            success_count=data.get("success_count", 0),
            failed_count=data.get("failed_count", 0),
            items=item_results,
            quota_exceeded=data.get("quota_exceeded", False),
            error_message=data.get("error_message", ""),
        )

    def reset_account(self, timeout_ms: int = 120000) -> AccountResetResult:
        """Clear entire Google Photos library: moves all items to trash via XwAOJf and empties trash via e2FP6c."""
        data = self._call(self._lib.GPWC_ResetAccount, timeout_ms)
        return AccountResetResult(
            success=data.get("success", False),
            total_deleted=data.get("total_deleted", 0),
            trash_emptied=data.get("trash_emptied", False),
            message=data.get("message", ""),
        )


    @classmethod
    def from_blob(cls, blob: Union[bytes, str], dll_path: Optional[str] = None) -> "NativeWebClient":
        """Restore an active NativeWebClient from a serialized session blob (bytes or hex string)."""
        blob_hex = blob.hex() if isinstance(blob, bytes) else blob.strip()
        lib_path = dll_path or _get_lib_path()
        lib = ctypes.CDLL(lib_path)
        lib.GPWC_CreateClientFromBlob.argtypes = [ctypes.c_char_p]
        lib.GPWC_CreateClientFromBlob.restype = ctypes.c_void_p
        lib.GPMC_FreeString.argtypes = [ctypes.c_void_p]
        lib.GPMC_FreeString.restype = None

        raw_ptr = lib.GPWC_CreateClientFromBlob(blob_hex.encode("utf-8"))
        data = _parse_c_json(lib, raw_ptr, "GPWC_CreateClientFromBlob")
        return cls(dll_path=lib_path, _handle=data["handle"])

    def export_session_blob(self) -> bytes:
        """Export serialized session blob (cookies, TLS tickets) for database persistence."""
        data = self._call(self._lib.GPWC_ExportSessionBlob)
        return bytes.fromhex(data.get("blob_hex", ""))

    def export_cookies(self) -> Dict[str, str]:
        """Export current live cookies from the session jar as header and Netscape string."""
        return self._call(self._lib.GPWC_ExportCookies)

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

