# Quickstart Guide

Get started with **Photos Engine** using **Python**, **Go**, or the **CLI**.

---

## 1. Prerequisites

- **Python**: 3.9+ (if using Python / CLI).
- **Go**: 1.26+ (if using native Go package or recompiling the core).
- A valid Google Photos Master Token in `AUTH_DATA` format:
  ```text
  oauth2_rt_1/0...:49029607:androidId
  ```

---

## 2. Installation

### For Python & CLI:
```bash
cd photos_engine
pip install -e .
```

To build or recompile the native Go core shared library on your machine:
```bash
python build_engine.py
```

### For Go:
```bash
go get github.com/masudranaxpert/photos-reverse-engine
```

---

## 3. Environment Configuration

Create a `.env` file in your root workspace or project directory:

```ini
AUTH_DATA="oauth2_rt_1/0aBcDeFgHiJkLmNoPqRsTuVwXyZ...:49029607:3b8909187319981297"
```

Both Python and Go clients automatically read `AUTH_DATA` from `.env` or system environment variables. You can also pass credentials explicitly.

---

## 4. Using in Python

```python
import photos_engine

# 1. Check current OAuth2 Bearer Token
token = photos_engine.get_token()
print(f"Token: {token[:20]}...")

# 2. Check if a local file is already in Google Photos
status = photos_engine.is_file_in_library("vacation.mp4")
if status.exists:
    print(f"File already in library! Media Key: {status.media_key}")
else:
    print("File not found in library.")

# 3. Create a public share link (photos.app.goo.gl)
if status.exists:
    link = photos_engine.create_share_link(status.media_key)
    print(f"Public Link: {link.share_url}")

# 4. Fetch direct original quality stream download link
info = photos_engine.get_download_url("MEDIA_KEY")
print(f"Download URL: {info.download_url}")
```

---

## 5. Using in Go

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

	// 1. Initialize Client (reads AUTH_DATA from env if empty)
	client, err := core.NewClient(os.Getenv("AUTH_DATA"))
	if err != nil {
		log.Fatalf("Init failed: %v", err)
	}

	// 2. Fetch OAuth2 Bearer Token
	token, err := client.GetToken(ctx)
	if err != nil {
		log.Fatalf("Token failed: %v", err)
	}
	fmt.Printf("Token: %s...\n", token[:25])

	// 3. Create a public share link (photos.app.goo.gl)
	link, err := client.CreateShareLink(ctx, []string{"MEDIA_KEY_1"})
	if err == nil {
		fmt.Printf("Share Link: %s\n", link.ShareURL)
	}

	// 4. Fetch direct download URL
	dl, err := client.GetDownloadURL(ctx, "MEDIA_KEY_1")
	if err == nil {
		fmt.Printf("File: %s (%d bytes)\n", dl.Filename, dl.FileSize)
		fmt.Printf("Stream URL: %s\n", dl.DownloadURL)
	}
}
```

---

## 6. Using the CLI

You can run any operation directly from your terminal:

```bash
# Get Bearer Token
photos-engine token

# Get Token formatted as JSON
photos-engine token --json

# Check local file existence by SHA-1 hash
photos-engine check vacation.mp4

# Create public share link for one or more media keys
photos-engine share AF1QipP... AF1QipM...

# Get original stream download URL
photos-engine download AF1QipP...

# Import a public shared album with Pixel XL spoofing
photos-engine import "https://photos.app.goo.gl/abcdef12345"

# Permanently delete a media item
photos-engine delete AF1QipP...
```
