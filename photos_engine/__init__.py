"""
photos_engine - High-performance Google Photos Client with native Go core engine.

Provides direct in-process bindings to the native Go core library with TLS-fingerprinted scraping.
"""

from typing import Any, Dict, List, Optional, Union
from pathlib import Path

from .client import GPMCClient, NativeWebClient, PhotosEngineClient
from .cookies import BaseCookieStore, DatabaseCookieStore, FileCookieStore, SessionManager
from .models import (
    CookieStatus,
    DownloadInfo,
    DriveImportResult,
    ExistResult,
    PublicShareLink,
    SaveResult,
    ScrapedShare,
    ShareInfo,
)
from .scraper import scrape_share_url
from .web_client import GooglePhotosWebClient

# Standard alias matching httpcloak style (Client)
Client = PhotosEngineClient

_default_client: Optional[PhotosEngineClient] = None


def _get_default_client(auth_data: Optional[str] = None) -> PhotosEngineClient:
    global _default_client
    if auth_data:
        return PhotosEngineClient(auth_data=auth_data)
    if _default_client is None:
        _default_client = PhotosEngineClient()
    return _default_client


def get_token(auth_data: Optional[str] = None) -> str:
    """Get a valid OAuth2 Bearer token."""
    return _get_default_client(auth_data).get_token()


def get_download_url(media_key: str, auth_data: Optional[str] = None) -> DownloadInfo:
    """Retrieve direct download URL, filename, file size, SHA-1, and dedup key."""
    return _get_default_client(auth_data).get_download_url(media_key)


def create_share_link(media_keys: Union[str, List[str]], auth_data: Optional[str] = None) -> PublicShareLink:
    """Generate a public photos.app.goo.gl link for single or multiple media keys."""
    return _get_default_client(auth_data).create_share_link(media_keys)


def import_share_url(share_url: str, auth_data: Optional[str] = None) -> Dict[str, Any]:
    """Scrape and import shared media with Pixel XL spoofing."""
    return _get_default_client(auth_data).import_share_url(share_url)


def delete_by_media_key(media_key: str, auth_data: Optional[str] = None) -> bool:
    """Permanently delete media item by its media key."""
    return _get_default_client(auth_data).delete_by_media_key(media_key)


def is_file_in_library(file_path: Union[str, Path], auth_data: Optional[str] = None) -> ExistResult:
    """Check if a local file exists in Google Photos by SHA-1."""
    return _get_default_client(auth_data).is_file_in_library(file_path)


__all__ = [
    "Client",
    "PhotosEngineClient",
    "GPMCClient",
    "NativeWebClient",
    "GooglePhotosWebClient",
    "FileCookieStore",
    "DatabaseCookieStore",
    "BaseCookieStore",
    "SessionManager",
    "get_token",
    "get_download_url",
    "create_share_link",
    "import_share_url",
    "delete_by_media_key",
    "is_file_in_library",
    "scrape_share_url",
    "DownloadInfo",
    "ShareInfo",
    "SaveResult",
    "ExistResult",
    "ScrapedShare",
    "PublicShareLink",
    "CookieStatus",
    "DriveImportResult",
]
