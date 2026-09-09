# Python API Reference

Complete reference for classes, methods, models, and top-level functions in `photos_engine`.

---

## Top-Level Functions

All common tasks can be invoked directly from the module namespace without manually creating a client instance.

### `photos_engine.get_token(auth_data: Optional[str] = None) -> str`
Retrieves a valid OAuth2 Bearer token (`ya29...`).
- **Parameters**: `auth_data` *(optional)*: Custom auth string. Defaults to `.env` / environment `AUTH_DATA`.
- **Returns**: Valid access token string.
- **Auto-Refresh**: Handled automatically in background if expired or expiring within 5 minutes.

### `photos_engine.create_share_link(media_keys: Union[str, List[str]], auth_data: Optional[str] = None) -> PublicShareLink`
Creates a public `https://photos.app.goo.gl/...` share link for one or multiple media keys.
- **Parameters**:
  - `media_keys`: Single media key string or list of media key strings.
  - `auth_data` *(optional)*: Auth data credentials.
- **Returns**: `PublicShareLink` dataclass.

### `photos_engine.get_download_url(media_key: str, auth_data: Optional[str] = None) -> DownloadInfo`
Retrieves original stream download URL, filename, file size, SHA-1 checksum, and dedup key.
- **Parameters**: `media_key`: The media item's unique key.
- **Returns**: `DownloadInfo` dataclass.

### `photos_engine.import_share_url(share_url: str, auth_data: Optional[str] = None) -> Dict[str, Any]`
Scrapes public shared album/item via `httpcloak` + `selectolax` and imports them into your Google Photos library with Pixel XL original quality backup spoofing.
- **Parameters**: `share_url`: The `https://photos.app.goo.gl/...` public URL.
- **Returns**: Dictionary with:
  - `share_info`: `ShareInfo` metadata.
  - `shared_media`: List of `ScrapedShare` items.
  - `import_result`: `SaveResult` containing newly generated library keys.

### `photos_engine.delete_by_media_key(media_key: str, auth_data: Optional[str] = None) -> bool`
Permanently deletes a photo or video from Google Photos.
- **Process**: Resolves media key -> dedup key -> moves to trash -> deletes permanently.
- **Returns**: `True` if successfully deleted, `False` otherwise.

### `photos_engine.is_file_in_library(file_path: Union[str, Path], auth_data: Optional[str] = None) -> ExistResult`
Calculates the local file's SHA-1 checksum and checks whether it already exists in your Google Photos library.
- **Parameters**: `file_path`: Path to the local file.
- **Returns**: `ExistResult` dataclass with `.exists`, `.sha1_hash`, `.media_key`, and `.dedup_key`.

---

## Class: `Client` (`PhotosEngineClient`)

```python
from photos_engine import Client

client = Client(auth_data="...")
```

### Constructor
```python
Client(auth_data: Optional[str] = None, lib_path: Optional[str] = None)
```
- `auth_data`: Master token credentials. If omitted, loaded from `.env` or `AUTH_DATA` environment variable.
- `lib_path`: Explicit path to native compiled dynamic library (`.dll`, `.so`, `.dylib`). If omitted, detected automatically from package `lib/` directory.

### Methods
- `client.get_token() -> str`
- `client.get_download_url(media_key: str) -> DownloadInfo`
- `client.create_share_link(media_keys: Union[str, List[str]]) -> PublicShareLink`
- `client.import_shared_media(auth_key: str, media_keys: List[str]) -> SaveResult`
- `client.import_share_url(share_url: str) -> Dict[str, Any]`
- `client.move_to_trash(dedup_key: str) -> bool`
- `client.delete_permanently(dedup_key: str) -> bool`
- `client.delete_by_media_key(media_key: str) -> bool`
- `client.find_media_by_hash(sha1_hash: str) -> ExistResult`
- `client.is_file_in_library(file_path: Union[str, Path]) -> ExistResult`

---

## Data Models

All models are strongly typed Python dataclasses:

### `DownloadInfo`
```python
@dataclass
class DownloadInfo:
    download_url: str   # Direct original stream download link
    filename: str       # Original filename (e.g. VID_2026.mp4)
    file_size: int      # Exact file size in bytes
    sha1_hash: str      # Hex-encoded SHA-1 checksum
    dedup_key: str      # Base64 dedup key used for deletion/query
```

### `PublicShareLink`
```python
@dataclass
class PublicShareLink:
    share_url: str   # Public short URL (e.g. https://photos.app.goo.gl/...)
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
    exists: bool      # True if present in user's library
    sha1_hash: str    # Hex SHA-1 hash of the file
    media_key: str    # Media key if exists, empty otherwise
    dedup_key: str    # Dedup key if exists, empty otherwise
```
