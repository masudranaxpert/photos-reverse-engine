"""
Pluggable cookie and session stores supporting File (cookies.txt) and Database backends.
"""

import abc
import datetime
import os
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from .parser import format_netscape_cookies, parse_cookie_source


class BaseCookieStore(abc.ABC):
    """Abstract base class for cookie and session persistence."""

    @abc.abstractmethod
    def load_session_blob(self, session_id: str) -> Optional[str]:
        """Load serialized httpcloak session blob for the given session ID."""
        pass

    @abc.abstractmethod
    def save_session_blob(
        self,
        session_id: str,
        blob: str,
        account: Optional[str] = None,
        is_valid: Optional[bool] = None,
    ) -> None:
        """Persist session blob and metadata."""
        pass

    @abc.abstractmethod
    def load_cookies(self, session_id: str) -> List[Dict[str, Any]]:
        """Load cookie dictionaries for the given session ID."""
        pass

    @abc.abstractmethod
    def save_cookies(self, session_id: str, cookies: List[Dict[str, Any]]) -> None:
        """Save raw cookie dictionaries for the given session ID."""
        pass

    def close(self) -> None:
        """Release any open resources or database connections."""
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class FileCookieStore(BaseCookieStore):
    """
    File-based cookie store using cookies.txt (Netscape or JSON format)
    and an adjacent .session file for serialized httpcloak TLS session state.
    """

    def __init__(self, file_path: Union[str, Path] = "cookies.txt", session_dir: Optional[Union[str, Path]] = None):
        self.file_path = Path(file_path).resolve()
        self.session_dir = Path(session_dir).resolve() if session_dir else self.file_path.parent
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _blob_path(self, session_id: str) -> Path:
        safe_id = re.sub(r"[^\w\-.]", "_", session_id or "default")
        return self.session_dir / f"{self.file_path.stem}_{safe_id}.session"

    def load_session_blob(self, session_id: str) -> Optional[str]:
        blob_file = self._blob_path(session_id)
        if blob_file.is_file():
            try:
                return blob_file.read_text(encoding="utf-8").strip()
            except Exception:
                return None
        return None

    def save_session_blob(
        self,
        session_id: str,
        blob: str,
        account: Optional[str] = None,
        is_valid: Optional[bool] = None,
    ) -> None:
        blob_file = self._blob_path(session_id)
        tmp_file = blob_file.with_suffix(".tmp")
        with self._lock:
            tmp_file.write_text(blob, encoding="utf-8")
            tmp_file.replace(blob_file)

    def load_cookies(self, session_id: str) -> List[Dict[str, Any]]:
        if not self.file_path.is_file():
            return []
        try:
            content = self.file_path.read_text(encoding="utf-8")
            cookies, _ = parse_cookie_source(content)
            return cookies
        except Exception:
            return []

    def save_cookies(self, session_id: str, cookies: List[Dict[str, Any]]) -> None:
        content = format_netscape_cookies(cookies)
        tmp_file = self.file_path.with_suffix(".tmp")
        with self._lock:
            tmp_file.write_text(content, encoding="utf-8")
            tmp_file.replace(self.file_path)


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _sanitize_ident(name: str, fallback: str) -> str:
    """Ensure database identifier consists only of alphanumeric characters and underscores."""
    if _IDENTIFIER_RE.match(name or ""):
        return name
    return fallback


class DatabaseCookieStore(BaseCookieStore):
    """
    Database cookie store with customizable table and column names.
    Supports SQLite (file path or Connection) and any PEP-249 DB-API connection.
    Guarantees thread-safe queries and zero connection leaks.
    """

    def __init__(
        self,
        db_source: Union[str, Path, Any] = "cookies.db",
        table_name: str = "cookies",
        session_id_col: str = "session_id",
        blob_col: str = "session_blob",
        is_active_col: str = "is_active",
        account_col: str = "last_checked_account",
        is_valid_col: str = "last_status_ok",
        updated_at_col: str = "updated_at",
        auto_create_table: bool = True,
    ):
        self.table_name = _sanitize_ident(table_name, "cookies")
        self.session_id_col = _sanitize_ident(session_id_col, "session_id")
        self.blob_col = _sanitize_ident(blob_col, "session_blob")
        self.is_active_col = _sanitize_ident(is_active_col, "is_active")
        self.account_col = _sanitize_ident(account_col, "last_checked_account")
        self.is_valid_col = _sanitize_ident(is_valid_col, "last_status_ok")
        self.updated_at_col = _sanitize_ident(updated_at_col, "updated_at")

        self._lock = threading.Lock()
        self._owned_conn = False

        if isinstance(db_source, (str, Path)):
            db_path = str(Path(db_source).resolve())
            self._conn = sqlite3.connect(db_path, check_same_thread=False)
            self._owned_conn = True
            self._is_sqlite = True
        else:
            self._conn = db_source
            self._is_sqlite = "sqlite" in type(db_source).__module__.lower()

        if auto_create_table and self._is_sqlite:
            self._create_sqlite_table()

    def _create_sqlite_table(self) -> None:
        """Create the table with the specified column schema if it does not already exist."""
        sql = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            {self.session_id_col} TEXT PRIMARY KEY,
            {self.blob_col} TEXT DEFAULT '',
            {self.is_active_col} INTEGER DEFAULT 1,
            {self.account_col} TEXT DEFAULT '',
            {self.is_valid_col} INTEGER DEFAULT NULL,
            {self.updated_at_col} TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql)
            self._conn.commit()

    def load_session_blob(self, session_id: str) -> Optional[str]:
        sql = f"""
        SELECT {self.blob_col} FROM {self.table_name}
        WHERE {self.session_id_col} = ? AND {self.is_active_col} = 1
        LIMIT 1
        """
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, (session_id or "default",))
            row = cur.fetchone()
            if row and row[0]:
                return row[0]
        return None

    def save_session_blob(
        self,
        session_id: str,
        blob: str,
        account: Optional[str] = None,
        is_valid: Optional[bool] = None,
    ) -> None:
        sid = session_id or "default"
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Try update first
        updates = [f"{self.blob_col} = ?", f"{self.updated_at_col} = ?"]
        params: List[Any] = [blob, now_str]

        if account is not None:
            updates.append(f"{self.account_col} = ?")
            params.append(account)
        if is_valid is not None:
            updates.append(f"{self.is_valid_col} = ?")
            params.append(1 if is_valid else 0)

        params.append(sid)
        update_sql = f"UPDATE {self.table_name} SET {', '.join(updates)} WHERE {self.session_id_col} = ?"

        with self._lock:
            cur = self._conn.cursor()
            cur.execute(update_sql, tuple(params))
            if cur.rowcount == 0:
                # Row does not exist yet; insert it
                insert_cols = [self.session_id_col, self.blob_col, self.is_active_col, self.updated_at_col]
                insert_vals: List[Any] = [sid, blob, 1, now_str]
                if account is not None:
                    insert_cols.append(self.account_col)
                    insert_vals.append(account)
                if is_valid is not None:
                    insert_cols.append(self.is_valid_col)
                    insert_vals.append(1 if is_valid else 0)

                placeholders = ", ".join(["?"] * len(insert_cols))
                insert_sql = f"INSERT INTO {self.table_name} ({', '.join(insert_cols)}) VALUES ({placeholders})"
                cur.execute(insert_sql, tuple(insert_vals))
            self._conn.commit()

    def load_cookies(self, session_id: str) -> List[Dict[str, Any]]:
        # DatabaseStore manages full session blobs directly via httpcloak
        return []

    def save_cookies(self, session_id: str, cookies: List[Dict[str, Any]]) -> None:
        pass

    def close(self) -> None:
        """Safely close owned database connections."""
        with self._lock:
            if self._owned_conn and self._conn:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    def __del__(self):
        self.close()
