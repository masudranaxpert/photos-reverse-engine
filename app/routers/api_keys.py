from datetime import datetime, timedelta, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select

from app.database import get_db
from app.models import ApiKey
from app.schemas import (
    ApiKeyCreateRequest,
    ApiKeyCreatedResponse,
    ApiKeyResponse,
    ApiKeyRevealResponse,
    ApiKeyUpdateRequest,
)
from app.security import generate_api_key, get_current_admin

router = APIRouter(prefix="/api/keys", tags=["API Keys Management"])


@router.get("", response_model=List[ApiKeyResponse])
async def list_api_keys(current_admin: dict = Depends(get_current_admin)):
    """List all registered API keys (secrets masked with public prefix)."""
    async with get_db(write=False) as db:
        stmt = select(ApiKey).order_by(ApiKey.id.desc())
        res = await db.execute(stmt)
        keys = res.scalars().all()

    return [
        ApiKeyResponse(
            id=k.id,
            name=k.name,
            prefix=k.prefix,
            is_active=k.is_active,
            created_at=k.created_at.isoformat() if k.created_at else "",
            last_used_at=k.last_used_at.isoformat() if k.last_used_at else None,
            expires_at=k.expires_at.isoformat() if k.expires_at else None,
        )
        for k in keys
    ]


@router.post("", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_new_api_key(
    req: ApiKeyCreateRequest,
    current_admin: dict = Depends(get_current_admin),
):
    """
    Generate a new persistent API key.
    The raw secret key is returned ONCE in this response. Store it securely.
    """
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="API Key name cannot be empty")

    raw_key, prefix = generate_api_key()

    expires_at = None
    if req.expires_days and req.expires_days > 0:
        expires_at = datetime.now(timezone.utc) + timedelta(days=req.expires_days)

    new_key = ApiKey(
        key=raw_key,
        name=name,
        prefix=prefix,
        is_active=True,
        expires_at=expires_at,
    )

    async with get_db() as db:
        db.add(new_key)
        await db.commit()
        await db.refresh(new_key)

    return ApiKeyCreatedResponse(
        id=new_key.id,
        name=new_key.name,
        prefix=new_key.prefix,
        is_active=new_key.is_active,
        created_at=new_key.created_at.isoformat() if new_key.created_at else "",
        last_used_at=None,
        expires_at=new_key.expires_at.isoformat() if new_key.expires_at else None,
        api_key=raw_key,
    )


@router.get("/{key_id}/reveal", response_model=ApiKeyRevealResponse)
async def reveal_api_key(
    key_id: int,
    current_admin: dict = Depends(get_current_admin),
):
    """Return the full secret for a stored API key (admin-only white-label/copy support)."""
    async with get_db(write=False) as db:
        res = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
        key_obj = res.scalar_one_or_none()

    if not key_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")

    return ApiKeyRevealResponse(id=key_obj.id, name=key_obj.name, api_key=key_obj.key)


@router.patch("/{key_id}", response_model=ApiKeyResponse)
@router.put("/{key_id}", response_model=ApiKeyResponse)
async def update_api_key(
    key_id: int,
    req: ApiKeyUpdateRequest,
    current_admin: dict = Depends(get_current_admin),
):
    """Update API key metadata: name/label, active status, or expiration."""
    async with get_db() as db:
        stmt = select(ApiKey).where(ApiKey.id == key_id)
        res = await db.execute(stmt)
        key_obj = res.scalar_one_or_none()
        if not key_obj:
            raise HTTPException(status_code=404, detail="API Key not found")

        if req.name is not None:
            name = req.name.strip()
            if not name:
                raise HTTPException(status_code=400, detail="API Key name cannot be empty")
            key_obj.name = name

        if req.is_active is not None:
            key_obj.is_active = req.is_active

        if req.expires_days is not None:
            if req.expires_days == 0:
                key_obj.expires_at = None
            elif req.expires_days > 0:
                key_obj.expires_at = datetime.now(timezone.utc) + timedelta(days=req.expires_days)

        await db.commit()
        await db.refresh(key_obj)

    return ApiKeyResponse(
        id=key_obj.id,
        name=key_obj.name,
        prefix=key_obj.prefix,
        is_active=key_obj.is_active,
        created_at=key_obj.created_at.isoformat() if key_obj.created_at else "",
        last_used_at=key_obj.last_used_at.isoformat() if key_obj.last_used_at else None,
        expires_at=key_obj.expires_at.isoformat() if key_obj.expires_at else None,
    )


@router.patch("/{key_id}/toggle", response_model=ApiKeyResponse)
async def toggle_api_key(
    key_id: int,
    current_admin: dict = Depends(get_current_admin),
):
    """Enable or disable an existing API key."""
    async with get_db() as db:
        stmt = select(ApiKey).where(ApiKey.id == key_id)
        res = await db.execute(stmt)
        key_obj = res.scalar_one_or_none()
        if not key_obj:
            raise HTTPException(status_code=404, detail="API Key not found")

        key_obj.is_active = not key_obj.is_active
        await db.commit()
        await db.refresh(key_obj)

    return ApiKeyResponse(
        id=key_obj.id,
        name=key_obj.name,
        prefix=key_obj.prefix,
        is_active=key_obj.is_active,
        created_at=key_obj.created_at.isoformat() if key_obj.created_at else "",
        last_used_at=key_obj.last_used_at.isoformat() if key_obj.last_used_at else None,
        expires_at=key_obj.expires_at.isoformat() if key_obj.expires_at else None,
    )


@router.delete("/{key_id}")
async def delete_api_key(
    key_id: int,
    current_admin: dict = Depends(get_current_admin),
):
    """Permanently delete / revoke an API key."""
    async with get_db() as db:
        stmt = select(ApiKey).where(ApiKey.id == key_id)
        res = await db.execute(stmt)
        key_obj = res.scalar_one_or_none()
        if not key_obj:
            raise HTTPException(status_code=404, detail="API Key not found")

        await db.delete(key_obj)
        await db.commit()

    return {"detail": "API Key permanently deleted", "id": key_id}
