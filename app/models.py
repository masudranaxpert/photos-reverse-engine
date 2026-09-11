from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(AsyncAttrs, DeclarativeBase):
    pass


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)


class MobileAccount(Base):
    __tablename__ = "mobile_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, index=True)
    auth_data: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )


class WebSession(Base):
    __tablename__ = "web_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    account_email: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    raw_cookies: Mapped[str] = mapped_column(Text, nullable=False)
    session_blob: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )


class DownloadCache(Base):
    __tablename__ = "download_cache"

    media_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    download_url: Mapped[str] = mapped_column(Text, nullable=False)
    dedup_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="web", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)





class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    prefix: Mapped[str] = mapped_column(String(30), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# Additional multi-column index for cache lookup
Index("idx_download_cache_lookup", DownloadCache.media_key, DownloadCache.expires_at)


class StreamCache(Base):
    """Cached DASH manifest representations (video & audio stream URLs) with 20-minute validity."""

    __tablename__ = "stream_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    media_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    drive_ref_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("drive_refs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    video_streams: Mapped[str] = mapped_column(Text, nullable=False)   # JSON string
    audio_streams: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # JSON string
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


Index("idx_stream_cache_lookup", StreamCache.media_key, StreamCache.expires_at)


# ──────────────────────────── Upload Pipeline Models ────────────────────────────


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )


class DriveRef(Base):
    """One row per unique drive_id — carries the public download token."""

    __tablename__ = "drive_refs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    drive_id: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    label: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    filename: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    file_status: Mapped[str] = mapped_column(String(50), default="ok", nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    api_key_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)


class TempImport(Base):
    """Transient row created right after Drive→Photos import, before background promotion."""

    __tablename__ = "temp_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    drive_ref_id: Mapped[int] = mapped_column(Integer, ForeignKey("drive_refs.id", ondelete="CASCADE"), nullable=False, index=True)
    media_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    dedup_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    share_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    promote_after: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class PermanentItem(Base):
    """Promoted row: drive_ref_id, media_key, owner email."""

    __tablename__ = "permanent_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    drive_ref_id: Mapped[int] = mapped_column(Integer, ForeignKey("drive_refs.id", ondelete="CASCADE"), nullable=False, index=True)
    media_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(150), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    last_manifest_check: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class BackgroundJob(Base):
    """Persistent job queue — every async task is tracked here for the dashboard."""

    __tablename__ = "background_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # pending | running | done | failed
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # JSON
    result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)    # JSON
    # recurring jobs: seconds between runs
    run_every_sec: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)


class SystemNotice(Base):
    """System alerts and notice board: tracks quota errors, cookie failures, import issues."""

    __tablename__ = "system_notices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String(20), default="warning", nullable=False)  # info | warning | error | critical
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(50), default="system", nullable=False, index=True)  # quota | upload | cookies | mobile
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
