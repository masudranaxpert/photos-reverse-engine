import os
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
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

