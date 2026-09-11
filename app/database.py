import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

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
)


@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enforce SQLite WAL mode and concurrency PRAGMAs on every low-level connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=10000")
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
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager yielding a managed SQLAlchemy AsyncSession."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Depends dependency yielding an AsyncSession."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Initialize all ORM models and tables asynchronously using SQLAlchemy."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Ensure schema migrations for existing databases
        def _migrate(connection):
            cur = connection.connection.cursor()
            cur.execute("PRAGMA table_info(drive_refs)")
            cols = [c[1] for c in cur.fetchall()]
            if "error_message" not in cols:
                cur.execute("ALTER TABLE drive_refs ADD COLUMN error_message TEXT")
            if "api_key_id" not in cols:
                cur.execute("ALTER TABLE drive_refs ADD COLUMN api_key_id INTEGER REFERENCES api_keys(id) ON DELETE SET NULL")
                cur.execute("CREATE INDEX IF NOT EXISTS ix_drive_refs_api_key_id ON drive_refs(api_key_id)")
            cur.execute("PRAGMA table_info(permanent_items)")
            perm_cols = [c[1] for c in cur.fetchall()]
            if perm_cols and "last_manifest_check" not in perm_cols:
                cur.execute("ALTER TABLE permanent_items ADD COLUMN last_manifest_check DATETIME")
            cur.close()
        await conn.run_sync(_migrate)
    logger.info("SQLAlchemy ORM tables initialized successfully in WAL mode.")

