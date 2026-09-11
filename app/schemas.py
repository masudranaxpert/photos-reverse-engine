from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


# --- Authentication & Admins ---
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    expires_in: int
    expires_at: str
    expires_timestamp: int


class AdminCreateRequest(BaseModel):
    username: str
    password: str


class AdminUpdateRequest(BaseModel):
    password: Optional[str] = None
    is_active: Optional[bool] = None


class AdminResponse(BaseModel):
    id: int
    username: str
    is_active: bool
    created_at: str


# --- Web Client Sessions ---
class WebSessionCreate(BaseModel):
    name: str = Field(default="Web Cookies", description="Optional session label")
    cookies: str = Field(..., description="Raw cookies in Netscape, JSON, or header format")


class WebSessionUpdate(BaseModel):
    name: Optional[str] = None
    cookies: Optional[str] = None
    is_active: Optional[bool] = None


class WebSessionResponse(BaseModel):
    id: int
    session_id: str
    name: str
    account_email: Optional[str] = None
    is_active: bool
    has_blob: bool
    created_at: str
    updated_at: str


class WebSessionDetailResponse(WebSessionResponse):
    raw_cookies: Optional[str] = None
    session_blob_json: Optional[str] = Field(
        None, description="Decoded pretty-printed JSON of the saved session state"
    )
    session_blob_hex: Optional[str] = Field(
        None, description="Raw serialized session bytes as hex, exactly as stored in the database"
    )

class WebSessionStatusResponse(BaseModel):
    valid: bool
    account: Optional[str] = None
    message: str


class AccountResetRequest(BaseModel):
    session_id: Optional[str] = Field(None, description="Optional specific web session ID")
    confirm: bool = Field(..., description="Must be true to authorize permanent wiping of library")


class AccountResetResponse(BaseModel):
    success: bool
    total_deleted: int
    trash_emptied: bool
    message: str


# --- Mobile Client Accounts ---
class MobileAccountCreate(BaseModel):
    auth_data: str = Field(..., description="Complete Google Photos Mobile Client AUTH_DATA string")


class MobileAccountResponse(BaseModel):
    id: int
    email: str
    is_active: bool
    created_at: str
    updated_at: str


# --- API Key Management ---
class ApiKeyCreateRequest(BaseModel):
    name: str = Field(..., description="Descriptive label for this API key, e.g. 'Integration Bot'")
    expires_days: Optional[int] = Field(None, description="Optional expiry in days (None = never expires)")


class ApiKeyUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, description="Updated descriptive label for this API key")
    is_active: Optional[bool] = Field(None, description="Enable or disable this API key")
    expires_days: Optional[int] = Field(
        None,
        description="Reset expiry: 0 = permanent (no expiry), >0 = N days from today, None = leave unchanged",
    )


class ApiKeyResponse(BaseModel):
    id: int
    name: str
    prefix: str
    is_active: bool
    created_at: str
    last_used_at: Optional[str] = None
    expires_at: Optional[str] = None



class ApiKeyCreatedResponse(ApiKeyResponse):
    api_key: str = Field(..., description="Full secret API key. Store safely, shown only once.")



class ApiKeyRevealResponse(BaseModel):
    id: int
    name: str
    api_key: str = Field(..., description="Full secret API key (admin-only reveal)")

# ──────────────────────────── Upload Pipeline Schemas ────────────────────────────


class UploadRequest(BaseModel):
    drive_id: str = Field(..., description="Google Drive file ID to import")


class UploadResponse(BaseModel):
    token: str = Field(..., description="32-char URL-safe token for /download/{token}")
    drive_id: str
    status: str = Field(..., description="imported | already_exists")
    filename: Optional[str] = None
    file_size: Optional[int] = None
    download_url: Optional[str] = Field(None, description="Expiring 45-character download URL valid for 1.5 hours")


class DownloadTokenResponse(BaseModel):
    token: str
    status: str = Field(..., description="processing | ready | not_found | expired | failed")
    download_url: Optional[str] = None
    filename: Optional[str] = None
    file_size: Optional[int] = None
    is_permanent: Optional[bool] = False
    has_stream_cache: Optional[bool] = False


class JobResponse(BaseModel):
    id: int
    job_type: str
    status: str
    payload: Optional[str] = None
    result: Optional[str] = None
    run_every_sec: Optional[int] = None
    next_run_at: Optional[str] = None
    last_run_at: Optional[str] = None
    created_at: str

