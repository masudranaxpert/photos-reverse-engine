"""
photos_engine - High-performance Google Photos Client with native Go core engine.

Provides direct in-process C-ABI bindings to the native Go core library.
"""

from typing import Any, Dict, List, Optional, Union
from pathlib import Path

from .client import (
    GPMCClient,
    NativeWebClient,
    PhotosEngineClient,
    StreamNotReadyError,
    scrape_share_url,
    scrape_share_url_async,
)
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

# Standard aliases
Client = PhotosEngineClient
WebClient = NativeWebClient

_default_client: Optional[PhotosEngineClient] = None


def _get_default_client(auth_data: Optional[str] = None) -> PhotosEngineClient:
    global _default_client
    if auth_data:
        return PhotosEngineClient(auth_data=auth_data)
    if _default_client is None:
        _default_client = PhotosEngineClient()
    return _default_client


def get_token(auth_data: Optional[str] = None, timeout: Optional[float] = None) -> str:
    """Get a valid OAuth2 Bearer token."""
    return _get_default_client(auth_data).get_token(timeout=timeout)


def get_download_url(media_key: str, auth_data: Optional[str] = None, timeout: Optional[float] = None) -> DownloadInfo:
    """Retrieve direct download URL, filename, file size, SHA-1, and dedup key."""
    return _get_default_client(auth_data).get_download_url(media_key, timeout=timeout)


def create_share_link(
    media_keys: Union[str, List[str]], auth_data: Optional[str] = None, timeout: Optional[float] = None
) -> PublicShareLink:
    """Generate a public photos.app.goo.gl link for single or multiple media keys."""
    return _get_default_client(auth_data).create_share_link(media_keys, timeout=timeout)


def import_share_url(
    share_url: str, auth_data: Optional[str] = None, timeout: Optional[float] = None
) -> Dict[str, Any]:
    """Scrape and import shared media with Pixel XL spoofing."""
    return _get_default_client(auth_data).import_share_url(share_url, timeout=timeout)


def delete_by_media_key(media_key: str, auth_data: Optional[str] = None, timeout: Optional[float] = None) -> bool:
    """Permanently delete media item by its media key."""
    return _get_default_client(auth_data).delete_by_media_key(media_key, timeout=timeout)


def is_file_in_library(file_path: Union[str, Path], auth_data: Optional[str] = None) -> ExistResult:
    """Check if a local file exists in Google Photos by SHA-1."""
    return _get_default_client(auth_data).is_file_in_library(file_path)


async def get_token_async(auth_data: Optional[str] = None, timeout: Optional[float] = None) -> str:
    """Get a valid OAuth2 Bearer token asynchronously via native goroutine."""
    return await _get_default_client(auth_data).get_token_async(timeout=timeout)


async def get_download_url_async(
    media_key: str, auth_data: Optional[str] = None, timeout: Optional[float] = None
) -> DownloadInfo:
    """Retrieve download URL asynchronously via native goroutine."""
    return await _get_default_client(auth_data).get_download_url_async(media_key, timeout=timeout)


async def create_share_link_async(
    media_keys: Union[str, List[str]], auth_data: Optional[str] = None, timeout: Optional[float] = None
) -> PublicShareLink:
    """Generate a public photos.app.goo.gl link asynchronously via native goroutine."""
    return await _get_default_client(auth_data).create_share_link_async(media_keys, timeout=timeout)


async def import_share_url_async(
    share_url: str, auth_data: Optional[str] = None, timeout: Optional[float] = None
) -> Dict[str, Any]:
    """Scrape and import shared media asynchronously via native goroutine."""
    return await _get_default_client(auth_data).import_share_url_async(share_url, timeout=timeout)


def get_stream_manifest(
    media_key: str,
    protocol: str = "hls",
    content_version: Optional[int] = None,
    auth_data: Optional[str] = None,
    timeout: Optional[float] = None,
) -> str:
    """Fetch streaming video manifest (HLS .m3u8 or DASH .mpd)."""
    return _get_default_client(auth_data).get_stream_manifest(
        media_key, protocol=protocol, content_version=content_version, timeout=timeout
    )


async def get_stream_manifest_async(
    media_key: str,
    protocol: str = "hls",
    content_version: Optional[int] = None,
    auth_data: Optional[str] = None,
    timeout: Optional[float] = None,
) -> str:
    """Fetch streaming video manifest asynchronously via native goroutine."""
    return await _get_default_client(auth_data).get_stream_manifest_async(
        media_key, protocol=protocol, content_version=content_version, timeout=timeout
    )


__all__ = [
    "Client",
    "PhotosEngineClient",
    "GPMCClient",
    "WebClient",
    "NativeWebClient",
    "get_token",
    "get_token_async",
    "get_download_url",
    "get_download_url_async",
    "get_stream_manifest",
    "get_stream_manifest_async",
    "create_share_link",
    "create_share_link_async",
    "import_share_url",
    "import_share_url_async",
    "delete_by_media_key",
    "is_file_in_library",
    "scrape_share_url",
    "scrape_share_url_async",
    "DownloadInfo",
    "ShareInfo",
    "SaveResult",
    "ExistResult",
    "ScrapedShare",
    "PublicShareLink",
    "CookieStatus",
    "DriveImportResult",
    "DriveBatchItem",
    "DriveImportItemResult",
    "DriveBatchImportResult",
    "AccountResetResult",
    "StorageQuota",
]

