"""System settings router: Google Drive API Key and system-level configuration."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.database import get_db
from app.models import SystemSetting
from app.security import get_current_admin
from app.services.drive_api_service import get_drive_api_key, set_drive_api_key

router = APIRouter(prefix="/api/settings", tags=["System Settings"])


class DriveApiKeyRequest(BaseModel):
    api_key: str


class DriveApiKeyResponse(BaseModel):
    api_key: str
    masked_key: str
    is_set: bool


@router.get("/drive-api-key", response_model=DriveApiKeyResponse)
async def get_drive_key(current_admin: dict = Depends(get_current_admin)):
    """Retrieve the currently configured Google Drive API Key."""
    key = await get_drive_api_key()
    if not key:
        return DriveApiKeyResponse(api_key="", masked_key="", is_set=False)
    masked = f"{key[:8]}...{key[-4:]}" if len(key) > 12 else key
    return DriveApiKeyResponse(api_key=key, masked_key=masked, is_set=True)


@router.post("/drive-api-key", response_model=DriveApiKeyResponse)
async def update_drive_key(
    req: DriveApiKeyRequest,
    current_admin: dict = Depends(get_current_admin),
):
    """Update Google Drive API Key."""
    clean_key = req.api_key.strip()
    if not clean_key:
        raise HTTPException(status_code=400, detail="API Key cannot be empty")
    await set_drive_api_key(clean_key)
    masked = f"{clean_key[:8]}...{clean_key[-4:]}" if len(clean_key) > 12 else clean_key
    return DriveApiKeyResponse(api_key=clean_key, masked_key=masked, is_set=True)


# ── Import Concurrency ──────────────────────────────────────────────────────


class ConcurrencyResponse(BaseModel):
    max_concurrent_imports: int
    description: str


class ConcurrencyRequest(BaseModel):
    max_concurrent_imports: int


@router.get("/import-concurrency", response_model=ConcurrencyResponse)
async def get_import_concurrency(current_admin: dict = Depends(get_current_admin)):
    """Return the current max concurrent Drive→Photos import slots."""
    async with get_db(write=False) as db:
        row = await db.get(SystemSetting, "max_concurrent_imports")
    value = int(row.value) if row else 1
    return ConcurrencyResponse(
        max_concurrent_imports=value,
        description=(
            "Controls how many Drive→Photos imports run in parallel. "
            "Set to 1 for strictly sequential. "
            "Increase proportionally to your web staging storage "
            "(e.g. 15 GB staging ÷ avg file size = safe concurrency)."
        ),
    )


@router.post("/import-concurrency", response_model=ConcurrencyResponse)
async def set_import_concurrency(
    req: ConcurrencyRequest,
    current_admin: dict = Depends(get_current_admin),
):
    """Update max concurrent import slots (1–2000). Takes effect on next queued import."""
    value = req.max_concurrent_imports
    if not (1 <= value <= 2000):
        raise HTTPException(
            status_code=400,
            detail="max_concurrent_imports must be between 1 and 2000",
        )
    async with get_db() as db:
        row = await db.get(SystemSetting, "max_concurrent_imports")
        if row:
            row.value = str(value)
        else:
            db.add(SystemSetting(
                key="max_concurrent_imports",
                value=str(value),
                description="Max parallel Drive→Photos staging imports",
            ))
    return ConcurrencyResponse(
        max_concurrent_imports=value,
        description=(
            "Controls how many Drive→Photos imports run in parallel. "
            "Set to 1 for strictly sequential. "
            "Increase proportionally to your web staging storage."
        ),
    )
