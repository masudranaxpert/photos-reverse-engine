---
title: Python API
description: Comprehensive Python API reference for classes, methods, models, and FFI bindings in photos_engine
icon: lucide/code-2
---

# Python API Reference

Comprehensive reference for classes, methods, models, and top-level functions in the `photos_engine` package.

---

## Top-Level Functions

All common operations can be executed directly from the module namespace without manually creating a client instance.

### `get_token()`

```python
photos_engine.get_token(auth_data: Optional[str] = None) -> str
```

Retrieves an active OAuth2 Bearer token (`ya29...`) with transparent auto-refreshing.

**Parameters:**

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `auth_data` | `str, optional` | `None` | Master token credential string. If omitted, reads from `.env` or `AUTH_DATA` environment variable. |

**Returns:**

* `str`: A valid OAuth2 Bearer token string.

**Example:**

```python
import photos_engine

token = photos_engine.get_token()
print("Token:", token[:25] + "...")
```

---

### `create_share_link()`

```python
photos_engine.create_share_link(
    media_keys: Union[str, List[str]], 
    auth_data: Optional[str] = None
) -> PublicShareLink
```

Generates an official public short link (`https://photos.app.goo.gl/...`) for one or multiple media keys.

**Parameters:**

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `media_keys` | `str` or `List[str]` | *required* | A single media key or a list of media keys to share. |
| `auth_data` | `str, optional` | `None` | Custom credentials string. |

**Returns:**

* [`PublicShareLink`](#publicsharelink): Object containing `share_url`, `media_key`, and `auth_key`.

**Example:**

```python
link = photos_engine.create_share_link(["AF1QipM...", "AF1QipN..."])
print("Public Share Link:", link.share_url)
```

---

### `get_download_url()`

```python
photos_engine.get_download_url(
    media_key: str, 
    auth_data: Optional[str] = None
) -> DownloadInfo
```

Extracts original-quality media stream download URLs, file metadata, exact byte sizes, and SHA-1 checksums.

**Parameters:**

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `media_key` | `str` | *required* | The media item's unique key. |
| `auth_data` | `str, optional` | `None` | Custom credentials string. |

**Returns:**

* [`DownloadInfo`](#downloadinfo): Direct download stream link and file attributes.

---

### `import_share_url()`

```python
photos_engine.import_share_url(
    share_url: str, 
    auth_data: Optional[str] = None
) -> Dict[str, Any]
```

Scrapes a public Google Photos shared link (via native Go core engine) and saves all contained media items into your library with Google Pixel XL original quality backup spoofing.

**Parameters:**

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `share_url` | `str` | *required* | Public Google Photos URL (`https://photos.app.goo.gl/...`). |
| `auth_data` | `str, optional` | `None` | Custom credentials string. |

**Returns:**

* `dict`: Dictionary with `share_info` (`ShareInfo`), `shared_media` (`List[ScrapedShare]`), and `import_result` (`SaveResult`).

---

### `delete_by_media_key()`

```python
photos_engine.delete_by_media_key(
    media_key: str, 
    auth_data: Optional[str] = None
) -> bool
```

Permanently expunges an item from Google Photos using the atomic Move-to-Trash -> DeletePermanently sequence.

**Parameters:**

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `media_key` | `str` | *required* | Media key of the item to delete. |
| `auth_data` | `str, optional` | `None` | Custom credentials string. |

**Returns:**

* `bool`: `True` if successfully expunged, `False` otherwise.

---

### `is_file_in_library()`

```python
photos_engine.is_file_in_library(
    file_path: Union[str, Path], 
    auth_data: Optional[str] = None
) -> ExistResult
```

Computes the 20-byte SHA-1 hash of a local file and queries Google Photos to verify whether it already exists in your library.

**Parameters:**

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `file_path` | `str` or `Path` | *required* | Path to the local photo or video file. |
| `auth_data` | `str, optional` | `None` | Custom credentials string. |

**Returns:**

* [`ExistResult`](#existresult): Object indicating `.exists`, `.sha1_hash`, `.media_key`, and `.dedup_key`.

---

## Client Class

For stateful interactions or custom configuration, instantiate `photos_engine.Client`.

```python
from photos_engine import Client

client = Client(auth_data="...")
```

### Constructor

```python
Client(auth_data: Optional[str] = None, lib_path: Optional[str] = None)
```

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `auth_data` | `str, optional` | `None` | Master token string. If omitted, reads from `.env`. |
| `lib_path` | `str, optional` | `None` | Explicit path to compiled native dynamic library (`.dll`, `.so`, `.dylib`). |

### Client Methods

| Method | Return Type | Description |
| :--- | :--- | :--- |
| `client.get_token()` | `str` | Fetch active OAuth2 Bearer token. |
| `client.create_share_link(media_keys)` | `PublicShareLink` | Create public short link for media keys. |
| `client.get_download_url(media_key)` | `DownloadInfo` | Get direct stream download URL and metadata. |
| `client.import_share_url(share_url)` | `dict` | Scrape and save shared link with Pixel XL spoofing. |
| `client.import_shared_media(...)` | `SaveResult` | Low-level import of media keys with auth key. |
| `client.delete_by_media_key(media_key)`| `bool` | Permanently delete media item. |
| `client.move_to_trash(dedup_key)` | `bool` | Move item to trash via base64 dedup key. |
| `client.delete_permanently(dedup_key)`| `bool` | Permanently delete item from trash. |
| `client.find_media_by_hash(sha1_hash)` | `ExistResult` | Check if 20-byte SHA-1 hash exists in library. |
| `client.is_file_in_library(file_path)` | `ExistResult` | Check local file existence by hash. |

---

## Data Models

All models are strongly-typed Python dataclasses.

### `DownloadInfo`

```python
@dataclass
class DownloadInfo:
    download_url: str   # Direct original quality stream URL
    filename: str       # Original filename (e.g. VID_2026.mp4)
    file_size: int      # Exact file size in bytes
    sha1_hash: str      # Hex-encoded SHA-1 checksum
    dedup_key: str      # URL-safe base64 deduplication key
```

### `PublicShareLink`

```python
@dataclass
class PublicShareLink:
    share_url: str   # Public short URL (https://photos.app.goo.gl/...)
    media_key: str   # Envelope media key
    auth_key: str    # Internal authentication key for the envelope
```

### `SaveResult`

```python
@dataclass
class SaveResult:
    status: int           # Status code (2 = Success)
    success: bool         # True if successfully saved
    new_keys: List[str]   # Newly assigned media keys in user's library
```

### `ExistResult`

```python
@dataclass
class ExistResult:
    exists: bool      # True if present in library
    sha1_hash: str    # Hex SHA-1 hash
    media_key: str    # Media key if exists, empty otherwise
    dedup_key: str    # Dedup key if exists, empty otherwise
```

### `CookieStatus`

```python
@dataclass
class CookieStatus:
    valid: bool                 # True if cookies are active
    session_id: str = "default" # Session identifier
    account: Optional[str]      # Connected Google email address
    message: str                # Human-readable status message
```

### `DriveImportResult`

```python
@dataclass
class DriveImportResult:
    drive_file_id: str          # Original Google Drive file ID
    media_key: str              # Newly created Google Photos media key
    dedup_key: str              # Deduplication key in Photos
    download_url: Optional[str] # Direct stream download URL
```

### `StorageQuota`

```python
@dataclass
class StorageQuota:
    usage_text: str    # Human-readable string, e.g. "9.3 GB of 15 GB used"
    used_display: str  # Display string of used space, e.g. "9.3 GB"
    total_display: str # Display string of total space, e.g. "15 GB"
    used_percent: float# Used percentage, e.g. 61.7
    free_percent: float# Free percentage, e.g. 38.3
    used_bytes: int    # Used storage in bytes
    total_bytes: int   # Total storage limit in bytes
```

### `DriveBatchImportResult`

```python
@dataclass
class DriveBatchImportResult:
    success_count: int               # Count of successfully imported items
    failed_count: int                # Count of failed items
    items: List[DriveImportItemResult] # Individual item results
    quota_exceeded: bool             # True if rejected due to storage quota full
    error_message: str               # Detailed error description
```

### `AccountResetResult`

```python
@dataclass
class AccountResetResult:
    success: bool        # True if reset succeeded
    total_deleted: int   # Total items moved to trash and purged
    trash_emptied: bool  # True if trash was permanently emptied
    message: str         # Detailed summary message
```

---

## Web Client & Cookies API

For cookie-authenticated web sessions, Google Drive to Photos imports, storage quota inspection, and session database persistence.

### `NativeWebClient` (Go Core DLL Powered)

Direct ctypes FFI binding to the native Go GPWC core engine:

```python
from photos_engine import NativeWebClient

# 1. Quick status check without keeping persistent handle
status = NativeWebClient.check_status("cookies_data_here")

# 2. Stateful client with compiled Go core performance
with NativeWebClient(cookies="cookies_data_here") as client:
    # Check account storage quota
    quota = client.get_storage_quota()
    print(f"Storage: {quota.usage_text} ({quota.used_percent}% used)")

    # Batch import files from Google Drive with quota full detection
    res = client.batch_import_from_drive([
        {"drive_file_id": "173o1kBve_...", "mime_type": "video/x-matroska"},
        {"drive_file_id": "1TjQP3B7gw...", "mime_type": "video/x-matroska"},
    ], cleanup=False)
    if res.quota_exceeded:
        print("Storage quota full!")
    else:
        print(f"Imported {res.success_count} files successfully!")

    # Complete account library wipe and purge trash
    reset = client.reset_account()
    print(f"Reset {reset.total_deleted} items: {reset.message}")
```

### `GooglePhotosWebClient` (httpcloak & Database Sessions)

High-level Python web client supporting pluggable session storage (SQLite, PostgreSQL, MySQL) and automatic rotating cookie synchronization:

```python
from photos_engine import GooglePhotosWebClient, DatabaseCookieStore

# Database-backed session store with customizable table and column names
store = DatabaseCookieStore(
    db_source="cookies.db",
    table_name="my_sessions",
    session_id_col="sess_id",
    blob_col="blob_data",
)

with GooglePhotosWebClient(store=store) as client:
    status = client.check_status(session_id="default")
    print("Account:", status.account)
```

