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

### `PublicShareLink`

```go
type PublicShareLink struct {
    ShareURL string `json:"share_url"`
    MediaKey string `json:"media_key"`
    AuthKey  string `json:"auth_key"`
}
```

### `ShareInfo`

```go
type ShareInfo struct {
    Title     string   `json:"title"`
    ShareURL  string   `json:"share_url"`
    AuthKey   string   `json:"auth_key"`
    MediaKeys []string `json:"media_keys"`
}
```

### `SaveResult`

```go
type SaveResult struct {
    Status  int      `json:"status"`
    Success bool     `json:"success"`
    NewKeys []string `json:"new_keys"`
}
```

### `ExistResult`

```go
type ExistResult struct {
    Exists   bool   `json:"exists"`
    Sha1Hex  string `json:"sha1_hex"`
    MediaKey string `json:"media_key"`
    DedupKey string `json:"dedup_key"`
}
```

---

## Concurrency & Performance

* **Goroutine Safety**: All client operations and token refreshes are protected by `sync.RWMutex`.
* **Context Cancellation**: Full support for `context.WithTimeout` and `context.WithCancel`.
* **Zero Allocation Protobuf**: Native wire-level encoding avoiding heavy reflection.
