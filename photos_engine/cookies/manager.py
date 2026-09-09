"""
Thread-safe session manager maintaining cached httpcloak sessions and debounced persistence.
"""

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Union

import httpcloak
from .parser import parse_cookie_source
from .store import BaseCookieStore, FileCookieStore

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Manages httpcloak.Session lifecycle, in-memory pooling, and debounced synchronization.
    Guarantees thread-safety, TLS session reuse, and zero socket/connection leaks.
    """

    def __init__(
        self,
        store: Optional[BaseCookieStore] = None,
        sync_interval_seconds: float = 30.0,
    ):
        self.store = store or FileCookieStore("cookies.txt")
        self.sync_interval_seconds = sync_interval_seconds

        self._sessions: Dict[str, httpcloak.Session] = {}
        self._last_sync_time: Dict[str, float] = {}
        self._lock = threading.RLock()

    def get_session(
        self,
        session_id: str = "default",
        raw_cookies: Optional[Union[str, List[Dict[str, Any]]]] = None,
    ) -> httpcloak.Session:
        """
        Get or initialize a thread-safe httpcloak.Session for session_id.
        Restores from store blob if present, otherwise injects provided or stored cookies.
        """
        sid = (session_id or "default").strip()

        with self._lock:
            if sid in self._sessions:
                return self._sessions[sid]

            session: Optional[httpcloak.Session] = None

            # 1. Attempt to restore from serialized session blob
            blob = self.store.load_session_blob(sid)
            if blob:
                try:
                    session = httpcloak.Session.unmarshal(blob)
                    session.set_follow_redirects(False)
                    logger.debug("Restored httpcloak session '%s' from persistent blob", sid)
                except Exception as exc:
                    logger.warning("Failed to unmarshal session blob for '%s': %s", sid, exc)

            # 2. If no blob or unmarshal failed, initialize fresh session
            if session is None:
                session = httpcloak.Session(
                    preset="firefox-latest",
                    timeout=30,
                    allow_redirects=False,
                )

                # Collect cookies to inject
                cookie_items: List[Dict[str, Any]] = []
                if isinstance(raw_cookies, str) and raw_cookies.strip():
                    parsed, _ = parse_cookie_source(raw_cookies)
                    cookie_items = parsed
                elif isinstance(raw_cookies, list):
                    cookie_items = raw_cookies
                else:
                    cookie_items = self.store.load_cookies(sid)

                for item in cookie_items:
                    if isinstance(item, dict) and item.get("name") and item.get("value"):
                        session.set_cookie(
                            str(item["name"]),
                            str(item["value"]),
                            domain=str(item.get("domain") or ".google.com"),
                            path=str(item.get("path") or "/"),
                            secure=bool(item.get("secure", False)),
                            http_only=bool(item.get("http_only", False)),
                        )

            self._sessions[sid] = session
            return session

    def debounced_sync(
        self,
        session_id: str,
        session: httpcloak.Session,
        account: Optional[str] = None,
        is_valid: Optional[bool] = None,
        force: bool = False,
    ) -> None:
        """
        Persist serialized session blob (containing updated cookies and TLS state) to store.
        Debounced to minimize disk/DB write overhead.
        """
        sid = (session_id or "default").strip()
        now = time.monotonic()

        with self._lock:
            last = self._last_sync_time.get(sid, 0.0)
            if not force and (now - last < self.sync_interval_seconds):
                return

            self._last_sync_time[sid] = now
            try:
                blob = session.marshal()
                self.store.save_session_blob(
                    sid,
                    blob,
                    account=account,
                    is_valid=is_valid,
                )
            except Exception as exc:
                logger.error("Failed to sync session '%s' to store: %s", sid, exc)

    def invalidate(self, session_id: str = "default") -> None:
        """Close and discard cached session instance to force re-creation."""
        sid = (session_id or "default").strip()
        with self._lock:
            if sid in self._sessions:
                sess = self._sessions.pop(sid)
                try:
                    sess.close()
                except Exception:
                    pass
            self._last_sync_time.pop(sid, None)

    def close(self) -> None:
        """Close all cached httpcloak sessions and underlying store."""
        with self._lock:
            for sid, sess in list(self._sessions.items()):
                try:
                    # Final sync before shutdown
                    blob = sess.marshal()
                    self.store.save_session_blob(sid, blob)
                except Exception:
                    pass
                try:
                    sess.close()
                except Exception:
                    pass
            self._sessions.clear()
            self._last_sync_time.clear()
            self.store.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        self.close()
