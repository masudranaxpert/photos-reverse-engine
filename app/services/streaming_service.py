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
            label = ""
            if w and int(w) >= 1900:
                label = "1080P"
            elif w and int(w) >= 1200:
                label = "720P"
            elif w and int(w) >= 800:
                label = "480P"
            elif w and int(w) >= 600:
                label = "360P"
            elif h:
                label = f"{h}P"
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

    # Prefer non-otf complete progressive streams if available
    clean_videos = [v for v in videos if not v["is_otf"]]
    final_videos = clean_videos if clean_videos else videos

    final_videos.sort(key=lambda x: x["bandwidth"], reverse=True)
    audios.sort(key=lambda x: x["bandwidth"], reverse=True)

    return {
        "videos": final_videos,
        "audios": audios,
    }


async def fetch_manifest_via_proxy(proxy_base: str, media_key: str, token: str, user_agent: str) -> str:
    """Fetch DASH MPD manifest through Cloudflare Worker proxy to mask origin server IP."""
    import asyncio
    import gzip
    import urllib.request

    manifest_url = f"{proxy_base.rstrip('/')}/p/{media_key}%3Dmm,dash-vm"
    req = urllib.request.Request(
        manifest_url,
        data=b"",
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": user_agent or "com.google.android.apps.photos/6.80.0.627584067 (Linux; U; Android 14; Pixel 5; Build/UP1A.231005.007)",
            "Accept-Encoding": "gzip",
        },
    )

    loop = asyncio.get_running_loop()

    def _fetch() -> str:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
            if resp.info().get("Content-Encoding") == "gzip":
                data = gzip.decompress(data)
            return data.decode("utf-8")

    return await loop.run_in_executor(None, _fetch)


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

    client, _ = await get_mobile_client()

    manifest_xml = None
    if MANIFEST_PROXY_URL:
        try:
            token = await client.get_token_async()
            manifest_xml = await fetch_manifest_via_proxy(
                MANIFEST_PROXY_URL,
                media_key,
                token,
                getattr(client, "user_agent", ""),
            )
            logger.info("Successfully fetched DASH manifest via Cloudflare proxy for media key %s", media_key[:16])
        except Exception as exc:
            logger.warning("Cloudflare manifest proxy failed (%s): falling back to direct photos_engine", exc)

    if not manifest_xml:
        manifest_xml = await client.get_stream_manifest_async(media_key, protocol="dash")

    streams = parse_mpd_streams(manifest_xml)

    return {
        "videos": streams["videos"],
        "audios": streams["audios"],
        "manifest": manifest_xml,
    }
