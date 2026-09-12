from datetime import datetime, timezone
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

def utc_now_naive() -> datetime:
    """Return naive UTC datetime for SQLite compatibility."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import DB_PATH
from app.models import Base

logger = logging.getLogger(__name__)

# SQLAlchemy async SQLite connection string
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    pool_size=5,
    max_overflow=0,
    pool_timeout=30,
    pool_recycle=3600,
    connect_args={"timeout": 60, "check_same_thread": False},
)


@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enforce SQLite WAL mode and concurrency PRAGMAs on every low-level connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    mode = cursor.fetchone()[0]
    if str(mode).lower() != "wal":
        logger.error("SQLite WAL mode NOT enabled: journal_mode=%s", mode)
    cursor.execute("PRAGMA busy_timeout=60000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


@asynccontextmanager
async def get_db(write: bool = True) -> AsyncGenerator[AsyncSession, None]:
    """Async context manager yielding a managed SQLAlchemy AsyncSession.

    write=True emits BEGIN IMMEDIATE upfront to serialize writers cleanly.
    write=False allows concurrent WAL reads without grabbing RESERVED locks.
    """
    async with AsyncSessionLocal() as session:
        if write:
            conn = await session.connection()
            await conn.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            yield session
            if write and session.in_transaction():
                await session.commit()
        except Exception:
            if session.in_transaction():
                await session.rollback()
            raise


async def get_db_session(write: bool = False) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Depends dependency yielding an AsyncSession."""
    async with get_db(write=write) as session:
        yield session


async def init_db() -> None:
    """Initialize all ORM models and tables asynchronously using SQLAlchemy."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("SQLAlchemy ORM tables initialized successfully in WAL mode.")


