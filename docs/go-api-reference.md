---
title: Go Core API
description: Comprehensive Go API reference for the high-performance native engine core
icon: lucide/cpu
---

# Go API Reference

Comprehensive reference for using the native Go core engine (`github.com/masudranaxpert/photos-reverse-engine/core`).

---

## Package Import

```go
import "github.com/masudranaxpert/photos-reverse-engine/core"
```

---

## Client Constructor

### `NewClient()`

```go
func NewClient(authData string) (*Client, error)
```

Initializes a new Google Photos client instance.

**Parameters:**

| Parameter | Type | Description |
| :--- | :--- | :--- |
| `authData` | `string` | Credential string (`oauth2_rt_1/0...:49029607:androidId`). If empty, reads from `.env` or `AUTH_DATA` environment variable. |

**Returns:**

* `*core.Client`: Initialized client pointer, or an error if credentials are missing or invalid.

**Example:**

```go
client, err := core.NewClient("")
if err != nil {
    log.Fatal(err)
}
```

---

## Client Methods

### `GetToken()`

```go
func (c *Client) GetToken(ctx context.Context) (string, error)
```

Retrieves an active OAuth2 Bearer token (`ya29...`) with thread-safe RWMutex caching and automatic 5-minute proactive token refresh.

---

### `GetDownloadURL()`

```go
func (c *Client) GetDownloadURL(ctx context.Context, mediaKey string) (*DownloadInfo, error)
```

Fetches the original-quality media stream download URL, filename, file size in bytes, SHA-1 checksum, and deduplication key.

**Parameters:**

| Parameter | Type | Description |
| :--- | :--- | :--- |
| `ctx` | `context.Context` | Context for cancellation / timeout. |
| `mediaKey` | `string` | Unique media key of the item. |

**Returns:**

* `*core.DownloadInfo`: Download stream URL and metadata struct.

---

### `CreateShareLink()`

```go
func (c *Client) CreateShareLink(ctx context.Context, mediaKeys []string) (*PublicShareLink, error)
```

Calls internal Google Photos envelope endpoint `11663664809460121647` to generate an official public `https://photos.app.goo.gl/...` short link for one or more media keys.

---

### `CreateAlbum()`

```go
func (c *Client) CreateAlbum(ctx context.Context, albumName string, mediaKeys []string) (*ShareInfo, error)
```

Creates a new shared album containing the specified media keys.

---

### `ImportSharedMedia()`

```go
func (c *Client) ImportSharedMedia(ctx context.Context, mediaKeys []string, authKey, albumKey string) (*SaveResult, error)
```

Saves shared media items into the user's Google Photos account using Google Pixel XL hardware spoofing (unlimited original quality backup status).

---

### `FindMediaByHash()`

```go
func (c *Client) FindMediaByHash(ctx context.Context, sha1Bytes []byte) (*ExistResult, error)
```

Performs a fast deduplication check by querying Google Photos with a 20-byte SHA-1 hash to verify if a file already exists in the account.

---

### `DeleteByMediaKey()`

```go
func (c *Client) DeleteByMediaKey(ctx context.Context, mediaKey string) error
```

Convenience method that resolves the item's raw deduplication key, moves it to trash, and permanently deletes it immediately.

---

### `MoveToTrash()`

```go
func (c *Client) MoveToTrash(ctx context.Context, dedupKey string) error
```

Moves an item to trash using its URL-safe base64 deduplication key.

---

### `DeletePermanently()`

```go
func (c *Client) DeletePermanently(ctx context.Context, dedupKey string) error
```

Permanently expunges an item from trash using its URL-safe base64 deduplication key.

---

---

## Web Client & Cookie Authentication (GPWC)

For web-based operations, cookie-authenticated workflows, and importing Google Drive files directly into Google Photos, use `core.WebClient`.

### Cookie Management

#### `ParseCookies()`

```go
func ParseCookies(raw string) (Cookie, error)
```

Parses raw cookie data automatically from Netscape `cookies.txt` format, JSON export format, or raw `Cookie: ...` header strings.

#### `CheckCookieStatus()`

```go
func CheckCookieStatus(cookie Cookie) (*CookieStatus, error)
```

Performs a live validation check against `photos.google.com/?_t=...` and extracts the associated Google account email (`"oPEP7c"`).

---

### `NewWebClient()`

```go
func NewWebClient(cookie Cookie) (*WebClient, error)
```

Initializes a Google Photos Web Client with the parsed cookies, automatically fetching required session tokens (`f.sid`, `bl`, `at`) from `photos.google.com`.

---

### Web Client Methods

#### `ImportFromDrive()`

```go
func (c *WebClient) ImportFromDrive(driveFileID string, mimeType string, cleanup bool) (*DriveImportResult, error)
```

Imports a Google Drive file into Google Photos using internal `SusGud` batchexecute RPC, automatically fetches the direct download URL via `VrseUb`, and optionally cleans up the imported file from trash.

**Parameters:**

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `driveFileID` | `string` | *required* | The Google Drive file ID. |
| `mimeType` | `string` | `"video/*"` | MIME type of the file. |
| `cleanup` | `bool` | `false` | If `true`, permanently deletes the photo from library after import. |

**Returns:**

* `*core.DriveImportResult`: Struct containing `DriveFileID`, `MediaKey`, `DedupKey`, and direct `DownloadURL`.

---

#### `GetDownloadURL()` (Web)

```go
func (c *WebClient) GetDownloadURL(mediaKey string) (*DownloadInfo, error)
```

Retrieves direct download URL and deduplication key using web RPC `VrseUb` (`GetItemInfo`).

---

#### `CreateShareLink()` (Web)

```go
func (c *WebClient) CreateShareLink(mediaKey string) (*PublicShareLink, error)
```

#### `BatchImportFromDrive()` (Web)

```go
func (c *WebClient) BatchImportFromDrive(items []DriveBatchItem, cleanup bool, timeout time.Duration) (*DriveBatchImportResult, error)
```

Imports multiple Google Drive files in a single `SusGud` RPC request with proactive quota full detection (`STORAGE_QUOTA_EXCEEDED`).

---

#### `ResetAccount()` (Web)

```go
func (c *WebClient) ResetAccount(timeout time.Duration) (*AccountResetResult, error)
```

Paginates and moves all items in the library and archive to trash via `XwAOJf` and permanently purges trash via `e2FP6c`.

---

### Go Example: Cookie Validation, Batch Drive Import & Reset

```go
package main

import (
    "fmt"
    "log"
    "os"
    "time"

    "github.com/masudranaxpert/photos-reverse-engine/core"
)

func main() {
    rawCookies, err := os.ReadFile("cookies.txt")
    if err != nil {
        log.Fatalf("Failed to read cookies.txt: %v", err)
    }

    cookie, err := core.ParseCookies(string(rawCookies))
    if err != nil {
        log.Fatalf("Failed to parse cookies: %v", err)
    }

    webClient, err := core.NewWebClient(cookie)
    if err != nil {
        log.Fatalf("Failed to initialize web client: %v", err)
    }

    // Check storage quota
    quota, err := webClient.GetStorageQuota()
    if err == nil {
        fmt.Printf("Storage: %s (%.1f%% used)\n", quota.UsageText, quota.UsedPercent)
    }

    // Batch Import multiple Google Drive files
    batchRes, err := webClient.BatchImportFromDrive([]core.DriveBatchItem{
        {DriveFileID: "173o1kBve_...", MimeType: "video/x-matroska"},
        {DriveFileID: "1TjQP3B7gw...", MimeType: "video/x-matroska"},
    }, false, 120*time.Second)

    if err != nil {
        log.Fatalf("Batch import error: %v", err)
    }
    fmt.Printf("Imported %d items successfully!\n", batchRes.SuccessCount)

    // Complete account wipe / reset
    resetRes, err := webClient.ResetAccount(180 * time.Second)
    if err == nil {
        fmt.Printf("Account Reset: %d items deleted, trash emptied: %v\n", resetRes.TotalDeleted, resetRes.TrashEmptied)
    }
}
```

---

## Data Structures

### `DownloadInfo`

```go
type DownloadInfo struct {
    DownloadURL string `json:"download_url"`
    Filename    string `json:"filename"`
    FileSize    int64  `json:"file_size"`
    SHA1Hex     string `json:"sha1_hex"`
    DedupKey    string `json:"dedup_key"`
}
```

### `StorageQuota`

```go
type StorageQuota struct {
    UsageText    string  `json:"usage_text"`    // e.g. "9.3 GB of 15 GB used"
    UsedDisplay  string  `json:"used_display"`  // e.g. "9.3 GB"
    TotalDisplay string  `json:"total_display"` // e.g. "15 GB"
    UsedPercent  float64 `json:"used_percent"`  // e.g. 61.7
    FreePercent  float64 `json:"free_percent"`  // e.g. 38.3
    UsedBytes    int64   `json:"used_bytes"`    // in bytes
    TotalBytes   int64   `json:"total_bytes"`   // in bytes
}
```

### `DriveImportItemResult`

```go
type DriveImportItemResult struct {
    DriveFileID string `json:"drive_file_id"`
    MediaKey    string `json:"media_key"`
    DedupKey    string `json:"dedup_key"`
    DownloadURL string `json:"download_url,omitempty"`
    Width       int    `json:"width,omitempty"`
    Height      int    `json:"height,omitempty"`
    FileSize    int64  `json:"file_size,omitempty"`
    Status      int    `json:"status"` // 0=Success, 1=Processing, 3=Unsupported/Rejected, 8=Quota Exceeded
    Error       string `json:"error,omitempty"`
    RawItem     string `json:"raw_item,omitempty"`
}
```

### `DriveBatchImportResult`

```go
type DriveBatchImportResult struct {
    SuccessCount  int                     `json:"success_count"`
    FailedCount   int                     `json:"failed_count"`
    Items         []DriveImportItemResult `json:"items"`
    QuotaExceeded bool                    `json:"quota_exceeded"`
    ErrorMessage  string                  `json:"error_message,omitempty"`
    RawResponse   string                  `json:"raw_response,omitempty"`
}
```

### `AccountResetResult`

```go
type AccountResetResult struct {
    Success      bool   `json:"success"`
    TotalDeleted int    `json:"total_deleted"`
    TrashEmptied bool   `json:"trash_emptied"`
    Message      string `json:"message"`
}
```

### `CookieStatus`

```go
type CookieStatus struct {
    Valid   bool   `json:"valid"`
    Account string `json:"account,omitempty"`
    Message string `json:"message,omitempty"`
}
```

### `DriveImportResult`

```go
type DriveImportResult struct {
    DriveFileID string `json:"drive_file_id"`
    MediaKey    string `json:"media_key"`
    DedupKey    string `json:"dedup_key"`
    DownloadURL string `json:"download_url,omitempty"`
}
```

### `PublicShareLink`

```go
type PublicShareLink struct {
    ShareURL    string   `json:"share_url"`
    EnvelopeKey string   `json:"envelope_key"`
    AuthKey     string   `json:"auth_key"`
    MediaKeys   []string `json:"media_keys"`
}
```

### `ShareInfo`

```go
type ShareInfo struct {
    AlbumName     string   `json:"album_name"`
    AlbumMediaKey string   `json:"album_media_key"`
    MediaKeys     []string `json:"media_keys"`
}
```

### `SaveResult`

```go
type SaveResult struct {
    OriginalKeys []string `json:"original_keys"`
    NewKeys      []string `json:"new_keys"`
    Status       int      `json:"status"`
}
```

### `ExistResult`

```go
type ExistResult struct {
    Exists   bool   `json:"exists"`
    MediaKey string `json:"media_key,omitempty"`
}
```

---

## Concurrency & Performance

* **Goroutine Safety**: All client operations and token refreshes are protected by `sync.RWMutex`.
* **Context Cancellation**: Full support for `context.WithTimeout` and `context.WithCancel`.
* **Zero Allocation Protobuf**: Native wire-level encoding avoiding heavy reflection.
* **Zero External Dependencies**: Pure standard library Go implementation.

