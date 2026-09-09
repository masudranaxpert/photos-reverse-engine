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
