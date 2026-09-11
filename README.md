# Instant Engine — Google Photos High-Performance Reverse Engine & Streaming Pipeline

<p align="center">
  <img src="static/img/upload.svg" alt="Instant Engine Banner" width="160">
  <br>
  <b>Production-grade Google Photos reverse engineering engine with two-stage import pipeline, adaptive DASH streaming, zero-leak privacy, and real-time administrative analytics.</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.13+-3776AB?style=flat&logo=python&logoColor=white" alt="Python 3.13+">
  <img src="https://img.shields.io/badge/FastAPI-0.141+-009688?style=flat&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Database-SQLite%20WAL-003B57?style=flat&logo=sqlite&logoColor=white" alt="SQLite WAL">
  <img src="https://img.shields.io/badge/Migrations-Alembic-E95420?style=flat&logo=alembic&logoColor=white" alt="Alembic">
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=flat&logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/Tests-22%20Passed-brightgreen?style=flat" alt="Tests Passed">
</p>

---

## System Architecture

```
[ Google Drive File ]
         │
         ▼
[ Web Client Session ] ──► [ Temporary Queue ] ──► Instant Direct Download
         │
         ▼ (Background Worker / APScheduler)
[ Mobile Auth Client ] ──► [ Permanent Library ] ──► Direct Download + Adaptive Streaming
         │                                                      │
         ▼                                                      ▼
[ Token Cache (Mem) ]                                 [ Cloudflare Worker Proxy ]
                                                                │
                                                                ▼
                                                      [ ArtPlayer Video Stream ]
```

1. **Two-Stage Resilient Pipeline**:
   - **Stage 1 (Web Client)**: Instantaneous import from Google Drive into Google Photos via session cookies, immediately creating a public download token.
   - **Stage 2 (Mobile Client)**: Background worker automatically promotes temporary items into permanent multi-account storage using mobile OAuth reverse-engineering tokens.
2. **Adaptive Video Streaming (DASH/ArtPlayer)**:
   - Dynamic extraction and caching of multi-bitrate DASH manifests (1080p, 720p, 480p, 360p) with dual-stream audio synchronization.
   - Manifests are proxied through Cloudflare Worker (`MANIFEST_PROXY_URL`) to mask backend server IP addresses.
3. **Zero Identifier Leakage**:
   - Public download endpoints (`/api/download/{token}`, `/download/{token}`) strictly scrub internal Google Drive IDs, Google Photos Media Keys, and album URLs.
4. **Unique Visitor Tracking**:
   - 24-hour cookie-based deduplication (`viewed_{token}=1`). Refreshing or F5 spam never inflates counts. Visitor analytics are visible exclusively on the admin dashboard.
5. **White-Label Branding**:
   - API keys can carry dedicated brand names. Files uploaded via an API key reflect that key's name on public download pages.

---

## Project Structure

```
.
├── alembic/                 # Database schema migration scripts (async SQLite batch mode)
│   ├── versions/            # Migration revisions
│   └── env.py               # Dynamic Alembic environment configuration
├── app/
│   ├── routers/             # FastAPI modular route handlers
│   │   ├── api_keys.py      # Third-party persistent API key management
│   │   ├── auth.py          # Admin authentication, session cookies, JWT
│   │   ├── download.py      # Public download pages, player, and manifest routing
│   │   ├── media.py         # Media explorer repository and analytics
│   │   ├── mobile_client.py # Mobile accounts management
│   │   ├── upload.py        # Drive import pipeline endpoints
│   │   └── web_client.py    # Web session cookies management
│   ├── services/            # Core business logic & background workers
│   │   ├── mobile_service.py # Cached mobile client instances & token lifecycle
│   │   ├── scheduler.py     # APScheduler background tasks
│   │   ├── stream_cache_service.py # 20-min manifest representation caching
│   │   └── streaming_service.py # DASH MPD parser & proxy transport
│   ├── config.py            # Centralized environment configuration
│   ├── database.py          # SQLAlchemy 2.0 async engine (SQLite WAL mode)
│   ├── logging_config.py    # Loguru logging with rotation and retention
│   ├── models.py            # SQLAlchemy ORM declarative models
│   ├── schemas.py           # Pydantic request/response schemas
│   └── security.py          # JWT, bcrypt password hashing, auth guards
├── photos_engine/           # Google Photos reverse-engineered protocol package
├── static/                  # Vanilla CSS, SVG icons, and vanilla JS dashboard
├── templates/               # Jinja2 HTML templates (download, player, dashboard)
├── tests/                   # Automated pytest and unittest integration test suite
├── docker-compose.yml       # Production Docker orchestration
├── Dockerfile               # Container build recipe
├── manage.py                # Command-line interface manager
└── requirements.txt         # Pinned Python package dependencies
```

---

## Quick Start

### 1. Prerequisites
- **Python 3.13+**
- **uv** (recommended) or **pip**

### 2. Clone & Install Dependencies
```bash
git clone https://github.com/masudranaxpert/photos-reverse-engine.git
cd photos-reverse-engine

# Using uv (fastest)
uv sync

# Or using standard pip
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure Environment
Copy the example environment file:
```bash
cp .env.example .env
```
Key configuration parameters in `.env`:
```ini
# Secret key for JWT signing
SECRET_KEY=photos-engine-super-secret-jwt-key-2026-production

# Cloudflare Worker reverse proxy for DASH manifests (masks server IP from video streams)
MANIFEST_PROXY_URL=https://curly-mountain-4fe1.ood-sakib-2.workers.dev

# Logging levels
LOG_LEVEL=INFO
LOG_SHOW_CALLER=false
```

### 4. Create Admin Account
```bash
python manage.py createadmin -u admin -p "YourStrongPassword123"
```

### 5. Start Application Server
```bash
python manage.py runserver --host 127.0.0.1 --port 8000
```
> **Auto-Migration**: Server startup automatically executes `alembic upgrade head` before Uvicorn boots. No manual migration step is required.

Access the dashboard at: [http://localhost:8000/login](http://localhost:8000/login)

---

## Docker Deployment

The application is fully containerized with persistent SQLite storage and centralized logs.

```bash
# Build and start container in detached mode
docker compose up -d --build

# View container logs
docker compose logs -f

# Check running status
docker compose ps
```

The container maps internal port `8000` to host port `8890`:
- **Dashboard URL**: `http://your-server-ip:8890/login`
- **Persistent Data**: Stored in `./data`
- **Logs**: Stored in `./logs`

---

## CLI Management Commands

Manage all administrative operations via `manage.py`:

| Command | Usage | Description |
| :--- | :--- | :--- |
| `runserver` | `python manage.py runserver [--host 0.0.0.0] [--port 8000]` | Starts FastAPI application with auto-migrations. |
| `createadmin` | `python manage.py createadmin -u <user> -p <pass>` | Creates or updates an administrator account. |
| `createkey` | `python manage.py createkey -n "Bot Name" [-d <days>]` | Generates a persistent API key for third-party scripts. |
| `makemigrations`| `python manage.py makemigrations -m "<message>"` | Autodetects schema changes and generates Alembic revision. |
| `migrate` | `python manage.py migrate` | Applies all pending database migrations to latest revision. |
| `init-db` | `python manage.py init-db` | Initializes SQLite schema with WAL mode directly. |

---

## Public & API Endpoints

### Public Consumer Endpoints
- `GET /download/{token}`: Responsive HTML download page with direct link and player launcher.
- `GET /player/{token}`: Dedicated full-browser ArtPlayer with resolution switcher.
- `GET /embed/{token}`: Iframe-embeddable video player.
- `GET /api/download/{token}`: JSON status for client integrations (sanitized: no internal IDs).
- `GET /api/download/{token}/manifest`: Parsed DASH audio and video tracks for web players.
- `GET /api/download/{token}/manifest.mpd`: Raw DASH XML manifest.

### Admin & Integration Endpoints
- `POST /api/auth/login`: Admin authentication returning JWT access token and cookie.
- `GET /api/media`: Paginated media explorer with visitor counts, stages, and account owner info.
- `POST /api/upload`: Import file by Google Drive ID (supports `X-API-Key` or Bearer auth).
- `GET /api/api-keys`: View and manage persistent API keys and white-label branding.
- `GET /health`: Health check with SQLite WAL verification.

---

## Automated Testing

Run the comprehensive 22-test integration test suite:
```bash
# Run all tests
uv run pytest -q

# Run with verbose output
uv run pytest -v
```

All tests execute against isolated in-memory/temporary SQLite databases and never touch production or development data.

---

## License
Proprietary & Confidential. All rights reserved.
