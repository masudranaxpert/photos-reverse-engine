# Google Photos Mobile API Reverse Engineering

This document details the reverse-engineered wire protocol, endpoints, protobuf schemas, and device spoofing headers discovered during the analysis of official Google Photos Android releases.

---

## 1. Authentication Protocol

### Master Token Exchange
Google Photos for Android does not use standard browser OAuth consent screens. Instead, it exchanges a persistent **Master Token** (or OAuth refresh token) for short-lived Bearer tokens scoped to the Google Photos internal data API (`photosdata-pa.googleapis.com`).

- **Endpoint**: `POST https://android.clients.google.com/auth`
- **User-Agent**: `GoogleAuth/1.4 (Pixel XL PQ3B.190801.11070909)`
- **Request Form Data**:
  ```ini
  accountType=HOSTED_OR_GOOGLE
  Email=<account_email>
  has_permission=1
  EncryptedPasswd=<master_token>
  service=oauth2:https://www.googleapis.com/auth/photos https://www.googleapis.com/auth/photos.native
  source=android
  androidId=<hex_android_id>
  app=com.google.android.apps.photos
  client_sig=38918a453d07199354f8b19af05ec6562ced5788
  callerPkg=com.google.android.apps.photos
  callerSig=38918a453d07199354f8b19af05ec6562ced5788
  ```
- **Response**: Key-value pairs containing `Auth=ya29.a0...` and `Expiry=...`.

---

## 2. API Endpoints & Request Headers

Google Photos mobile apps communicate with `photosdata-pa.googleapis.com` using binary Protobuf payloads over HTTP/2.

### Standard Request Headers
```http
POST /<rpc_category>/<rpc_id> HTTP/2
Host: photosdata-pa.googleapis.com
User-Agent: com.google.android.apps.photos/49029607 (Linux; U; Android 9; en_US; Pixel XL; Build/PQ2A.190205.001; Cronet/127.0.6510.5) (gzip)
Authorization: Bearer ya29.a0...
Content-Type: application/x-protobuf
Accept-Encoding: gzip
x-goog-ext-173412678-bin: CgcIAhClARgC
x-goog-ext-174067345-bin: CgIIAg==
```

> **Important (Gzip Decompression)**: In Go, setting `req.Header.Set("Accept-Encoding", "gzip")` explicitly disables standard `http.Transport` auto-decompression. The response must be wrapped in `gzip.NewReader(resp.Body)` whenever `Content-Encoding: gzip` is present.

---

## 3. Public Share Link Endpoint (`photos.app.goo.gl`)

The native Android app generates public share links by calling endpoint `11663664809460121647`:

- **Endpoint**: `https://photosdata-pa.googleapis.com/6439526531001121323/11663664809460121647`

### Request Protobuf Structure:
- **Field 3**: Envelope options sub-message:
  - Subfield 1: `1`
  - Subfield 2: `1`
  - Subfield 4: `1`
  - Subfield 5: `1`
- **Field 4**: Media item array (repeated submessage for each item):
  - Subfield 3 -> Subfield 1 -> Subfield 1: `media_key` (e.g. `AF1Qip...`)
- **Field 8**: Unix timestamp in milliseconds.
- **Field 9**: Repeated varint `[3, 1, 2, 5]` (link access permissions).
- **Field 10**: Static 131-byte binary read mask defining returned fields.

### Response Protobuf Structure:
- **Field 1**: Envelope key (e.g. `AF1QipODqf2...`)
- **Field 2**: Public short link (e.g. `https://photos.app.goo.gl/9xabc...`)
- **Field 5**: Internal auth key

---

## 4. Unlimited Original Quality Save / Backup (Pixel XL Spoofing)

Original Google Pixel devices (codename `marlin`) retain lifetime unlimited Google Photos backups in original quality. By mimicking the Android client application ID and hardware identifiers during save operations:

- **Endpoint**: `https://photosdata-pa.googleapis.com/6439526531001121323/16499878235777771746`
- **Hardware Profile**:
  - Device: `Google Pixel XL`
  - OS: `Android 9 (Pie)`
  - Build ID: `PQ2A.190205.001`
  - Client Version: `com.google.android.apps.photos/49029607`
- **Protobuf Payload**:
  - Submessage 1: Target shared album auth key and item media keys.
  - Submessage 2: Flag `1` (original quality preserve).

When successfully processed, the server returns status code `2` with new persistent media keys placed in the user's primary library.

---

## 5. Permanent Deletion Sequence

Google Photos prevents directly deleting active items permanently via API. Calling permanent deletion on an active item yields `HTTP 500` or `INVALID_ARGUMENT`.

### Two-Step Protocol:
1. **Move to Trash**:
   - Call deletion RPC with action `1` (`MoveToTrash`).
   - Include client metadata in Field 9.
2. **Delete Permanently**:
   - Convert item SHA-1 hash into raw deduplication key (`base64UrlSafe(sha1_bytes).TrimRight("=")`).
   - Call deletion RPC with action `2` (`DeletePermanently`).
   - Clear metadata field (empty).

The item is then expunged immediately without remaining in the 60-day trash retention bin.
