import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
import sys

# Ensure parent and photos_engine are on python path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(BASE_DIR / "photos_engine") not in sys.path:
    sys.path.insert(0, str(BASE_DIR / "photos_engine"))

from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.database import get_db, init_db
from app.security import is_authenticated_admin
from app.routers import api_keys, auth, media, mobile_client, web_client
from app.routers import upload, download, jobs, settings, notices
from app.services.cache_service import cleanup_expired_cache
from app.logging_config import setup_logging, logger

# Initialize Loguru as the centralized logging engine
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB, purge expired cache, start APScheduler background manager."""
    # Bump thread pool to handle concurrent blocking calls (client.close, quota check, etc.)
    loop = asyncio.get_event_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=64))

    logger.info("Initializing SQLite database with WAL mode...")
    await init_db()
    cleaned = await cleanup_expired_cache()
    logger.info(f"Database initialized. Purged {cleaned} expired cache records.")

    # Start APScheduler for all recurring background jobs
    from app.services.scheduler import start_scheduler, stop_scheduler
    await start_scheduler()

    yield

    await stop_scheduler()
    logger.info("Application shutting down.")


app = FastAPI(
    title="Instant Engine API",
    description="High-performance  Instant Download Engine",
    version="3.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files & templates
static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

templates_dir = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

# Routers
app.include_router(auth.router)
app.include_router(api_keys.router)
app.include_router(web_client.router)
app.include_router(mobile_client.router)
app.include_router(media.router)
app.include_router(upload.router)
app.include_router(download.router)
app.include_router(jobs.router)
app.include_router(settings.router)
app.include_router(notices.router)


# Frontend pages
@app.get("/", tags=["Frontend"])
async def dashboard_page(request: Request):
    """Render main management dashboard page (requires admin auth)."""
    if not await is_authenticated_admin(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/login", tags=["Frontend"])
async def login_page(request: Request):
    """Render administrator login page (redirects to / if already logged in)."""
    if await is_authenticated_admin(request):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html")


@app.get("/cached-urls", tags=["Frontend"])
async def cached_urls_page(request: Request):
    """Render 30-min cached download URLs management page (requires admin auth)."""
    if not await is_authenticated_admin(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request=request, name="cached_urls.html")


@app.get("/stream-cache", tags=["Frontend"])
async def stream_cache_page(request: Request):
    """Render 20-min cached streaming URLs management page (requires admin auth)."""
    if not await is_authenticated_admin(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request=request, name="stream_cache.html")


@app.get("/audit", tags=["Frontend"])
async def audit_page(request: Request):
    """Render system audit log page (requires admin auth)."""
    if not await is_authenticated_admin(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request=request, name="audit.html")


@app.get("/health", tags=["System"])
async def health_check():
    """System health check and database status."""
    from sqlalchemy import text

    async with get_db() as db:
        res = await db.execute(text("PRAGMA journal_mode"))
        row = res.fetchone()
        journal_mode = row[0] if row else "unknown"

    return {
        "status": "healthy",
        "engine": "photos_engine_go_core",
        "database": {
            "type": "sqlite",
            "journal_mode": journal_mode,
        },
    }


@app.get("/openapi.json", include_in_schema=False)
async def openapi_endpoint(request: Request):
    """Dynamic OpenAPI schema: hides all endpoints except upload for unauthenticated visitors."""
    full_schema = app.openapi()
    if await is_authenticated_admin(request):
        return JSONResponse(full_schema)

    filtered_paths = {}
    for path, path_item in full_schema.get("paths", {}).items():
        if path.startswith("/api/upload"):
            filtered_paths[path] = path_item

    filtered_schema = {
        "openapi": full_schema.get("openapi", "3.1.0"),
        "info": full_schema.get("info", {}),
        "paths": filtered_paths,
        "components": full_schema.get("components", {}),
    }
    return JSONResponse(filtered_schema)


@app.get("/docs", include_in_schema=False)
async def swagger_ui_endpoint(request: Request):
    """Swagger UI documentation page."""
    token = (
        request.query_params.get("token")
        or request.query_params.get("api_key")
        or request.cookies.get("access_token")
    )
    openapi_url = f"/openapi.json?token={token}" if token else "/openapi.json"
    html_resp = get_swagger_ui_html(
        openapi_url=openapi_url,
        title=f"{app.title} - Swagger UI",
    )
    body = html_resp.body.decode("utf-8")
    script = """
    <script>
    (function() {
        try {
            var tok = localStorage.getItem("photos_engine_token") || localStorage.getItem("auth_token");
            if (tok) {
                document.cookie = "access_token=" + encodeURIComponent(tok) + "; path=/; max-age=604800; SameSite=Lax";
                var p = new URLSearchParams(window.location.search);
                if (!p.has("token")) {
                    p.set("token", tok);
                    window.location.search = p.toString();
                }
            }
        } catch(e) {}
    })();
    </script>
    """
    body = body.replace("<head>", f"<head>{script}", 1)
    return HTMLResponse(content=body)


@app.get("/redoc", include_in_schema=False)
async def redoc_endpoint(request: Request):
    """ReDoc documentation page."""
    token = (
        request.query_params.get("token")
        or request.query_params.get("api_key")
        or request.cookies.get("access_token")
    )
    openapi_url = f"/openapi.json?token={token}" if token else "/openapi.json"
    html_resp = get_redoc_html(
        openapi_url=openapi_url,
        title=f"{app.title} - ReDoc",
    )
    body = html_resp.body.decode("utf-8")
    script = """
    <script>
    (function() {
        try {
            var tok = localStorage.getItem("photos_engine_token") || localStorage.getItem("auth_token");
            if (tok) {
                document.cookie = "access_token=" + encodeURIComponent(tok) + "; path=/; max-age=604800; SameSite=Lax";
                var p = new URLSearchParams(window.location.search);
                if (!p.has("token")) {
                    p.set("token", tok);
                    window.location.search = p.toString();
                }
            }
        } catch(e) {}
    })();
    </script>
    """
    body = body.replace("<head>", f"<head>{script}", 1)
    return HTMLResponse(content=body)
