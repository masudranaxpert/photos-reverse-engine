# Quickstart Guide

Get started with **Photos Engine** in minutes.

---

## 1. Prerequisites

- Python 3.9 or newer.
- A valid Google Photos Master Token or OAuth2 token string in `AUTH_DATA` format:
  ```text
  oauth2_rt_1/0...:49029607:androidId
  ```

---

## 2. Installation

Install the package directly into your virtual environment:

```bash
cd photos_engine
pip install -e .
```

To re-compile or build the native Go core shared library on your machine:
```bash
python build_engine.py
```

---

## 3. Environment Configuration

Create a `.env` file in your root workspace or working directory:

```ini
AUTH_DATA="oauth2_rt_1/0aBcDeFgHiJkLmNoPqRsTuVwXyZ...:49029607:3b8909187319981297"
```

The engine will automatically read `AUTH_DATA` from `.env` or system environment variables. You can also pass `auth_data` explicitly to the constructor or CLI arguments.

---

## 4. First Python Script

```python
import photos_engine

# 1. Check current OAuth2 Bearer Token
token = photos_engine.get_token()
print(f"Token: {token[:20]}...")

# 2. Check if a local video or picture is already in Google Photos
status = photos_engine.is_file_in_library("vacation.mp4")
if status.exists:
    print(f"File already in library! Media Key: {status.media_key}")
else:
    print("File not found in library.")

# 3. Create a public share link (photos.app.goo.gl)
if status.exists:
    link = photos_engine.create_share_link(status.media_key)
    print(f"Public Link: {link.share_url}")
```

---

## 5. First CLI Run

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
```
