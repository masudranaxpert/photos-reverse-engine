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


async def get_streaming_data_for_media_key(media_key: str) -> Dict[str, Any]:
    """
    Fetch and parse streaming video and audio tracks for a given media key.

    Args:
        media_key: Google Photos permanent media key.

    Returns:
        Dict containing videos, audios, and raw manifest XML.
    """
    from app.services.mobile_service import get_mobile_client

    client, _ = await get_mobile_client()
    manifest_xml = await client.get_stream_manifest_async(media_key, protocol="dash")
    streams = parse_mpd_streams(manifest_xml)

    return {
        "videos": streams["videos"],
        "audios": streams["audios"],
        "manifest": manifest_xml,
    }
