import os
import sys
import time
from pathlib import Path

# Ensure photos_engine package is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from photos_engine import PhotosEngineClient


def load_auth_data() -> str:
    """Load AUTH_DATA from environment or .env file."""
    if auth := os.getenv("AUTH_DATA"):
        return auth

    search_paths = [
        Path(".env"),
        Path("../.env"),
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]

    for env_path in search_paths:
        if env_path.is_file():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("AUTH_DATA="):
                    val = line[len("AUTH_DATA="):].strip()
                    return val.strip("'\"")
    return ""


def main():
    wait_mode = "--wait" in sys.argv or "-w" in sys.argv
    args = [a for a in sys.argv[1:] if a not in ("--wait", "-w")]

    if args:
        share_url = args[0].strip().strip("'\"")
    else:
        share_url = "https://photos.app.goo.gl/kS1iDhRR2CeW4fTa6"

    auth_data = load_auth_data()
    if not auth_data:
        raise ValueError("AUTH_DATA not found in .env file or environment")

    print(f"Target Share URL: {share_url}")
    print("Initializing PhotosEngineClient with AUTH_DATA...")
    client = PhotosEngineClient(auth_data=auth_data)

    print("Scraping shared link and importing with Pixel XL original quality spoofing...")

    attempt = 1
    while True:
        res = client.import_share_url(share_url)
        if not res.get("scraped"):
            print(f"\n[FAILED] Failed to scrape share link: {res.get('error')}", file=sys.stderr)
            sys.exit(1)

        import_result = res["import_result"]
        scraped = res["scraped"]

        if import_result.status == 2:
            new_keys = import_result.new_keys or []
            print("\n" + "=" * 55)
            print("           IMPORT COMPLETED SUCCESSFULLY          ")
            print("=" * 55)
            print(f"Album Key        : {scraped.album_key}")
            print(f"Auth Key         : {scraped.auth_key}")
            print(f"Found Media Items: {res['media_count']}")
            print(f"Saved to Library : {len(new_keys)} item(s)")
            print(f"Status Code      : 2 (STATUS_OK)")
            if new_keys:
                print("\nNew Media Keys in Account:")
                for idx, key in enumerate(new_keys, 1):
                    print(f"  [{idx}] {key}")
            print("=" * 55)
            break

        elif import_result.status == 1:
            print(f"\n[STATUS 1: PROCESSING] Video is currently transcoding on Google Photos servers.")
            print(f"Status Message: {import_result.status_message}")
            if wait_mode:
                print(f"Waiting 10s for Google transcoding to finish... (Attempt {attempt})")
                time.sleep(10)
                attempt += 1
                continue
            else:
                print("\nTip: Pass '--wait' to automatically poll and save when video transcoding finishes.")
                print("     Example: py save.py <url> --wait")
                break
        else:
            print(f"\n[STATUS {import_result.status}] {import_result.status_message}")
            break


if __name__ == "__main__":
    main()
