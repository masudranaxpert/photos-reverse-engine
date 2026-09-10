#!/usr/bin/env python3
"""
Command Line Interface (CLI) for photos_engine.
Provides command-line utilities to interact with Google Photos via native Go core.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List

from photos_engine import (
    Client,
    NativeWebClient,
    create_share_link,
    delete_by_media_key,
    get_download_url,
    get_token,
    import_share_url,
    is_file_in_library,
)


def _cmd_token(args):
    """Retrieve and print active OAuth2 Bearer token."""
    token = get_token(auth_data=args.auth_data)
    if args.json:
        print(json.dumps({"token": token}, indent=2))
    else:
        print(token)


def _cmd_share(args):
    """Create public share link for media keys."""
    keys: List[str] = args.keys
    if not keys:
        print("Error: At least one media key is required.", file=sys.stderr)
        sys.exit(1)

    link = create_share_link(keys, auth_data=args.auth_data)
    if args.json:
        print(json.dumps({
            "share_url": link.share_url,
            "media_key": link.media_key,
            "auth_key": link.auth_key,
            "num_items": len(keys)
        }, indent=2))
    else:
        print(f"Share URL : {link.share_url}")
        print(f"Media Key : {link.media_key}")
        if link.auth_key:
            print(f"Auth Key  : {link.auth_key}")


def _cmd_download(args):
    """Fetch direct stream download link for media key."""
    info = get_download_url(args.media_key, auth_data=args.auth_data)
    if args.json:
        print(json.dumps({
            "download_url": info.download_url,
            "filename": info.filename,
            "file_size": info.file_size,
            "sha1_hash": info.sha1_hash,
            "dedup_key": info.dedup_key,
        }, indent=2))
    else:
        print(f"Filename     : {info.filename}")
        print(f"File Size    : {info.file_size} bytes ({info.file_size / (1024*1024):.2f} MB)")
        print(f"SHA-1 Hash   : {info.sha1_hash}")
        print(f"Dedup Key    : {info.dedup_key}")
        print(f"Download URL : {info.download_url}")


def _cmd_import(args):
    """Import shared album into account with Pixel XL spoofing."""
    print(f"Importing shared link: {args.share_url} ...")
    res = import_share_url(args.share_url, auth_data=args.auth_data)
    
    import_res = res["import_result"]
    if args.json:
        print(json.dumps({
            "success": import_res.success,
            "status": import_res.status,
            "new_keys": import_res.new_keys,
            "num_imported": len(import_res.new_keys),
            "media_items": [
                {
                    "media_key": m.media_key,
                    "download_url": m.download_url,
                    "width": m.width,
                    "height": m.height,
                }
                for m in res["shared_media"]
            ]
        }, indent=2))
    else:
        print(f"Import Status: {'Success' if import_res.success else 'Failed'} (Status Code: {import_res.status})")
        print(f"Items Saved  : {len(import_res.new_keys)}")
        if import_res.new_keys:
            print("Saved Keys   :")
            for k in import_res.new_keys:
                print(f"  - {k}")


def _cmd_delete(args):
    """Delete media item by media key."""
    success = delete_by_media_key(args.media_key, auth_data=args.auth_data)
    if args.json:
        print(json.dumps({"media_key": args.media_key, "deleted": success}, indent=2))
    else:
        if success:
            print(f"Successfully permanently deleted media: {args.media_key}")
        else:
            print(f"Failed to delete media: {args.media_key}", file=sys.stderr)
            sys.exit(1)


def _cmd_check(args):
    """Check if local file exists in Google Photos library by SHA-1 hash."""
    if not os.path.exists(args.file_path):
        print(f"Error: File not found: {args.file_path}", file=sys.stderr)
        sys.exit(1)

    result = is_file_in_library(args.file_path, auth_data=args.auth_data)
    if args.json:
        print(json.dumps({
            "file": args.file_path,
            "exists": result.exists,
            "sha1": result.sha1_hash,
            "media_key": result.media_key,
            "dedup_key": result.dedup_key,
        }, indent=2))
    else:
        print(f"File Path    : {args.file_path}")
        print(f"SHA-1 Hash   : {result.sha1_hash}")
        print(f"In Library   : {'YES' if result.exists else 'NO'}")
        if result.exists:
            print(f"Media Key    : {result.media_key}")
            print(f"Dedup Key    : {result.dedup_key}")


def _read_cookies(path_or_str: str) -> str:
    p = Path(path_or_str)
    if p.is_file():
        return p.read_text(encoding="utf-8")
    return path_or_str


def _cmd_cookies_check(args):
    """Verify stored cookies validity and retrieve logged-in account email."""
    cookies_data = _read_cookies(args.cookies_file)
    status = NativeWebClient.check_status(cookies_data)
    if args.json:
        print(json.dumps({
            "valid": status.valid,
            "account": status.account,
            "message": status.message,
        }, indent=2))
    else:
        print(f"Valid      : {'YES' if status.valid else 'NO'}")
        print(f"Account    : {status.account or 'N/A'}")
        print(f"Message    : {status.message}")
    if not status.valid:
        sys.exit(1)


def _cmd_drive_import(args):
    """Import Google Drive file(s) into Google Photos and fetch download URL(s)."""
    cookies_data = _read_cookies(args.cookies_file)
    client = NativeWebClient(cookies=cookies_data)
    try:
        drive_ids = args.drive_file_ids
        print(f"Importing {len(drive_ids)} Drive file(s) ...")
        res = client.batch_import_from_drive(
            items=[{"drive_file_id": d_id, "mime_type": "video/*"} for d_id in drive_ids],
            cleanup=args.cleanup,
            timeout_ms=args.timeout * 1000 if hasattr(args, "timeout") and args.timeout else 120000,
        )

        if res.quota_exceeded:
            print("[CRITICAL] Google Photos storage is FULL! (PhotosWebImportDriveItemsFailure)", file=sys.stderr)

        if args.json:
            print(json.dumps({
                "success_count": res.success_count,
                "failed_count": res.failed_count,
                "quota_exceeded": res.quota_exceeded,
                "error_message": res.error_message,
                "items": [
                    {
                        "drive_file_id": it.drive_file_id,
                        "media_key": it.media_key,
                        "dedup_key": it.dedup_key,
                        "download_url": it.download_url,
                        "width": it.width,
                        "height": it.height,
                        "file_size": it.file_size,
                        "status": it.status,
                        "error": it.error,
                    }
                    for it in res.items
                ],
            }, indent=2))
        else:
            print(f"Success Count : {res.success_count}")
            print(f"Failed Count  : {res.failed_count}")
            if res.quota_exceeded:
                print("Quota Status  : EXCEEDED (Storage full)")
            for idx, it in enumerate(res.items, 1):
                status_str = "OK" if it.status == 0 and it.media_key else f"FAILED ({it.error})"
                print(f"[{idx}] {it.drive_file_id} -> {status_str}")
                if it.media_key:
                    print(f"    Media Key    : {it.media_key}")
                    print(f"    Dedup Key    : {it.dedup_key}")
                    print(f"    Download URL : {it.download_url or 'N/A'}")
                    if it.width and it.height:
                        print(f"    Resolution   : {it.width}x{it.height}")
                    if it.file_size:
                        print(f"    File Size    : {it.file_size} bytes")
    finally:
        client.close()


def _cmd_reset_account(args):
    """Clear all photos/videos from Google Photos library and permanently empty trash."""
    if not args.confirm:
        print("Error: Library reset will permanently DELETE all media in this Google account!", file=sys.stderr)
        print("To proceed, you must pass the --confirm flag: photos-engine reset-account --confirm", file=sys.stderr)
        sys.exit(1)

    cookies_data = _read_cookies(args.cookies_file)
    client = NativeWebClient(cookies=cookies_data)
    try:
        print("Starting Google Photos account reset & complete library wipe...")
        res = client.reset_account(timeout_ms=180000)
        if args.json:
            print(json.dumps({
                "success": res.success,
                "total_deleted": res.total_deleted,
                "trash_emptied": res.trash_emptied,
                "message": res.message,
            }, indent=2))
        else:
            print(f"Success       : {res.success}")
            print(f"Total Deleted : {res.total_deleted} item(s)")
            print(f"Trash Emptied : {res.trash_emptied}")
            print(f"Status        : {res.message}")
    finally:
        client.close()


def _cmd_quota(args):
    """Fetch and display Google Photos account storage quota."""
    cookie_path = Path(args.cookies_file)
    if not cookie_path.exists():
        print(f"Error: Cookies file not found: {args.cookies_file}", file=sys.stderr)
        sys.exit(1)

    cookies_text = cookie_path.read_text(encoding="utf-8")
    client = NativeWebClient(cookies=cookies_text)
    try:
        quota = client.get_storage_quota()
        if args.json:
            print(json.dumps({
                "usage_text": quota.usage_text,
                "used_display": quota.used_display,
                "total_display": quota.total_display,
                "used_percent": quota.used_percent,
                "free_percent": quota.free_percent,
                "used_bytes": quota.used_bytes,
                "total_bytes": quota.total_bytes,
            }, indent=2))
        else:
            print(f"Storage Quota : {quota.usage_text}")
            print(f"Used Space    : {quota.used_display} ({quota.used_percent}%)")
            print(f"Total Space   : {quota.total_display}")
            print(f"Free Space    : {quota.free_percent}% remaining")
    finally:
        client.close()


def main():
    """Main CLI entry point."""
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument(
        "--auth-data",
        "-a",
        default="",
        help="Custom master token / oauth auth_data string (defaults to AUTH_DATA env var)",
    )
    common_parser.add_argument(
        "--json",
        action="store_true",
        help="Format output as JSON",
    )

    parser = argparse.ArgumentParser(
        prog="photos-engine",
        description="High-performance Google Photos CLI powered by native Go core engine.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[common_parser],
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: token
    subparsers.add_parser("token", help="Get active OAuth2 Bearer token", parents=[common_parser])

    # Command: share
    p_share = subparsers.add_parser("share", help="Create public share link (photos.app.goo.gl)", parents=[common_parser])
    p_share.add_argument("keys", nargs="+", help="One or more media keys to share")

    # Command: download
    p_dl = subparsers.add_parser("download", help="Get direct stream download URL and file metadata", parents=[common_parser])
    p_dl.add_argument("media_key", help="Media key of the photo/video")

    # Command: import
    p_imp = subparsers.add_parser("import", help="Import shared album/link with Pixel XL backup spoofing", parents=[common_parser])
    p_imp.add_argument("share_url", help="Public Google Photos share URL")

    # Command: delete
    p_del = subparsers.add_parser("delete", help="Permanently delete a media item", parents=[common_parser])
    p_del.add_argument("media_key", help="Media key to permanently delete")

    # Command: check
    p_chk = subparsers.add_parser("check", help="Check if a local file exists in account by SHA-1 hash", parents=[common_parser])
    p_chk.add_argument("file_path", help="Local file path to check")

    # Command: cookies-check
    p_cc = subparsers.add_parser("cookies-check", help="Verify cookies validity and account email", parents=[common_parser])
    p_cc.add_argument("--cookies-file", "-c", default="cookies.txt", help="Path to cookies.txt (Netscape or JSON)")
    p_cc.add_argument("--session", "-s", default="default", help="Session ID (default: 'default')")

    # Command: drive-import
    p_di = subparsers.add_parser("drive-import", help="Import Google Drive file(s) to Photos via cookies", parents=[common_parser])
    p_di.add_argument("drive_file_ids", nargs="+", help="One or more Google Drive File IDs to import")
    p_di.add_argument("--cookies-file", "-c", default="cookies.txt", help="Path to cookies.txt")
    p_di.add_argument("--session", "-s", default="default", help="Session ID (default: 'default')")
    p_di.add_argument("--cleanup", action="store_true", help="Move to trash and permanently delete after obtaining download URL")
    p_di.add_argument("--timeout", type=int, default=120, help="Timeout in seconds for import operation (default: 120)")

    # Command: reset-account
    p_reset = subparsers.add_parser("reset-account", help="Clear entire Google Photos library and permanently empty trash", parents=[common_parser])
    p_reset.add_argument("--cookies-file", "-c", default="cookies.txt", help="Path to cookies.txt")
    p_reset.add_argument("--confirm", action="store_true", help="Confirmation flag required to perform permanent wipe")

    # Command: quota
    p_quota = subparsers.add_parser("quota", help="Fetch Google Photos account storage quota and limits", parents=[common_parser])
    p_quota.add_argument("--cookies-file", "-c", default="cookies.txt", help="Path to cookies.txt (Netscape or JSON)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    handlers = {
        "token": _cmd_token,
        "share": _cmd_share,
        "download": _cmd_download,
        "import": _cmd_import,
        "delete": _cmd_delete,
        "check": _cmd_check,
        "cookies-check": _cmd_cookies_check,
        "drive-import": _cmd_drive_import,
        "reset-account": _cmd_reset_account,
        "quota": _cmd_quota,
    }

    try:
        handlers[args.command](args)
    except Exception as e:
        if args.json:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
        else:
            print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
