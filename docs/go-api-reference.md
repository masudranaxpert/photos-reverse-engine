# Go API Reference

Complete reference for using the native Go core engine (`github.com/masudranaxpert/photos-reverse-engine/core`).

---

## Package Import

```go
import "github.com/masudranaxpert/photos-reverse-engine/core"
```

---

## Client Constructor

### `core.NewClient(authData string) (*core.Client, error)`
Initializes a new Google Photos client instance.
- **Parameters**: `authData`: The Master Token credential string in format `oauth2_rt_1/0...:49029607:androidId`. If empty, reads from the `AUTH_DATA` environment variable or `.env` file.
- **Returns**: `*core.Client` pointer, or an error if credentials are empty or invalid.

---

## Client Methods

### `client.GetToken(ctx context.Context) (string, error)`
Retrieves an active OAuth2 Bearer token (`ya29...`).
- **Thread-Safety**: Protected by `sync.RWMutex`.
- **Auto-Refresh**: Automatically checks token expiration and refreshes transparently with a 5-minute proactive buffer.

### `client.GetDownloadURL(ctx context.Context, mediaKey string) (*core.DownloadInfo, error)`
Fetches the original quality media download stream URL, original filename, exact byte size, SHA-1 checksum, and deduplication key.
- **Parameters**: `ctx`: Context for timeout/cancellation; `mediaKey`: Google Photos item media key.
- **Returns**: `*core.DownloadInfo` struct.

### `client.CreateShareLink(ctx context.Context, mediaKeys []string) (*core.PublicShareLink, error)`
Creates an official `https://photos.app.goo.gl/...` public share link for one or more media keys using endpoint `11663664809460121647`.
- **Parameters**: `mediaKeys`: Slice of media keys to share.
- **Returns**: `*core.PublicShareLink` struct containing `ShareURL`, `MediaKey`, and `AuthKey`.

### `client.CreateAlbum(ctx context.Context, albumName string, mediaKeys []string) (*core.ShareInfo, error)`
Creates a new shared album containing the specified media keys.
- **Parameters**: `albumName`: Name of the album; `mediaKeys`: Slice of media keys to include.
- **Returns**: `*core.ShareInfo` struct.

### `client.ImportSharedMedia(ctx context.Context, mediaKeys []string, authKey, albumKey string) (*core.SaveResult, error)`
Saves shared media items into the user's personal Google Photos library with Google Pixel XL hardware spoofing (unlimited original quality backup).
- **Parameters**: `mediaKeys`: Slice of item media keys; `authKey`: Shared album auth key; `albumKey`: Target album key (optional).
- **Returns**: `*core.SaveResult` with `Status` (2 = success) and `NewKeys`.

### `client.FindMediaByHash(ctx context.Context, sha1Bytes []byte) (*core.ExistResult, error)`
Performs a fast deduplication lookup to check if a file with the given 20-byte SHA-1 hash already exists in the user's account.
- **Parameters**: `sha1Bytes`: Exactly 20 bytes representing the SHA-1 hash of the file.
- **Returns**: `*core.ExistResult` (`Exists`, `MediaKey`, `DedupKey`).

### `client.MoveToTrash(ctx context.Context, dedupKey string) error`
Moves an active item to the trash bin using its URL-safe base64 deduplication key.

### `client.DeletePermanently(ctx context.Context, dedupKey string) error`
Permanently expunges an item from trash using its URL-safe base64 deduplication key.

### `client.DeleteByMediaKey(ctx context.Context, mediaKey string) error`
Convenience method that resolves the media key's deduplication key, moves it to trash, and permanently deletes it in a single atomic sequence.

---

## Data Structures

```go
type DownloadInfo struct {
    DownloadURL string `json:"download_url"`
    Filename    string `json:"filename"`
    FileSize    int64  `json:"file_size"`
    SHA1Hex     string `json:"sha1_hex"`
    DedupKey    string `json:"dedup_key"`
}

type PublicShareLink struct {
    ShareURL string `json:"share_url"`
    MediaKey string `json:"media_key"`
    AuthKey  string `json:"auth_key"`
}

type ShareInfo struct {
    Title     string   `json:"title"`
    ShareURL  string   `json:"share_url"`
    AuthKey   string   `json:"auth_key"`
    MediaKeys []string `json:"media_keys"`
}

type SaveResult struct {
    Status  int      `json:"status"`
    Success bool     `json:"success"`
    NewKeys []string `json:"new_keys"`
}

type ExistResult struct {
    Exists   bool   `json:"exists"`
    Sha1Hex  string `json:"sha1_hex"`
    MediaKey string `json:"media_key"`
    DedupKey string `json:"dedup_key"`
}
```

---

## Concurrency & Performance

- **Goroutine-Safe**: `*core.Client` is safe for concurrent use across multiple goroutines.
- **Context-Aware**: All RPC calls accept `context.Context` for fine-grained timeouts and cancellations.
- **Transparent Gzip**: Responses from `photosdata-pa.googleapis.com` are decompressed automatically with zero stream truncation.
