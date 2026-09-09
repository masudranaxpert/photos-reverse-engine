"""
Data models for Google Photos Mobile Client (GPMC).
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class DownloadInfo:
    media_key: str
    filename: str = ""
    file_size: int = 0
    download_url: str = ""
    sha1_hex: str = ""
    dedup_key: str = ""


@dataclass
class ShareInfo:
    album_name: str
    album_media_key: str
    media_keys: List[str] = field(default_factory=list)


@dataclass
class SaveResult:
    original_keys: List[str] = field(default_factory=list)
    new_keys: List[str] = field(default_factory=list)
    status: int = 0


@dataclass
class ExistResult:
    exists: bool
    media_key: Optional[str] = None


@dataclass
class ScrapedShare:
    share_url: str
    album_key: str
    auth_key: str
    media_keys: List[str] = field(default_factory=list)


@dataclass
class PublicShareLink:
    share_url: str
    envelope_key: str
    auth_key: str
    media_keys: List[str] = field(default_factory=list)
