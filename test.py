"""
Interactive test script to inspect raw SusGud RPC responses from Google Photos.
Demonstrates engine behavior on unsupported mime types (e.g. RAR archives) vs supported media.
"""

import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

# Ensure photos_engine is in sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from photos_engine import NativeWebClient
from photos_engine.models import DriveBatchItem


def load_client() -> NativeWebClient:
    """Initialize NativeWebClient from app database, env vars, or .env file."""
    # 1. Direct environment variable
    if cookies := os.getenv("GPWC_COOKIES") or os.getenv("COOKIES"):
        print("[auth] Using cookies from environment variable.")
        return NativeWebClient(cookies=cookies)

    # 2. SQLite database active session
    db_paths = [
        SCRIPT_DIR.parent / "data" / "app.db",
        SCRIPT_DIR / "data" / "app.db",
        Path("data/app.db"),
    ]
    for db_path in db_paths:
        if db_path.is_file():
            try:
                conn = sqlite3.connect(str(db_path))
                row = conn.cursor().execute(
                    "SELECT session_blob, raw_cookies, account_email FROM web_sessions WHERE is_active = 1 LIMIT 1"
                ).fetchone()
                if row:
                    blob, raw_cookies, email = row
                    print(f"[auth] Loaded active session for '{email}' from {db_path}")
                    if blob:
                        return NativeWebClient.from_blob(blob)
                    if raw_cookies:
                        return NativeWebClient(cookies=raw_cookies)
            except Exception as exc:
                print(f"[auth] Notice: could not read db {db_path}: {exc}")

    # 3. Search .env files
    env_paths = [
        SCRIPT_DIR / ".env",
        SCRIPT_DIR.parent / ".env",
    ]
    for env_path in env_paths:
        if env_path.is_file():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("COOKIES=") or line.startswith("GPWC_COOKIES="):
                    val = line.split("=", 1)[1].strip("'\"")
                    if val:
                        print(f"[auth] Loaded cookies from {env_path}")
                        return NativeWebClient(cookies=val)

    raise RuntimeError(
        "No active session found. Please ensure an active session exists in data/app.db "
        "or set GPWC_COOKIES environment variable."
    )


def print_section(title: str) -> None:
    """Print formatted section separator."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


async def test_import(
    client: NativeWebClient,
    drive_id: str,
    mime_type: str = "video/*",
    label: str = "",
) -> None:
    """Import a Drive file, print raw SusGud payload, and analyze status code."""
    print_section(f"TEST: {label or drive_id} (mime: '{mime_type}')")
    print(f"Target Drive File ID : {drive_id}")
    print(f"Specified Mime Type  : {mime_type}")

    # 1. Low-level BatchImportFromDrive to capture raw RPC payload
    print("\n>>> Calling batch_import_from_drive() via Go engine...")
    batch_res = client.batch_import_from_drive(
        items=[DriveBatchItem(drive_file_id=drive_id, mime_type=mime_type)],
        cleanup=False,
        timeout_ms=30000,
    )

    print("\n--- [SusGud Raw RPC Response] ---")
    if batch_res.raw_response:
        try:
            parsed = json.loads(batch_res.raw_response)
            print(json.dumps(parsed, indent=2))
        except Exception:
            print(batch_res.raw_response)
    else:
        print("(None captured)")
    print("---------------------------------")

    print("\n--- [Parsed Batch Result] ---")
    print(f"Success Count  : {batch_res.success_count}")
    print(f"Failed Count   : {batch_res.failed_count}")
    print(f"Quota Exceeded : {batch_res.quota_exceeded}")
    if batch_res.error_message:
        print(f"Error Message  : {batch_res.error_message}")

    for idx, item in enumerate(batch_res.items, start=1):
        print(f"\nItem #{idx}:")
        print(f"  Drive File ID : {item.drive_file_id}")
        print(f"  Status Code   : {item.status}")
        print(f"  Media Key     : {item.media_key or '(empty)'}")
        print(f"  Dedup Key     : {item.dedup_key or '(empty)'}")
        print(f"  Error Message : {item.error or '(none)'}")
        print(f"  Raw Item JSON : {item.raw_item or '(none)'}")

        # Explain status meaning
        print("\n  [Status Analysis]:")
        if item.status == 0 and item.media_key:
            print("  -> STATUS 0: Success. Google Photos accepted and imported the media.")
        elif item.status == 3:
            print("  -> STATUS 3: REJECTED by Google Photos.")
            print("     Google Photos inspects Drive file metadata or binary headers.")
            print("     Unsupported archive formats (.rar, .zip, .exe, etc.) return [drive_id, null, 3].")
        elif item.status == 8 or batch_res.quota_exceeded:
            print("  -> STATUS 8: Storage Quota Exceeded on destination Google account.")
        else:
            print(f"  -> STATUS {item.status}: Non-zero return status from Google SusGud RPC.")

    # 2. Test async single-item import to observe exception handling
    print("\n>>> Testing import_from_drive_async() behavior...")
    try:
        single_res = await client.import_from_drive_async(drive_id, mime_type=mime_type, timeout=30.0)
        print(f"Single Import Result: media_key={single_res.media_key}")
    except Exception as exc:
        print(f"Single Import Raised: {type(exc).__name__}: {exc}")


async def main() -> None:
    # Target drive ID: default to RAR file from user logs
    target_drive_id = "1NNVzoBzBeAg4FIOPijqJHkgxWJPxBtC7"
    target_mime = "video/*"

    # Command line overrides: python test.py [drive_id] [mime_type]
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) >= 1:
        target_drive_id = args[0].strip()
    if len(args) >= 2:
        target_mime = args[1].strip()

    client = load_client()

    # Test specified file
    await test_import(
        client,
        drive_id=target_drive_id,
        mime_type=target_mime,
        label="Target File Test",
    )

    # If testing the default RAR file without extra args, test different mime types to compare reaction
    if len(args) == 0:
        print_section("MIME TYPE VARIATION EXPERIMENT ON RAR ARCHIVE")
        mimes_to_test = ["application/x-rar", "application/octet-stream", "image/jpeg"]
        for mime in mimes_to_test:
            res = client.batch_import_from_drive(
                items=[DriveBatchItem(drive_file_id=target_drive_id, mime_type=mime)],
                timeout_ms=15000,
            )
            it = res.items[0] if res.items else None
            print(f"Mime: {mime:25} -> Status: {it.status if it else 'N/A'} | Raw: {it.raw_item if it else 'N/A'}")


if __name__ == "__main__":
    asyncio.run(main())
