import logging
import sys
import urllib.parse
from pathlib import Path
from typing import Optional, Tuple

from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR / "photos_engine") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "photos_engine"))

from photos_engine import PhotosEngineClient
from app.database import get_db
from app.models import MobileAccount

logger = logging.getLogger(__name__)


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
    """Fetch active mobile account from SQLite mobile_accounts table via SQLAlchemy ORM."""
    async with get_db() as db:
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
        return res.scalar_one_or_none()


# In-memory client cache: account_id -> (auth_data, PhotosEngineClient)
_client_cache: dict[int, tuple[str, PhotosEngineClient]] = {}


def invalidate_mobile_client_cache(account_id: Optional[int] = None) -> None:
    """Evict cached PhotosEngineClient instances when credentials change."""
    if account_id is not None:
        _client_cache.pop(account_id, None)
    else:
        _client_cache.clear()


async def get_mobile_client(account_id: Optional[int] = None) -> Tuple[PhotosEngineClient, MobileAccount]:
    """
    Instantiate or retrieve cached PhotosEngineClient strictly from active database mobile_accounts row.
    Reuses client to preserve Go TokenManager internal memory cache and avoid redundant auth calls.
    """
    account = await get_active_mobile_account(account_id)
    if not account:
        raise RuntimeError("No active Mobile Auth account found in database. Please add an account via /api/mobile/accounts.")

    auth_data = account.auth_data
    cached = _client_cache.get(account.id)
    if cached and cached[0] == auth_data:
        return cached[1], account

    client = PhotosEngineClient(auth_data=auth_data)
    _client_cache[account.id] = (auth_data, client)
    return client, account
