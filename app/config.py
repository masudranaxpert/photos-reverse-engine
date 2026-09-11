import os
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() not in os.environ:
                        os.environ[k.strip()] = v.strip().strip("'\"")
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

