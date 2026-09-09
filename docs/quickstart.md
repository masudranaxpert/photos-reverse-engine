# Quickstart Guide

Get up and running with **Photos Engine** in minutes using **Python**, **Go**, or the **CLI**.

---

## Prerequisites

- **Python**: 3.9+ (for Python library and CLI)
- **Go**: 1.26+ (for native Go engine or recompiling)
- A valid Google Photos Master Token in `AUTH_DATA` format:
  ```text
  oauth2_rt_1/0...:49029607:androidId
  ```

---

## Installation

=== "Python & CLI"

    Install the package in editable mode:
    ```bash
    cd photos_engine
    pip install -e .
    ```

    To build or recompile the Go core dynamic library locally:
    ```bash
    python build_engine.py
    ```

=== "Golang"

    Add the Go package to your `go.mod`:
    ```bash
    go get github.com/masudranaxpert/photos-reverse-engine
    ```

---

## Environment Configuration

Create a `.env` file in your working directory (see `.env.example`):

```ini
AUTH_DATA="oauth2_rt_1/0...:49029607:3b8909187319981297"
```

!!! tip "Automatic Credential Resolution"
    Both Python and Go clients automatically look for `AUTH_DATA` in your local `.env` file or environment variables. You can also pass credentials explicitly into client constructors.

---

## Basic Usage

Select your preferred language:

=== "Python"

    ```python
    import photos_engine

    # 1. Fetch active OAuth2 Bearer token
    token = photos_engine.get_token()
    print("OAuth Token:", token[:25] + "...")

    # 2. Check if a local file exists in Google Photos (by SHA-1)
    status = photos_engine.is_file_in_library("vacation.mp4")
    if status.exists:
        print(f"Already in library! Media Key: {status.media_key}")

    # 3. Create a public share link (photos.app.goo.gl)
    link = photos_engine.create_share_link(status.media_key)
    print("Public Share URL:", link.share_url)

    # 4. Fetch direct original quality download stream
    info = photos_engine.get_download_url("MEDIA_KEY")
    print("Stream URL:", info.download_url)
    ```

=== "Golang"

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

    	// 1. Initialize client
    	client, err := core.NewClient(os.Getenv("AUTH_DATA"))
    	if err != nil {
    		log.Fatalf("Init failed: %v", err)
    	}

    	// 2. Fetch active OAuth2 Bearer token
    	token, err := client.GetToken(ctx)
    	if err != nil {
    		log.Fatalf("Token failed: %v", err)
    	}
    	fmt.Println("Bearer Token:", token[:25]+"...")

    	// 3. Create a public share link
    	shareLink, err := client.CreateShareLink(ctx, []string{"MEDIA_KEY_1"})
    	if err == nil {
    		fmt.Println("Share URL:", shareLink.ShareURL)
    	}

    	// 4. Fetch direct download URL & metadata
    	dl, err := client.GetDownloadURL(ctx, "MEDIA_KEY_1")
    	if err == nil {
    		fmt.Printf("File: %s (%d bytes)\n", dl.Filename, dl.FileSize)
    		fmt.Println("Download URL:", dl.DownloadURL)
    	}
    }
    ```

=== "CLI"

    ```bash
    # Get active OAuth2 Bearer token
    photos-engine token
    photos-engine token --json

    # Check local file existence by SHA-1 hash
    photos-engine check vacation.mp4

    # Create public share link (photos.app.goo.gl)
    photos-engine share AF1QipP... AF1QipM...

    # Get direct stream download URL & metadata
    photos-engine download AF1QipP...

    # Import shared album with Pixel XL backup spoofing
    photos-engine import "https://photos.app.goo.gl/abcdef12345"

    # Permanently delete a media item
    photos-engine delete AF1QipP...
    ```
