"""
notices.py — System Notices / Alerts Board router.
Allows fetching active notices and dismissing them.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from app.security import get_current_admin
from app.services.notice_service import (
    clear_all_notices,
    dismiss_notice,
    get_active_notices,
    get_notices_paginated,
)

router = APIRouter(prefix="/api/notices", tags=["System Notices"])


class NoticeItem(BaseModel):
    id: int
    level: str
    title: str
    message: str
    source: str
    is_active: bool = True
    created_at: str
    updated_at: str


class NoticeListResponse(BaseModel):
    notices: List[NoticeItem]
    total: int


class PaginatedNoticeResponse(BaseModel):
    notices: List[NoticeItem]
    total: int
    page: int
    page_size: int
    total_pages: int


@router.get("", response_model=NoticeListResponse)
async def list_active_notices(current_admin: dict = Depends(get_current_admin)):
    """Retrieve all current unresolved system notices and alerts."""
    items = await get_active_notices()
    return NoticeListResponse(
        notices=[NoticeItem(**i) for i in items],
        total=len(items),
    )


@router.get("/paginated", response_model=PaginatedNoticeResponse)
async def list_paginated_notices(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status: str = Query("all", pattern="^(all|active)$"),
    current_admin: dict = Depends(get_current_admin),
):
    """Paginated audit log, newest first. status=all includes dismissed rows."""
    data = await get_notices_paginated(page, page_size, status)
    return PaginatedNoticeResponse(**data)


@router.post("/{notice_id}/dismiss")
async def dismiss_single_notice(
    notice_id: int,
    current_admin: dict = Depends(get_current_admin),
):
    """Dismiss/resolve a specific notice."""
    ok = await dismiss_notice(notice_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Notice not found")
    return {"success": True, "message": f"Notice #{notice_id} dismissed"}


@router.post("/clear")
async def dismiss_all_notices(current_admin: dict = Depends(get_current_admin)):
    """Dismiss all active notices."""
    count = await clear_all_notices()
    return {"success": True, "cleared": count}
