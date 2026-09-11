"""Mobile client router: account management only. Shared import/download moved to /api/upload + /api/download."""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select, update

from app.database import get_db
from app.models import MobileAccount
from app.schemas import (
    MobileAccountCreate,
    MobileAccountResponse,
)
from app.security import get_current_admin
from app.services.mobile_service import extract_email_from_auth_data, invalidate_mobile_client_cache
from photos_engine import PhotosEngineClient

router = APIRouter(prefix="/api/mobile", tags=["Mobile Client Accounts"])


@router.get("/accounts", response_model=List[MobileAccountResponse])
async def list_mobile_accounts(current_admin: dict = Depends(get_current_admin)):
    """List all stored Google Photos mobile client accounts."""
    async with get_db() as db:
        stmt = select(MobileAccount).order_by(MobileAccount.id.desc())
        res = await db.execute(stmt)
        accounts = res.scalars().all()

    return [
        MobileAccountResponse(
            id=a.id,
            email=a.email,
            is_active=a.is_active,
            created_at=str(a.created_at),
            updated_at=str(a.updated_at),
        )
        for a in accounts
    ]


@router.post("/accounts", response_model=MobileAccountResponse)
async def create_mobile_account(
    req: MobileAccountCreate,
    current_admin: dict = Depends(get_current_admin),
):
    """Register a new GPMC mobile client account using raw AUTH_DATA."""
    raw_auth = req.auth_data.strip()
    if not raw_auth:
        raise HTTPException(status_code=400, detail="AUTH_DATA cannot be empty")

    try:
        test_client = PhotosEngineClient(auth_data=raw_auth)
        _ = await test_client.get_token_async(timeout=10.0)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to validate mobile AUTH_DATA: {exc}")

    email = extract_email_from_auth_data(raw_auth)

    async with get_db() as db:
        stmt = select(MobileAccount).where(MobileAccount.email == email)
        res = await db.execute(stmt)
        account = res.scalar_one_or_none()

        if account:
            account.auth_data = raw_auth
            account.is_active = True
            invalidate_mobile_client_cache(account.id)
        else:
            account = MobileAccount(email=email, auth_data=raw_auth, is_active=True)
            db.add(account)

        await db.flush()
        await db.refresh(account)

    return MobileAccountResponse(
        id=account.id,
        email=account.email,
        is_active=account.is_active,
        created_at=str(account.created_at),
        updated_at=str(account.updated_at),
    )


@router.put("/accounts/{account_id}/activate", response_model=MobileAccountResponse)
async def activate_mobile_account(
    account_id: int,
    current_admin: dict = Depends(get_current_admin),
):
    """Set the specified account as the active mobile client."""
    async with get_db() as db:
        stmt = select(MobileAccount).where(MobileAccount.id == account_id)
        res = await db.execute(stmt)
        account = res.scalar_one_or_none()
        if not account:
            raise HTTPException(status_code=404, detail="Mobile account not found")

        await db.execute(update(MobileAccount).values(is_active=False))
        account.is_active = True
        await db.flush()
        await db.refresh(account)
        invalidate_mobile_client_cache()

    return MobileAccountResponse(
        id=account.id,
        email=account.email,
        is_active=account.is_active,
        created_at=str(account.created_at),
        updated_at=str(account.updated_at),
    )


@router.delete("/accounts/{account_id}")
async def delete_mobile_account(
    account_id: int,
    current_admin: dict = Depends(get_current_admin),
):
    """Delete a mobile account from the database."""
    async with get_db() as db:
        stmt = delete(MobileAccount).where(MobileAccount.id == account_id)
        res = await db.execute(stmt)
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Mobile account not found")
        invalidate_mobile_client_cache(account_id)
    return {"success": True, "message": "Mobile account deleted successfully"}
