"""
tests/test_stream_cache.py
Targeted test suite for 20-minute stream cache, 10-minute throttling, and dashboard endpoints.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import unittest
from starlette.testclient import TestClient

from app.database import get_db, init_db
from app.main import app
from app.models import DriveRef, PermanentItem, StreamCache
from app.services.stream_cache_service import (
    cleanup_expired_stream_cache,
    get_cached_stream,
    is_stream_cached,
    set_cached_stream,
)


class TestStreamCacheSystem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        asyncio.run(init_db())

    def test_01_stream_cache_lifecycle(self):
        """Test set, get, is_cached, expiration, and cleanup in stream_cache_service."""
        media_key = "test_media_key_stream_123"
        videos = [
            {"url": "https://example.com/v1080.mp4", "bandwidth": 5000000, "label": "1080P", "resolution": "1920x1080"},
            {"url": "https://example.com/v720.mp4", "bandwidth": 2500000, "label": "720P", "resolution": "1280x720"},
        ]
        audios = [{"url": "https://example.com/a128.mp4", "bandwidth": 128000}]

        # Initially not cached
        self.assertFalse(asyncio.run(is_stream_cached(media_key)))
        self.assertIsNone(asyncio.run(get_cached_stream(media_key)))

        # Store in cache (20 min default TTL)
        asyncio.run(
            set_cached_stream(
                media_key=media_key,
                video_streams=videos,
                audio_streams=audios,
            )
        )

        # Should now be cached
        self.assertTrue(asyncio.run(is_stream_cached(media_key)))
        cached = asyncio.run(get_cached_stream(media_key))
        self.assertIsNotNone(cached)
        self.assertEqual(cached["media_key"], media_key)
        self.assertEqual(len(cached["videos"]), 2)
        self.assertEqual(cached["videos"][0]["label"], "1080P")
        self.assertEqual(len(cached["audios"]), 1)

        # Manually set expires_at in the past
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        past = now - timedelta(minutes=5)

        async def _expire():
            async with get_db() as db:
                await db.execute(
                    StreamCache.__table__.update()
                    .where(StreamCache.media_key == media_key)
                    .values(expires_at=past)
                )

        asyncio.run(_expire())

        # Should not be returned once expired
        self.assertFalse(asyncio.run(is_stream_cached(media_key)))
        self.assertIsNone(asyncio.run(get_cached_stream(media_key)))

        # Cleanup deletes expired record
        deleted = asyncio.run(cleanup_expired_stream_cache())
        self.assertEqual(deleted, 1)

    def test_02_download_page_and_stream_cache_integration(self):
        """Verify download page and api download response include stream cache metadata."""
        token = "test_perm_token_stream_999"
        media_key = "test_perm_media_key_999"

        async def _seed():
            async with get_db() as db:
                ref = DriveRef(
                    drive_id="stream_drive_file_999",
                    token=token,
                    filename="TestVideo.mp4",
                    file_size=10485760,
                )
                db.add(ref)
                await db.flush()

                perm = PermanentItem(
                    drive_ref_id=ref.id,
                    media_key=media_key,
                    email="test@example.com",
                )
                db.add(perm)
                return ref.id

        ref_id = asyncio.run(_seed())

        # Before cache: has_stream_cache should be false
        res = self.client.get(f"/api/download/{token}")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["is_permanent"])
        self.assertFalse(data["has_stream_cache"])

        # Load download HTML page: watch button is hidden
        page_res = self.client.get(f"/download/{token}")
        self.assertEqual(page_res.status_code, 200)
        self.assertIn("display: none;", page_res.text)

        # Now simulate cache entry set
        asyncio.run(
            set_cached_stream(
                media_key=media_key,
                drive_ref_id=ref_id,
                video_streams=[{"url": "https://example.com/v.mp4", "bandwidth": 1000, "label": "720P"}],
            )
        )

        # After cache: has_stream_cache is True
        res2 = self.client.get(f"/api/download/{token}")
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()
        self.assertTrue(data2["has_stream_cache"])

        # Manifest endpoint serves from cache directly
        man_res = self.client.get(f"/api/download/{token}/manifest")
        self.assertEqual(man_res.status_code, 200)
        man_data = man_res.json()
        self.assertTrue(man_data["success"])
        self.assertEqual(len(man_data["videos"]), 1)
        self.assertEqual(man_data["videos"][0]["label"], "720P")

    def test_03_stream_cache_frontend_pages(self):
        """Verify /stream-cache template loads successfully."""
        res = self.client.get("/stream-cache")
        self.assertEqual(res.status_code, 200)
        self.assertIn("20-Min Stream Cache", res.text)
