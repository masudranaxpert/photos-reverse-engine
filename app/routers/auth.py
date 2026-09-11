from typing import List
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models import Admin
from app.schemas import (
    AdminCreateRequest,
    AdminResponse,
    AdminUpdateRequest,
    LoginRequest,
    TokenResponse,
)
from app.security import (
    create_access_token,
    get_current_admin,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["Authentication & Admins"])


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, response: Response):
    """Authenticate admin and return JWT access token, setting access_token cookie."""
    async with get_db(write=False) as db:
        stmt = select(Admin).where(Admin.username == req.username.strip())
        res = await db.execute(stmt)
        admin = res.scalar_one_or_none()

    if not admin or not verify_password(req.password, admin.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin account is disabled",
        )

    token, expire_at, expires_in = create_access_token({"sub": admin.username})
    response.set_cookie(
        key="access_token",
        value=token,
        max_age=expires_in,
        httponly=False,
        samesite="lax",
        path="/",
    )
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        username=admin.username,
        expires_in=expires_in,
        expires_at=expire_at.isoformat(),
        expires_timestamp=int(expire_at.timestamp()),
    )


@router.post("/logout")
async def logout(response: Response):
    """Clear session cookie and log out."""
    response.delete_cookie(key="access_token", path="/")
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=AdminResponse)
async def get_me(current_admin: dict = Depends(get_current_admin)):
    """Return currently authenticated admin details."""
    async with get_db(write=False) as db:
        stmt = select(Admin).where(Admin.id == current_admin["id"])
        res = await db.execute(stmt)
        admin = res.scalar_one_or_none()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")
    return AdminResponse(
        id=admin.id,
        username=admin.username,
        is_active=admin.is_active,
        created_at=str(admin.created_at),
    )


@router.get("/admins", response_model=List[AdminResponse])
async def list_admins(current_admin: dict = Depends(get_current_admin)):
    """List all registered administrator accounts."""
    async with get_db(write=False) as db:
        stmt = select(Admin).order_by(Admin.id.asc())
        res = await db.execute(stmt)
        admins = res.scalars().all()
    return [
        AdminResponse(
            id=adm.id,
            username=adm.username,
            is_active=adm.is_active,
            created_at=str(adm.created_at),
        )
        for adm in admins
    ]


@router.post("/admins", response_model=AdminResponse)
async def create_admin(
    req: AdminCreateRequest,
    current_admin: dict = Depends(get_current_admin),
):
    """Create a new administrator account using SQLAlchemy ORM."""
    username = req.username.strip()
    if not username or not req.password:
        raise HTTPException(status_code=400, detail="Username and password are required")

    pw_hash = hash_password(req.password)
    admin = Admin(username=username, password_hash=pw_hash, is_active=True)

    try:
        async with get_db() as db:
            db.add(admin)
            await db.flush()
            await db.refresh(admin)
    except IntegrityError:
        raise HTTPException(status_code=400, detail="Username already exists")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return AdminResponse(
        id=admin.id,
        username=admin.username,
        is_active=admin.is_active,
        created_at=str(admin.created_at),
    )


@router.put("/admins/{admin_id}", response_model=AdminResponse)
async def update_admin(
    admin_id: int,
    req: AdminUpdateRequest,
    current_admin: dict = Depends(get_current_admin),
):
    """Update administrator password or active status."""
    async with get_db() as db:
        stmt = select(Admin).where(Admin.id == admin_id)
        res = await db.execute(stmt)
        admin = res.scalar_one_or_none()
        if not admin:
            raise HTTPException(status_code=404, detail="Admin not found")

        if req.password:
            admin.password_hash = hash_password(req.password)
        if req.is_active is not None:
            admin.is_active = req.is_active

        await db.flush()
        await db.refresh(admin)

    return AdminResponse(
        id=admin.id,
        username=admin.username,
        is_active=admin.is_active,
        created_at=str(admin.created_at),
    )


@router.delete("/admins/{admin_id}")
async def delete_admin(
    admin_id: int,
    current_admin: dict = Depends(get_current_admin),
):
    """Delete an administrator account."""
    if current_admin["id"] == admin_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own admin account")

    async with get_db() as db:
        stmt = delete(Admin).where(Admin.id == admin_id)
        res = await db.execute(stmt)
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Admin not found")

    return {"success": True, "message": "Admin deleted successfully"}
