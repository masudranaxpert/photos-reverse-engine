import asyncio
import logging
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Optional, Tuple

from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR / "photos_engine") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "photos_engine"))

from photos_engine import PhotosEngineClient
from app.database import get_db
from app.models import MobileAccount

import time

logger = logging.getLogger(__name__)

# In-memory account cache: (MobileAccount, monotonic_expiry)
_account_cache: tuple[Optional[MobileAccount], float] = (None, 0.0)


def extract_email_from_auth_data(auth_data: str) -> str:
    """Extract account email from raw GPMC AUTH_DATA string."""
    try:
        parsed = urllib.parse.parse_qs(auth_data)
        if "Email" in parsed and parsed["Email"]:
            return parsed["Email"][0].strip()
    except Exception:
        pass
    return "unknown@gmail.com"


async def get_active_mobile_account(account_id: Optional[int] = None) -> Optional[MobileAccount]:
    """Fetch active mobile account with 30s in-memory cache and read-only DB query."""
    global _account_cache
    if account_id is None:
        row, exp = _account_cache
        if row is not None and time.monotonic() < exp:
            return row

    async with get_db(write=False) as db:
        if account_id:
            stmt = select(MobileAccount).where(
                MobileAccount.id == account_id,
                MobileAccount.is_active.is_(True),
            )
            res = await db.execute(stmt)
            return res.scalar_one_or_none()

        stmt = (
            select(MobileAccount)
            .where(MobileAccount.is_active.is_(True))
            .order_by(MobileAccount.id.desc())
            .limit(1)
        )
        res = await db.execute(stmt)
        account = res.scalar_one_or_none()
        if account:
            _account_cache = (account, time.monotonic() + 30.0)
        return account


# In-memory client caches
# 1. Request path: pool of 2 PhotosEngineClients per account for concurrent download resolution
_download_clients_pool: dict[int, tuple[str, list[PhotosEngineClient]]] = {}
_download_pool_idx: int = 0

# 2. Background sweep/worker: dedicated PhotosEngineClient per account
_bg_client_cache: dict[int, tuple[str, PhotosEngineClient]] = {}

# 3. Streaming & media operations: dedicated PhotosEngineClient per account
_streaming_client_cache: dict[int, tuple[str, PhotosEngineClient]] = {}

_pool_init_lock = asyncio.Lock()
_POOL_SIZE = 2


def _close_client_entry(entry: Any) -> None:
    """Explicitly close PhotosEngineClient instances to release Go CGo handles."""
    if not entry:
        return
    try:
        _, target = entry
        items = target if isinstance(target, list) else [target]
        for c in items:
            try:
                if hasattr(c, "close"):
                    c.close()
            except Exception:
                pass
    except Exception:
        pass


def invalidate_mobile_client_cache(account_id: Optional[int] = None) -> None:
    """Evict cached PhotosEngineClient and account instances when credentials change, closing Go handles."""
    global _account_cache
    _account_cache = (None, 0.0)
    if account_id is not None:
        _close_client_entry(_download_clients_pool.pop(account_id, None))
        _close_client_entry(_bg_client_cache.pop(account_id, None))
        _close_client_entry(_streaming_client_cache.pop(account_id, None))
    else:
        for k in list(_download_clients_pool):
            _close_client_entry(_download_clients_pool.pop(k, None))
        for k in list(_bg_client_cache):
            _close_client_entry(_bg_client_cache.pop(k, None))
        for k in list(_streaming_client_cache):
            _close_client_entry(_streaming_client_cache.pop(k, None))


async def get_mobile_client(
    account_id: Optional[int] = None,
    *,
    client_type: str = "download",
    background: bool = False,
) -> Tuple[PhotosEngineClient, MobileAccount]:
    """
    Instantiate or retrieve cached PhotosEngineClient strictly from active database mobile_accounts row.
    - client_type="download" (default): round-robins across a pool of 2 download clients with race-free lock.
    - client_type="worker" or background=True: returns dedicated worker client (isolated from user downloads).
    - client_type="streaming": returns dedicated streaming / media operations client.
    """
    global _download_pool_idx

    account = await get_active_mobile_account(account_id)
    if not account:
        raise RuntimeError("No active Mobile Auth account found in database. Please add an account via /api/mobile/accounts.")

    auth_data = account.auth_data

    # Map background=True to worker if client_type was left default
    effective_type = "worker" if background and client_type == "download" else client_type

    if effective_type in ("worker", "background"):
        cached = _bg_client_cache.get(account.id)
        if cached and cached[0] == auth_data:
            return cached[1], account

        async with _pool_init_lock:
            cached = _bg_client_cache.get(account.id)
            if cached and cached[0] == auth_data:
                return cached[1], account

            _close_client_entry(_bg_client_cache.pop(account.id, None))
            bg_client = await asyncio.to_thread(PhotosEngineClient, auth_data=auth_data)
            _bg_client_cache[account.id] = (auth_data, bg_client)
            return bg_client, account

    if effective_type == "streaming":
        cached = _streaming_client_cache.get(account.id)
        if cached and cached[0] == auth_data:
            return cached[1], account

        async with _pool_init_lock:
            cached = _streaming_client_cache.get(account.id)
            if cached and cached[0] == auth_data:
                return cached[1], account

            _close_client_entry(_streaming_client_cache.pop(account.id, None))
            streaming_client = await asyncio.to_thread(PhotosEngineClient, auth_data=auth_data)
            _streaming_client_cache[account.id] = (auth_data, streaming_client)
            return streaming_client, account

    # Request / Download path: pool of 2 clients
    cached_pool = _download_clients_pool.get(account.id)
    if cached_pool and cached_pool[0] == auth_data and len(cached_pool[1]) >= _POOL_SIZE:
        clients = cached_pool[1]
        client = clients[_download_pool_idx % len(clients)]
        _download_pool_idx += 1
        return client, account

    async with _pool_init_lock:
        cached_pool = _download_clients_pool.get(account.id)
        if cached_pool and cached_pool[0] == auth_data and len(cached_pool[1]) >= _POOL_SIZE:
            clients = cached_pool[1]
            client = clients[_download_pool_idx % len(clients)]
            _download_pool_idx += 1
            return client, account

        _close_client_entry(_download_clients_pool.pop(account.id, None))
        pool = [
            await asyncio.to_thread(PhotosEngineClient, auth_data=auth_data)
            for _ in range(_POOL_SIZE)
        ]
        _download_clients_pool[account.id] = (auth_data, pool)
        client = pool[_download_pool_idx % len(pool)]
        _download_pool_idx += 1
        return client, account
