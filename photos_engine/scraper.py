"""
Scraper module for Google Photos shared album links using httpcloak and selectolax.
"""

import json
import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

import httpcloak
from selectolax.parser import HTMLParser

from .models import ScrapedShare


def scrape_share_url(url: str, timeout: int = 30) -> ScrapedShare:
    """
    Fetch and parse a Google Photos shared album URL to extract album_key, auth_key, and media_keys.

    Args:
        url: Public Google Photos share URL (photos.app.goo.gl or photos.google.com/share/...)
        timeout: HTTP request timeout in seconds

    Returns:
        ScrapedShare dataclass containing parsed keys
    """
    resp = httpcloak.get(url, allow_redirects=True, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to fetch share URL: status {resp.status_code}")

    final_url = resp.url
    parsed = urlparse(final_url)

    # 1. Extract keys from final URL
    m_album = re.search(r"/share/([^/?]+)", parsed.path)
    album_key = m_album.group(1) if m_album else ""
    auth_key = parse_qs(parsed.query).get("key", [""])[0]

    # 2. Extract media keys using fast Selectolax DOM traversal
    tree = HTMLParser(resp.text)
    media_keys = []
    seen = set()

    for node in tree.css('a[href*="/photo/"]'):
        href = node.attributes.get("href", "")
        if href:
            m = re.search(r"/photo/([^/?]+)", href)
            if m:
                key = m.group(1)
                if key not in seen:
                    seen.add(key)
                    media_keys.append(key)

    # 3. Fallback to embedded script payload if DOM didn't yield all keys
    match = re.search(r"data:\s*(\[.*?\])\s*,\s*sideChannel:", resp.text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            if len(data) > 1 and isinstance(data[1], list):
                for item in data[1]:
                    if isinstance(item, list) and len(item) > 0 and isinstance(item[0], str):
                        key = item[0]
                        if key not in seen:
                            seen.add(key)
                            media_keys.append(key)

            if not album_key and len(data) > 3 and isinstance(data[3], list) and len(data[3]) > 0:
                album_key = data[3][0]

            if not auth_key and len(data) > 3 and isinstance(data[3], list) and len(data[3]) > 14:
                auth_key = data[3][14]
        except (json.JSONDecodeError, IndexError, TypeError):
            pass

    return ScrapedShare(
        share_url=final_url,
        album_key=album_key,
        auth_key=auth_key,
        media_keys=media_keys,
    )
