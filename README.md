# photos-engine

<p align="center">
  <img src="https://img.shields.io/badge/Google%20Photos-Client%20Engine-4285F4?style=for-the-badge&logo=google-photos&logoColor=white" alt="Google Photos">
  <img src="https://img.shields.io/badge/Go%20Core-1.26+-00ADD8?style=for-the-badge&logo=go&logoColor=white" alt="Go">
  <img src="https://img.shields.io/badge/Python-3.9%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Architecture-C--ABI%20via%20ctypes-4EBA6F?style=for-the-badge" alt="Architecture">
  <a href="https://masudranaxpert.github.io/photos-reverse-engine/"><img src="https://img.shields.io/badge/Docs-Online-blue?style=for-the-badge&logo=googledocs&logoColor=white" alt="Docs"></a>
</p>

<p align="center">
  <b>High-performance Google Photos mobile client with a native Go core engine, direct in-process Python C-ABI bindings, and standalone CLI tool.</b>
  <br>
  <i>Engineered with the same high-performance in-process architecture as <a href="https://github.com/sardanioss/httpcloak">httpcloak</a>.</i>
</p>

---

## Highlights

- **Direct In-Process Execution**: The Go core engine is compiled into a native C-shared dynamic library (`lib/libphotos_engine-*.dll`), loaded into Python directly via `ctypes`. No subprocess overhead, no TCP proxies, no IPC latency.
- **Public Share Link Creation**: Generates official `https://photos.app.goo.gl/...` short share links for single or multiple media items.
- **Unlimited Pixel XL Backup Spoofing**: Simulates Google Pixel XL hardware parameters and headers to save and import shared media with unlimited original quality backup status.
- **Original Quality Stream Downloads**: Resolves direct streaming and download URLs, filenames, exact byte sizes, and SHA-1 checksums.
- **Account Storage Quota Inspection**: Parses Google Photos storage usage (`quotamanagement`), breakdown percentages, used/total space, and byte limits.
- **Fast Deduplication Pre-Check**: Checks if a local file already exists in your Google Photos library via SHA-1 hash before re-uploading.
- **Permanent Deletion**: Two-step expunge protocol (MoveToTrash followed by permanent deletion) using raw deduplication keys.
- **Unified CLI & Python API**: Full programmatic Python API alongside a fast, interactive command-line interface (`photos-engine`).

---

## Quickstart

### 1. Installation

```bash
cd photos_engine
pip install -e .
```

### 2. Configure Credentials

Create a `.env` file in your workspace root (see [`.env.example`](.env.example)):

```ini
AUTH_DATA="oauth2_rt_1/0...:49029607:3b8909187319981297"
```

### 3. Python Usage

```python
import photos_engine

# 1. Active OAuth2 Bearer Token (Auto-refreshed proactive caching)
token = photos_engine.get_token()
print("OAuth Token:", token[:25] + "...")

# 2. Generate Public Share Link (photos.app.goo.gl)
link = photos_engine.create_share_link(["AF1QipM...", "AF1QipN..."])
print("Share Link:", link.share_url)

# 3. Direct Original Quality Download Stream
dl = photos_engine.get_download_url("AF1QipM...")
print(f"File: {dl.filename} ({dl.file_size / (1024*1024):.2f} MB)")
print("Stream URL:", dl.download_url)

# 4. Import Shared Album with Pixel XL Spoofing
res = photos_engine.import_share_url("https://photos.app.goo.gl/abcdef12345")
print("Saved Media Keys:", res["import_result"].new_keys)

# 5. Check if Local File Already Exists in Library (by SHA-1)
check = photos_engine.is_file_in_library("vacation_video.mp4")
print("Exists in library?", check.exists)

# 6. Permanently Delete Media Item
success = photos_engine.delete_by_media_key("AF1QipM...")
print("Deleted:", success)

# 7. Check Google Photos Storage Quota
web_client = photos_engine.NativeWebClient(cookies=open("cookies.txt").read())
quota = web_client.get_storage_quota()
print(f"Storage: {quota.usage_text} ({quota.used_percent}% used)")

# 8. Batch Import Google Drive Files (with Storage Quota Detection)
batch_res = web_client.batch_import_from_drive([
    {"drive_file_id": "173o1kBve_RiXmI2ECCrfgRT91KG62Mz3", "mime_type": "video/x-matroska"},
    {"drive_file_id": "1TjQP3B7gw1tEkNPJbmalIbYDVWlxggXH", "mime_type": "video/x-matroska"},
])
if batch_res.quota_exceeded:
    print("Warning: Storage quota full! Google Photos rejected import.")
else:
    for item in batch_res.items:
        print(f"Imported: {item.drive_file_id} -> MediaKey: {item.media_key}")

# 9. Complete Account Library Reset / Wipe
reset_res = web_client.reset_account()
print(f"Account Reset: {reset_res.total_deleted} items removed, trash emptied: {reset_res.trash_emptied}")
```

### 4. Native Async Python Usage (Non-blocking Go Goroutines)

Just like [`httpcloak`](https://github.com/sardanioss/httpcloak), `photos_engine` includes a native C-ABI callback bridge (`_AsyncCallbackManager`) that runs operations inside Go goroutines and signals Python's `asyncio` event loop via thread-safe callbacks without locking Python's GIL or blocking the event loop:

```python
import asyncio
from photos_engine import NativeWebClient, PhotosEngineClient

async def main():
    # 1. Native async session status check (runs inside Go goroutine)
    status = await NativeWebClient.check_status_async("OSID=...; SID=...")
    print(f"Session valid: {status.valid}, Account: {status.account}")

    # 2. Native async Drive Import
    client = NativeWebClient(cookies="OSID=...; SID=...")
    result = await client.import_from_drive_async(
        drive_file_id="173o1kBve_RiXmI2ECCrfgRT91KG62Mz3",
        mime_type="video/mp4"
    )
    print(f"Imported Media Key: {result.media_key}")

    # 3. Native async Share Link Generation
    link = await client.create_share_link_async(result.media_key)
    print(f"Public Link: {link.share_url}")

    # 4. Native async Storage Quota check
    quota = await client.get_storage_quota_async()
    print(f"Used: {quota.used_display} / {quota.total_display}")

    client.close()

if __name__ == "__main__":
    asyncio.run(main())
```

---

### 5. Golang Usage

Add the package to your Go project:

```bash
go get github.com/masudranaxpert/photos-reverse-engine
```

```go
package main

import (
	"context"
	"fmt"
	"log"
	"os"

	"github.com/masudranaxpert/photos-reverse-engine/core"
)

func main() {
	ctx := context.Background()

	// 1. Initialize client (reads AUTH_DATA from env if empty)
	client, err := core.NewClient(os.Getenv("AUTH_DATA"))
	if err != nil {
		log.Fatalf("Client init failed: %v", err)
	}

	// 2. Active OAuth2 Bearer Token (auto-refreshing)
	token, err := client.GetToken(ctx)
	if err != nil {
		log.Fatalf("Token fetch failed: %v", err)
	}
	fmt.Println("Bearer Token:", token[:25]+"...")

	// 3. Generate Public Share Link (photos.app.goo.gl)
	shareLink, err := client.CreateShareLink(ctx, []string{"MEDIA_KEY_1", "MEDIA_KEY_2"})
	if err == nil {
		fmt.Println("Share URL:", shareLink.ShareURL)
	}

	// 4. Direct Original Quality Download Stream
	dlInfo, err := client.GetDownloadURL(ctx, "MEDIA_KEY_1")
	if err == nil {
		fmt.Printf("File: %s (Size: %d bytes)\n", dlInfo.Filename, dlInfo.FileSize)
		fmt.Println("Download URL:", dlInfo.DownloadURL)
	}

	// 5. Import Shared Media with Pixel XL Spoofing
	saveRes, err := client.ImportSharedMedia(ctx, []string{"MEDIA_KEY"}, "AUTH_KEY", "ALBUM_KEY")
	if err == nil {
		fmt.Println("Saved Keys:", saveRes.NewKeys)
	}

	// 6. Permanently Delete Media Item
	if err := client.DeleteByMediaKey(ctx, "MEDIA_KEY_1"); err == nil {
		fmt.Println("Item successfully deleted permanently!")
	}
}
```

---

## CLI Usage

`photos-engine` comes with a command-line interface:

```bash
# Get current OAuth2 Bearer token
photos-engine token
photos-engine token --json

# Create public share link
photos-engine share AF1QipM7Z... AF1QipPX1...

# Get direct download URL & metadata
photos-engine download AF1QipM7Z...

# Import public shared album with Pixel XL spoofing
photos-engine import "https://photos.app.goo.gl/..."

# Check if a file already exists by SHA-1 hash
photos-engine check video.mp4

# Permanently delete an item
photos-engine delete AF1QipM7Z...

# Check Google Photos account storage quota
photos-engine quota -c cookies.txt
photos-engine quota -c cookies.txt --json

# Import one or multiple Google Drive files in a single batch
photos-engine drive-import 173o1kBve_... 1TjQP3B7g... -c cookies.txt

# Reset / wipe Google Photos library completely and empty trash
photos-engine reset-account -c cookies.txt --confirm
```

---

## Architecture

```text
┌──────────────────────────────────────────────────────────┐
│                 Python Application / CLI                 │
├──────────────────────────────────────────────────────────┤
│             ctypes FFI Bridge (client.py)                │
├──────────────────────────────────────────────────────────┤
│         C-Shared ABI Exports (core/cshared/main.go)      │
├──────────────────────────────────────────────────────────┤
│                       Go Core Engine                     │
│  - Zero-Dependency Protobuf Wire Parser (proto.go)       │
│  - TokenManager with Proactive Auto-Refresh (auth.go)    │
│  - Pixel XL Headers & Hardware Profile (client.go)       │
│  - High-Speed Network Engine with Gzip Decompression     │
└──────────────────────────────────────────────────────────┘
```

### Performance Comparison

| Approach | Latency / Call | Process Memory | Binary Size | Port Binding |
| :--- | :--- | :--- | :--- | :--- |
| **Subprocess CLI (`.exe`)** | ~120 ms | High (forks new process) | ~15 MB per tool | None |
| **Local Proxy Server** | ~20–40 ms | High (background daemon) | ~30 MB | Required |
| **`photos-engine` (C-ABI)** | **< 0.5 ms** | **Low (shared process)** | **Single `.dll`** | **None** |

---

## Documentation

Online documentation is hosted at: **[https://masudranaxpert.github.io/photos-reverse-engine/](https://masudranaxpert.github.io/photos-reverse-engine/)**

Source markdown files are available in the [`docs/`](docs/) directory:

- [**Overview & Architecture**](docs/index.md)
- [**Quickstart Guide**](docs/quickstart.md)
- [**Python API Reference**](docs/api-reference.md)
- [**Go API Reference**](docs/go-api-reference.md)
- [**CLI Manual**](docs/cli-reference.md)
- [**Reverse Engineering & Protobuf Specifications**](docs/reverse-engineering.md)
- [**C-ABI & Low-Level Design**](docs/architecture.md)
- [**Development & Contributing**](docs/contributing.md)

---

## Rebuilding the Native Engine

To recompile the Go core for your local platform:

```bash
python build_engine.py
```

The script automatically detects the local OS, architecture, and available C compilers (`llvm-mingw`, `gcc`, or `clang`) and places the compiled binary directly into `photos_engine/lib/`.

---

## License

Distributed under the [MIT License](LICENSE).
