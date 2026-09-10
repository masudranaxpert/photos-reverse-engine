---
title: CLI Manual
description: Command-line reference manual for the photos-engine CLI utility
icon: lucide/terminal
---

# CLI Reference

The `photos-engine` command-line tool provides terminal access to all core operations.

---

## Global Options

```text
usage: photos-engine [-h] [--auth-data AUTH_DATA] [--json] {token,share,download,import,delete,check} ...
```

| Flag | Description |
| :--- | :--- |
| `-h, --help` | Show command help and exit |
| `-a, --auth-data` | Custom auth string (overrides `AUTH_DATA` env var) |
| `--json` | Format output as structured JSON |

---

## Commands

### `token`
Retrieves and outputs the active OAuth2 Bearer token (`ya29...`).

```bash
# Plain text output
photos-engine token

# JSON output
photos-engine token --json
```

**JSON Output Example**:
```json
{
  "token": "ya29.a0AdMD6..."
}
```

---

### `share`
Generates a public `https://photos.app.goo.gl/...` link for one or more media keys.

```bash
photos-engine share AF1QipM7Z... AF1QipPX1...
```

**Options**:
- `--json`: Outputs JSON with `share_url`, `media_key`, `auth_key`, and `num_items`.

**Example Output**:
```text
Share URL : https://photos.app.goo.gl/9xabcXYZ12345
Media Key : AF1QipODqf2...
Auth Key  : A3_...
```

---

### `download`
Resolves direct original-quality download stream info for a media item.

```bash
photos-engine download AF1QipM7Z...
```

**Example Output**:
```text
Filename     : sample_video.mp4
File Size    : 10485760 bytes (10.00 MB)
SHA-1 Hash   : a94a8fe5ccb19ba61c4c0873d391e987982fbbd3
Dedup Key    : qUqP5cyx...
Download URL : https://video-downloads.googleusercontent.com/...
```

---

### `import`
Scrapes a public Google Photos shared link and imports all contained media items into your library with Pixel XL original quality backup spoofing.

```bash
photos-engine import "https://photos.app.goo.gl/9xabcXYZ12345"
```

**Options**:
- `--json`: Outputs full import results and imported media details.

---

### `delete`
Permanently deletes a photo or video by resolving its deduplication key and executing the Move-to-Trash -> DeletePermanently sequence.

```bash
photos-engine delete AF1QipM7Z...
```

---

### `check`
Computes the SHA-1 hash of a local file and checks if it already exists in your Google Photos library.

```bash
photos-engine check /path/to/my_video.mp4
```

**Example Output**:
```text
File Path    : /path/to/my_video.mp4
SHA-1 Hash   : 7110eda4d09e062aa5e4a390b0a572ac0d2c0220
In Library   : YES
Media Key    : AF1QipP_x...
Dedup Key    : cRDtpNC...
```

---

### `cookies-check`
Validates authentication cookies from a `cookies.txt` file against `photos.google.com` and retrieves the logged-in Google account email.

```bash
# Verify cookies from default cookies.txt
photos-engine cookies-check

# Specify custom cookies file path
photos-engine cookies-check --cookies-file /path/to/cookies.txt --json
```

**Example Output**:
```text
Session ID : default
Valid      : YES
Account    : user@gmail.com
Message    : Cookies are valid (Account: user@gmail.com).
```

---

### `drive-import`
Imports one or more files from Google Drive directly into Google Photos in a single batch RPC request, retrieves direct download URLs, and optionally moves them to trash upon completion.

```bash
# Import a single Google Drive file ID
photos-engine drive-import 1A2B3C4D5E6F7G8H9I0J

# Import multiple Google Drive files in a single batch
photos-engine drive-import 1A2B3C4D... 1TjQP3B... 1H2E0dw... -c cookies.txt

# Import with auto-cleanup (trash and purge) and custom timeout
photos-engine drive-import 1A2B3C... --cleanup --timeout 180 --json
```

**Options**:
- `--cleanup`: Move imported items to trash and permanently empty trash after resolving download URLs.
- `--timeout`: Timeout in seconds for the batch import operation (default: 120s).
- `--cookies-file`, `-c`: Path to Netscape or JSON cookies file.

**Example Output**:
```text
Success Count : 3
Failed Count  : 0
[1] 173o1kBve_... -> OK
    Media Key    : AF1QipMjDY09Q2fyOLRqbT9n67ChqorvTboeE2CeuYqP
    Dedup Key    : QleyGUKTgeHhG39OwuYv-JftvYM
    Download URL : https://photos.fife.usercontent.google.com/pw/...
    Resolution   : 1920x960
    File Size    : 7056840 bytes
[2] 1TjQP3B7gw... -> OK
    Media Key    : AF1QipM29VPaagOBq3zW_IMTith5S-oOVSKvuW2PUFyu
    Resolution   : 1920x1080
    File Size    : 13192743 bytes
```

---

### `reset-account`
Wipes the entire Google Photos library: enumerates all photos and videos (including archive), moves them in batches to trash, and permanently empties the trash.

> **Caution**: This operation is irreversible and permanently deletes all media in the account. The `--confirm` flag is strictly required.

```bash
# Reset library (requires explicit confirmation)
photos-engine reset-account -c cookies.txt --confirm

# Reset library with JSON output
photos-engine reset-account -c cookies.txt --confirm --json
```

**Example Output**:
```text
Success       : True
Total Deleted : 124 item(s)
Trash Emptied : True
Status        : Successfully removed 124 items from library and permanently emptied trash.
```

---

### `quota`
Fetches Google Photos account storage quota, breakdown percentages, used/total space, and byte limits.

```bash
# Fetch storage quota using default cookies.txt
photos-engine quota

# Specify custom cookies file and output JSON
photos-engine quota --cookies-file /path/to/cookies.txt --json
```

**Example Output**:
```text
Storage Quota : 9.3 GB of 15 GB used
Used Space    : 9.3 GB (61.7%)
Total Space   : 15 GB
Free Space    : 38.3% remaining
```


