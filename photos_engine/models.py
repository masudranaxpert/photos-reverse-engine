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
    status_message: str = ""

    @property
    def is_success(self) -> bool:
        """True if successfully saved into library with new keys assigned."""
        return self.status == 2 and len(self.new_keys) > 0

    @property
    def is_processing(self) -> bool:
        """True if media is still being transcoded/processed on Google Photos servers."""
        return self.status == 1


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


@dataclass
class CookieStatus:
    valid: bool
    session_id: str = "default"
    account: Optional[str] = None
    message: str = ""


@dataclass
class DriveImportResult:
    drive_file_id: str
    media_key: str
    dedup_key: str
    download_url: Optional[str] = None
    filename: str = ""


@dataclass
class StorageQuota:
    usage_text: str = ""
    used_display: str = ""
    total_display: str = ""
    used_percent: float = 0.0
    free_percent: float = 0.0
    used_bytes: int = 0
    total_bytes: int = 0


@dataclass
class DriveBatchItem:
    drive_file_id: str
    mime_type: str = "video/*"


@dataclass
class DriveImportItemResult:
    drive_file_id: str
    media_key: str = ""
    dedup_key: str = ""
    download_url: Optional[str] = None
    width: int = 0
    height: int = 0
    file_size: int = 0
    status: int = 0
    error: str = ""


@dataclass
class DriveBatchImportResult:
    success_count: int = 0
    failed_count: int = 0
    items: List[DriveImportItemResult] = field(default_factory=list)
    quota_exceeded: bool = False
    error_message: str = ""


@dataclass
class AccountResetResult:
    success: bool
    total_deleted: int = 0
    trash_emptied: bool = False
    message: str = ""


