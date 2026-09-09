"""
Cookie and session management package for Google Photos web operations.
"""

from .manager import SessionManager
from .parser import (
    REQUIRED_COOKIE_KEYS,
    build_cookie_header,
    format_netscape_cookies,
    parse_cookie_source,
    parse_json_cookies,
    parse_netscape_cookies,
)
from .store import (
    BaseCookieStore,
    DatabaseCookieStore,
    FileCookieStore,
)

__all__ = [
    "REQUIRED_COOKIE_KEYS",
    "BaseCookieStore",
    "DatabaseCookieStore",
    "FileCookieStore",
    "SessionManager",
    "build_cookie_header",
    "format_netscape_cookies",
    "parse_cookie_source",
    "parse_json_cookies",
    "parse_netscape_cookies",
]
