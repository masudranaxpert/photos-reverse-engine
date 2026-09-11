import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader, APIKeyQuery, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update

from app.config import ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, SECRET_KEY
from app.database import get_db


class JWTError(Exception):
    """Raised when JWT verification, decoding, or expiration validation fails."""
    pass


class _JWT:
    """Standard library HS256 JWT implementation without external dependencies."""

    @staticmethod
    def _b64encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    @staticmethod
    def _b64decode(data: str) -> bytes:
        padding = 4 - (len(data) % 4)
        if padding != 4:
            data += "=" * padding
        return base64.urlsafe_b64decode(data)

    def encode(self, payload: dict, key: str, algorithm: str = "HS256") -> str:
        header = {"alg": algorithm, "typ": "JWT"}
        hdr_b64 = self._b64encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        clean = {}
        for k, v in payload.items():
            clean[k] = int(v.timestamp()) if isinstance(v, datetime) else v
        pay_b64 = self._b64encode(json.dumps(clean, separators=(",", ":")).encode("utf-8"))
        signing_input = f"{hdr_b64}.{pay_b64}".encode("ascii")
        sig = hmac.new(key.encode("utf-8"), signing_input, hashlib.sha256).digest()
        return f"{hdr_b64}.{pay_b64}.{self._b64encode(sig)}"

    def decode(self, token: str, key: str, algorithms: list = None) -> dict:
        parts = token.split(".")
        if len(parts) != 3:
            raise JWTError("Invalid token format")
        hdr_b64, pay_b64, sig_b64 = parts
        try:
            signing_input = f"{hdr_b64}.{pay_b64}".encode("ascii")
            expected_sig = hmac.new(key.encode("utf-8"), signing_input, hashlib.sha256).digest()
            actual_sig = self._b64decode(sig_b64)
            if not hmac.compare_digest(expected_sig, actual_sig):
                raise JWTError("Signature verification failed")
            payload = json.loads(self._b64decode(pay_b64).decode("utf-8"))
        except Exception as exc:
            raise JWTError(f"Token decoding failed: {exc}") from exc

        exp = payload.get("exp")
        if exp is not None and time.time() > float(exp):
            raise JWTError("Token has expired")
        return payload


jwt = _JWT()

security_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
api_key_query = APIKeyQuery(name="api_key", auto_error=False)


def generate_api_key() -> Tuple[str, str]:
    """
    Generate secure persistent API key and public prefix.
    Returns (raw_secret_key, display_prefix).
    """
    random_part = secrets.token_urlsafe(32).replace("-", "").replace("_", "")[:32]
    raw_key = f"gpmc_live_{random_part}"
    display_prefix = f"gpmc_live_{random_part[:6]}...{random_part[-4:]}"
    return raw_key, display_prefix


def hash_password(password: str) -> str:
    """Generate salted PBKDF2-HMAC-SHA256 password hash using standard library."""
    salt = secrets.token_hex(16)
    iterations = 260000
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    return f"pbkdf2:sha256:{iterations}${salt}${derived.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plain password against stored PBKDF2-HMAC-SHA256 hash."""
    try:
        method, salt, stored_hash = hashed_password.split("$")
        _, _, iterations_str = method.split(":")
        iterations = int(iterations_str)
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            plain_password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        )
        return hmac.compare_digest(derived.hex(), stored_hash)
    except Exception:
        return False


def create_access_token(
    data: dict, expires_delta: Optional[timedelta] = None
) -> Tuple[str, datetime, int]:
    """Generate signed JWT access token with expiration time metadata."""
    to_encode = data.copy()
    duration = expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    expire = datetime.now(timezone.utc) + duration
    to_encode.update({"exp": expire})
    token = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return token, expire, int(duration.total_seconds())


async def authenticate_admin(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = None,
    x_api_key: Optional[str] = None,
    query_api_key: Optional[str] = None,
) -> dict:
    """Core admin authentication validator for both API routes and frontend guards."""
    from app.models import Admin, ApiKey

    # 1. Check API Key candidates (header, query param, or Bearer gpmc_...)
    candidate_key = None
    if isinstance(x_api_key, str) and x_api_key.strip():
        candidate_key = x_api_key.strip()
    elif isinstance(query_api_key, str) and query_api_key.strip():
        candidate_key = query_api_key.strip()
    elif credentials and hasattr(credentials, "credentials") and credentials.credentials:
        bearer_val = credentials.credentials.strip()
        if bearer_val.startswith("gpmc_") or len(bearer_val.split(".")) != 3:
            candidate_key = bearer_val

    if not candidate_key:
        hdr_key = request.headers.get("X-API-Key")
        query_key = request.query_params.get("api_key")
        auth_hdr = request.headers.get("Authorization", "")
        if hdr_key and hdr_key.strip():
            candidate_key = hdr_key.strip()
        elif query_key and query_key.strip():
            candidate_key = query_key.strip()
        elif auth_hdr.startswith("Bearer "):
            bearer_val = auth_hdr[7:].strip()
            if bearer_val.startswith("gpmc_") or len(bearer_val.split(".")) != 3:
                candidate_key = bearer_val

    if candidate_key:
        async with get_db() as db:
            stmt = select(ApiKey).where(ApiKey.key == candidate_key, ApiKey.is_active.is_(True))
            res = await db.execute(stmt)
            key_obj = res.scalar_one_or_none()

            if not key_obj:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or revoked API key",
                    headers={"WWW-Authenticate": "ApiKey"},
                )

            # Check expiration if set
            if key_obj.expires_at:
                now_utc = datetime.now(timezone.utc)
                exp_utc = key_obj.expires_at
                if exp_utc.tzinfo is None:
                    exp_utc = exp_utc.replace(tzinfo=timezone.utc)
                if now_utc > exp_utc:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="API key has expired",
                        headers={"WWW-Authenticate": "ApiKey"},
                    )

            # Record last usage asynchronously
            await db.execute(
                update(ApiKey)
                .where(ApiKey.id == key_obj.id)
                .values(last_used_at=datetime.now(timezone.utc))
            )

            return {
                "id": key_obj.id,
                "username": f"apikey:{key_obj.name}",
                "is_active": True,
                "auth_type": "api_key",
                "key_id": key_obj.id,
                "key_name": key_obj.name,
            }

    # 2. Check JWT Bearer token or session cookie
    token = None
    if credentials and hasattr(credentials, "credentials") and credentials.credentials:
        token = credentials.credentials.strip()
    elif request.headers.get("Authorization", "").startswith("Bearer "):
        token = request.headers.get("Authorization")[7:].strip()
    elif request.cookies.get("access_token"):
        token = request.cookies.get("access_token").strip()
    elif request.query_params.get("token"):
        token = request.query_params.get("token").strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except JWTError:
        async with get_db(write=False) as db:
            stmt = select(ApiKey).where(ApiKey.key == token, ApiKey.is_active.is_(True))
            res = await db.execute(stmt)
            key_obj = res.scalar_one_or_none()
            if key_obj:
                return {
                    "id": key_obj.id,
                    "username": f"apikey:{key_obj.name}",
                    "is_active": True,
                    "auth_type": "api_key",
                    "key_id": key_obj.id,
                    "key_name": key_obj.name,
                }

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    async with get_db(write=False) as db:
        result = await db.execute(select(Admin).where(Admin.username == username))
        admin = result.scalar_one_or_none()
        if not admin or not admin.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Admin account inactive or deleted",
            )
        return {
            "id": admin.id,
            "username": admin.username,
            "is_active": admin.is_active,
            "auth_type": "jwt",
        }


async def get_current_admin(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    x_api_key: Optional[str] = Depends(api_key_header),
    query_api_key: Optional[str] = Depends(api_key_query),
) -> dict:
    """FastAPI dependency for authenticating admin users."""
    return await authenticate_admin(request, credentials, x_api_key, query_api_key)


async def is_authenticated_admin(request: Request) -> bool:
    """Return True if request has valid admin credentials, False otherwise."""
    try:
        await authenticate_admin(request)
        return True
    except Exception:
        return False



