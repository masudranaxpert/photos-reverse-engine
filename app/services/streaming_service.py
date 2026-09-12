"""
Streaming service module for Google Photos DASH manifests and media streams.

Responsible for fetching streaming manifests via native photos_engine,
extracting progressive video & audio representation URLs, resolving labels,
and formatting clean playback payload for frontend video players without server-side proxying.
"""
import logging
import xml.etree.ElementTree as ET
from typing import Any, Dict, List

logger = logging.getLogger("photos_engine.streaming")


def parse_mpd_streams(manifest_xml: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Extract direct video and audio URLs from a Google Photos DASH MPD XML manifest.

    Args:
        manifest_xml: Raw XML string of the MPD manifest.

    Returns:
        Dict with 'videos' and 'audios' lists of parsed stream metadata.
    """
    root = ET.fromstring(manifest_xml)
    ns = {"mpd": "urn:mpeg:DASH:schema:MPD:2011"}
    videos: List[Dict[str, Any]] = []
    audios: List[Dict[str, Any]] = []

    for as_elem in root.findall(".//mpd:AdaptationSet", ns):
        mime = as_elem.attrib.get("mimeType", "")
        for rep in as_elem.findall("mpd:Representation", ns):
            base_url_elem = rep.find("mpd:BaseURL", ns)
            if base_url_elem is None or not base_url_elem.text:
                continue
            url = base_url_elem.text.strip()
            bw = int(rep.attrib.get("bandwidth", 0))
            w = rep.attrib.get("width", "")
            h = rep.attrib.get("height", "")
            codecs = rep.attrib.get("codecs", "")

            # User-friendly label (1080P, 720P, 480P, 360P, etc.)
            # Use the shorter dimension (height for landscape, width for portrait)
            label = ""
            w_int = int(w) if w and w.isdigit() else 0
            h_int = int(h) if h and h.isdigit() else 0
            dim = min(w_int, h_int) if (w_int and h_int) else (w_int or h_int)

            if dim >= 1000:
                label = "1080P"
            elif dim >= 700:
                label = "720P"
            elif dim >= 450:
                label = "480P"
            elif dim >= 340:
                label = "360P"
            elif dim >= 220:
                label = "240P"
            elif dim > 0:
                label = "144P"
            elif bw > 0:
                label = f"{bw // 1000}kbps"

            resolution = f"{w}x{h}" if (w and h) else ""
            entry = {
                "url": url,
                "bandwidth": bw,
                "resolution": resolution,
                "label": label,
                "codecs": codecs,
                "is_otf": "picasa_otf" in url,
            }

            if mime.startswith("video"):
                videos.append(entry)
            elif mime.startswith("audio"):
                audios.append(entry)

    # Filter out fragmented OTF streams (source/picasa_otf) — never send unplayable fragmented URLs
    clean_videos = [v for v in videos if not v["is_otf"]]
    clean_videos.sort(key=lambda x: x["bandwidth"], reverse=True)
    audios.sort(key=lambda x: x["bandwidth"], reverse=True)

    return {
        "videos": clean_videos,
        "audios": audios if clean_videos else [],
    }


async def fetch_manifest_via_proxy(proxy_base: str, media_key: str, token: str, user_agent: str) -> str:
    """Fetch DASH MPD manifest through Cloudflare Worker proxy using httpcloak."""
    import httpcloak

    manifest_url = f"{proxy_base.rstrip('/')}/p/{media_key}%3Dmm,dash-vm"
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": user_agent or "com.google.android.apps.photos/6.80.0.627584067 (Linux; U; Android 14; Pixel 5; Build/UP1A.231005.007)",
        "Accept-Encoding": "gzip",
    }

    with httpcloak.Session(preset="chrome-latest", timeout=15) as session:
        resp = await session.post_async(manifest_url, headers=headers)
        if not resp.ok:
            raise RuntimeError(f"Cloudflare proxy HTTP {resp.status_code}: {resp.text[:120]}")
        return resp.text


async def get_streaming_data_for_media_key(media_key: str) -> Dict[str, Any]:
    """
    Fetch and parse streaming video and audio tracks for a given media key.

    Args:
        media_key: Google Photos permanent media key.

    Returns:
        Dict containing videos, audios, and raw manifest XML.
    """
    from app.config import MANIFEST_PROXY_URL
    from app.services.mobile_service import get_mobile_client

    client, _ = await get_mobile_client(client_type="streaming")

    if MANIFEST_PROXY_URL:
        # Enforce Cloudflare Worker proxy strictly — zero fallback to prevent origin IP leakage
        token = await client.get_token_async()
        manifest_xml = await fetch_manifest_via_proxy(
            MANIFEST_PROXY_URL,
            media_key,
            token,
            getattr(client, "user_agent", ""),
        )
        logger.info("Successfully fetched DASH manifest via Cloudflare proxy for media key %s", media_key[:16])
    else:
        manifest_xml = await client.get_stream_manifest_async(media_key, protocol="dash")

    streams = parse_mpd_streams(manifest_xml)

    return {
        "videos": streams["videos"],
        "audios": streams["audios"],
        "manifest": manifest_xml,
    }
