import os
from pathlib import Path

from dotenv import load_dotenv

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Database (tests override INSTANT_ENGINE_DB_PATH so they never touch the live DB)
DB_PATH = Path(os.getenv("INSTANT_ENGINE_DB_PATH", str(DATA_DIR / "app.db")))

# Security & JWT
SECRET_KEY = os.getenv("SECRET_KEY", "photos-engine-super-secret-jwt-key-2026-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

# Download Link Cache TTL (30 minutes)
DOWNLOAD_CACHE_TTL_SECONDS = 1800

# Stream Cache TTL (20 minutes) & Manifest Request Throttle (10 minutes)
STREAM_CACHE_TTL_SECONDS = 1200
STREAM_MANIFEST_THROTTLE_SECONDS = 600

# Cloudflare Worker or reverse proxy for DASH manifests (masks server IP from video URLs)
MANIFEST_PROXY_URL = os.getenv("MANIFEST_PROXY_URL", "").strip().rstrip("/")

