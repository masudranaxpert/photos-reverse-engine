import unittest
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(BASE_DIR / "photos_engine") not in sys.path:
    sys.path.insert(0, str(BASE_DIR / "photos_engine"))

from starlette.testclient import TestClient
from app.main import app
from app.services.cache_service import get_cached_url, set_cached_url
import asyncio
import uuid


class TestFastAPIBigSystem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        # Ensure database and admin user are initialized
        from manage import create_admin_user
        asyncio.run(create_admin_user("admin", "secretpassword123"))
        with cls.client:
            res = cls.client.get("/health")
            assert res.status_code == 200

    def test_00_frontend_pages(self):
        """Verify frontend HTML templates render with 200 OK."""
        res_login = self.client.get("/login")
        self.assertEqual(res_login.status_code, 200)
        self.assertIn("Sign In to Engine", res_login.text)

        # Unauthenticated / redirects to /login (303)
        res_home_redirect = self.client.get("/", follow_redirects=False)
        self.assertEqual(res_home_redirect.status_code, 303)
        self.assertEqual(res_home_redirect.headers["location"], "/login")

        # Following redirects arrives at /login
        res_home_followed = self.client.get("/")
        self.assertEqual(res_home_followed.status_code, 200)
        self.assertIn("Sign In to Engine", res_home_followed.text)

    def test_01_health_check(self):
        """Verify health check returns healthy status and SQLite WAL journal mode."""
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["database"]["journal_mode"], "wal")

    def test_02_admin_login(self):
        """Verify admin login with created credentials returns valid JWT token and expiration metadata."""
        res = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "secretpassword123"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["username"], "admin")
        self.assertIn("expires_in", data)
        self.assertIn("expires_at", data)
        self.assertIn("expires_timestamp", data)
        self.assertGreater(data["expires_in"], 0)
        self.__class__.token = data["access_token"]
        self.__class__.headers = {"Authorization": f"Bearer {self.token}"}

    def test_03_auth_me_and_admins(self):
        """Verify authenticated admin profile and admin listing."""
        res = self.client.get("/api/auth/me", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["username"], "admin")

        res_admins = self.client.get("/api/auth/admins", headers=self.headers)
        self.assertEqual(res_admins.status_code, 200)
        self.assertTrue(len(res_admins.json()) >= 1)

    def test_03b_media_list_and_stats(self):
        """Verify media pagination and dashboard stats endpoints."""
        res_stats = self.client.get("/api/media/stats", headers=self.headers)
        self.assertEqual(res_stats.status_code, 200)
        data = res_stats.json()
        self.assertIn("total_media", data)
        self.assertIn("active_web_sessions", data)

        res_media = self.client.get("/api/media?page=1&page_size=10", headers=self.headers)
        self.assertEqual(res_media.status_code, 200)
        media_data = res_media.json()
        self.assertIn("items", media_data)
        self.assertIn("total", media_data)

    def test_04_web_session_crud(self):
        """Verify web cookie sessions listing and status check with invalid/valid cookies."""
        res = self.client.get("/api/web/sessions", headers=self.headers)
        self.assertEqual(res.status_code, 200)

        # Test rejection of bad cookies
        bad_res = self.client.post(
            "/api/web/sessions",
            headers=self.headers,
            json={"name": "Test Session", "cookies": "not_valid_cookies"},
        )
        self.assertEqual(bad_res.status_code, 400)
        self.assertIn("Cookie validation failed", bad_res.json()["detail"])

    def test_05_mobile_account_crud(self):
        """Verify mobile account registration rejects bad AUTH_DATA and lists accounts."""
        res = self.client.get("/api/mobile/accounts", headers=self.headers)
        self.assertEqual(res.status_code, 200)

        # Test rejection of bad auth_data
        bad_auth = self.client.post(
            "/api/mobile/accounts",
            headers=self.headers,
            json={"auth_data": "Token=%zz"},
        )
        self.assertEqual(bad_auth.status_code, 400)

    def test_06_30_min_cache_service(self):
        """Verify 30-minute SQLite WAL download cache stores and retrieves URLs."""
        import uuid
        test_key = f"test_media_key_{uuid.uuid4().hex}"
        test_url = "https://video-downloads.googleusercontent.com/test_token"

        async def run_cache_test():
            # Initial lookup should be None
            cached = await get_cached_url(test_key)
            self.assertIsNone(cached)

            # Store in cache
            await set_cached_url(test_key, test_url, dedup_key="dedup_123", source="web", ttl_seconds=1800)

            # Lookup should now hit
            cached2 = await get_cached_url(test_key)
            self.assertIsNotNone(cached2)
            self.assertEqual(cached2["download_url"], test_url)
            self.assertEqual(cached2["dedup_key"], "dedup_123")

        asyncio.run(run_cache_test())

    def test_07_api_key_system(self):
        """Verify API key creation, multi-method auth (Header, Query, Bearer), toggle, and revocation."""
        # 1. Create API key
        res = self.client.post(
            "/api/keys",
            headers=self.headers,
            json={"name": "Test Runner Key", "expires_days": 14},
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertIn("api_key", data)
        self.assertTrue(data["api_key"].startswith("gpmc_live_"))
        key_id = data["id"]
        raw_key = data["api_key"]

        # 2. List keys
        list_res = self.client.get("/api/keys", headers=self.headers)
        self.assertEqual(list_res.status_code, 200)
        keys = list_res.json()
        self.assertTrue(any(k["id"] == key_id for k in keys))

        # 3. Authenticate via X-API-Key header
        auth_h = self.client.get("/api/media/stats", headers={"X-API-Key": raw_key})
        self.assertEqual(auth_h.status_code, 200)

        # 4. Authenticate via query param
        auth_q = self.client.get(f"/api/media/stats?api_key={raw_key}")
        self.assertEqual(auth_q.status_code, 200)

        # 5. Authenticate via Bearer authorization
        auth_b = self.client.get("/api/media/stats", headers={"Authorization": f"Bearer {raw_key}"})
        self.assertEqual(auth_b.status_code, 200)

        # 6. Toggle key to disabled
        toggle_res = self.client.patch(f"/api/keys/{key_id}/toggle", headers=self.headers)
        self.assertEqual(toggle_res.status_code, 200)
        self.assertFalse(toggle_res.json()["is_active"])

        # 7. Request with disabled key should be rejected
        disabled_res = self.client.get("/api/media/stats", headers={"X-API-Key": raw_key})
        self.assertEqual(disabled_res.status_code, 401)

        # 8. Delete / revoke key
        del_res = self.client.delete(f"/api/keys/{key_id}", headers=self.headers)
        self.assertEqual(del_res.status_code, 200)

        # 9. Request with deleted key should be rejected
        deleted_res = self.client.get("/api/media/stats", headers={"X-API-Key": raw_key})
        self.assertEqual(deleted_res.status_code, 401)

    def test_08_batch_import_and_reset_validation(self):
        """Verify request validation for batch drive import and account reset."""
        # 1. Reset without confirm flag must return 400
        res = self.client.post("/api/web/reset-account", json={"confirm": False}, headers=self.headers)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Confirmation required", res.json()["detail"])

        # 2. Reset with nonexistent session returns 404
        res2 = self.client.post("/api/web/reset-account", json={"confirm": True, "session_id": "nonexistent_sess"}, headers=self.headers)
        self.assertEqual(res2.status_code, 404)

        # 3. Batch import with nonexistent session returns 404
        res3 = self.client.post("/api/web/import-drive/batch", json={"items": ["id1", "id2"], "session_id": "nonexistent_sess"}, headers=self.headers)
        self.assertEqual(res3.status_code, 404)


    def test_09_cached_urls_page_and_api(self):
        """Verify cached URLs HTML page and management API endpoints."""
        # 1. Page renders
        page_res = self.client.get("/cached-urls")
        self.assertEqual(page_res.status_code, 200)
        self.assertIn("30-Min Cached Download URLs", page_res.text)

        # 2. List API requires auth (temporarily clear login cookie to simulate unauthenticated client)
        saved_cookie = self.client.cookies.get("access_token")
        self.client.cookies.clear()
        unauth_res = self.client.get("/api/media/cached-urls")
        self.assertEqual(unauth_res.status_code, 401)
        if saved_cookie:
            self.client.cookies.set("access_token", saved_cookie)

        # 3. List API with auth
        list_res = self.client.get("/api/media/cached-urls?page=1&limit=10", headers=self.headers)
        self.assertEqual(list_res.status_code, 200)
        data = list_res.json()
        self.assertIn("items", data)
        self.assertIn("total", data)
        self.assertIn("totalPages", data)

        # 4. Cleanup expired
        cleanup_res = self.client.post("/api/media/cached-urls/cleanup", headers=self.headers)
        self.assertEqual(cleanup_res.status_code, 200)
        self.assertIn("deleted", cleanup_res.json())

    def test_10_upload_endpoint_schema(self):
        """Verify POST /api/upload has no path parameters and only requires drive_id in body."""
        schema = app.openapi()
        upload_path = schema["paths"]["/api/upload"]["post"]
        self.assertIsNone(upload_path.get("parameters"))
        upload_schema = schema["components"]["schemas"]["UploadRequest"]
        self.assertIn("drive_id", upload_schema["properties"])
        self.assertNotIn("session_id", upload_schema["properties"])
        self.assertNotIn("name", upload_schema["properties"])
        self.assertEqual(upload_schema["required"], ["drive_id"])

        resp_schema = schema["components"]["schemas"]["UploadResponse"]
        self.assertIn("filename", resp_schema["properties"])
        self.assertIn("file_size", resp_schema["properties"])
        self.assertNotIn("media_key", resp_schema["properties"])
        self.assertNotIn("dedup_key", resp_schema["properties"])

    def test_11_system_notices(self):
        """Verify System Notices board endpoints and lifecycle."""
        # 1. Unauthenticated request rejected
        saved_cookie = self.client.cookies.get("access_token")
        self.client.cookies.clear()
        unauth_res = self.client.get("/api/notices")
        self.assertEqual(unauth_res.status_code, 401)
        if saved_cookie:
            self.client.cookies.set("access_token", saved_cookie)

        # 2. Authenticated request returns notices list
        res = self.client.get("/api/notices", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("notices", data)
        self.assertIn("total", data)
        for item in data["notices"]:
            self.assertIn("is_active", item)

        # 3. Dismiss first notice if any exists
        if data["notices"]:
            first_id = data["notices"][0]["id"]
            dismiss_res = self.client.post(f"/api/notices/{first_id}/dismiss", headers=self.headers)
            self.assertEqual(dismiss_res.status_code, 200)
            self.assertTrue(dismiss_res.json()["success"])

    def test_12_audit_log(self):
        """Verify audit log page, paginated endpoint, and the 50-row table cap."""
        from app.services.notice_service import record_notice

        # 2. Paginated endpoint requires auth (temporarily clear cookie)
        saved_cookie = self.client.cookies.get("access_token")
        self.client.cookies.clear()
        unauth_res = self.client.get("/api/notices/paginated")
        self.assertEqual(unauth_res.status_code, 401)
        if saved_cookie:
            self.client.cookies.set("access_token", saved_cookie)

        # 3. Cap: recording 55 rows must prune the table down to the newest 50
        for i in range(55):
            asyncio.run(record_notice(
                title=f"Cap Test {i}", message="cap test row",
                level="info", source=f"cap-test-{i}",
            ))

        res = self.client.get(
            "/api/notices/paginated?page=1&page_size=50&status=all",
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total"], 50)
        self.assertEqual(data["total_pages"], 1)
        self.assertEqual(len(data["notices"]), 50)
        self.assertTrue(all("is_active" in n for n in data["notices"]))
        self.assertEqual(data["notices"][0]["title"], "Cap Test 54")  # newest first

        # 4. Cleanup test rows (pre-existing rows may remain from the prune)
        import sqlite3
        from app.config import DB_PATH
        con = sqlite3.connect(DB_PATH)
        con.execute("DELETE FROM system_notices WHERE source LIKE 'cap-test-%'")
        con.commit()
        con.close()

    def test_14_media_bulk_and_single_delete(self):
        """Verify bulk deletion and single deletion endpoints for temporary and permanent storage."""
        # 1. Clear temp (even when empty or with items)
        res_temp = self.client.post("/api/media/clear-temp", headers=self.headers)
        self.assertEqual(res_temp.status_code, 200)
        self.assertTrue(res_temp.json()["success"])

        # 2. Clear permanent
        res_perm = self.client.post("/api/media/clear-permanent", headers=self.headers)
        self.assertEqual(res_perm.status_code, 200)
        self.assertTrue(res_perm.json()["success"])

        # 3. Single delete non-existent item returns 404
        res_del_404 = self.client.post(
            "/api/media/delete",
            headers=self.headers,
            json={"media_key": "nonexistent_key_12345"},
        )
        self.assertEqual(res_del_404.status_code, 404)

        # 4. Single delete bridge endpoint /api/web/delete
        res_bridge = self.client.post(
            "/api/web/delete",
            headers=self.headers,
            json={"media_key": "nonexistent_key_12345"},
        )
        self.assertEqual(res_bridge.status_code, 404)

    def test_15_native_async_goroutine_callback(self):
        """Verify native Go Goroutine + Python C-ABI callback executes asynchronously."""
        from photos_engine import NativeWebClient, CookieStatus

        async def _run():
            # Check with dummy cookie to trigger Go goroutine dispatch & C callback resolution
            status = await NativeWebClient.check_status_async("OSID=test; SID=test")
            self.assertIsInstance(status, CookieStatus)
            self.assertFalse(status.valid)

        asyncio.run(_run())

    def test_16_docs_and_openapi_auth_filtering(self):
        """Verify unauthenticated OpenAPI schema only exposes /api/upload, while authenticated exposes all."""
        # 1. Unauthenticated request to /openapi.json with a fresh client
        unauth_client = TestClient(app)
        res_unauth = unauth_client.get("/openapi.json")
        self.assertEqual(res_unauth.status_code, 200)
        unauth_paths = list(res_unauth.json()["paths"].keys())
        self.assertEqual(unauth_paths, ["/api/upload"])

        # 2. Authenticated request with Bearer token
        res_auth = unauth_client.get("/openapi.json", headers=self.headers)
        self.assertEqual(res_auth.status_code, 200)
        auth_paths = list(res_auth.json()["paths"].keys())
        self.assertGreater(len(auth_paths), 20)
        self.assertIn("/api/upload", auth_paths)
        self.assertIn("/api/auth/login", auth_paths)

        # 3. Authenticated request with cookie (self.client has cookie from login in test_01)
        res_cookie = self.client.get("/openapi.json")
        self.assertEqual(res_cookie.status_code, 200)
        self.assertEqual(len(res_cookie.json()["paths"]), len(auth_paths))

        # 4. /docs and /redoc pages return 200
        docs_res = unauth_client.get("/docs")
        self.assertEqual(docs_res.status_code, 200)
        redoc_res = unauth_client.get("/redoc")
        self.assertEqual(redoc_res.status_code, 200)


    def test_17_streaming_manifest_endpoint_and_download_page(self):
        """Verify DASH streaming manifest endpoints and conditional Watch Video button on download page."""
        import uuid
        from unittest.mock import AsyncMock, patch
        from app.database import get_db
        from app.models import DriveRef, PermanentItem, TempImport

        # 1. Non-existent token -> 404
        bad_res = self.client.get("/api/download/non_existent_token_123/manifest")
        self.assertEqual(bad_res.status_code, 404)

        # 2. Setup temp-only item and permanent item in DB
        temp_token = f"temp_{uuid.uuid4().hex[:16]}"
        perm_token = f"perm_{uuid.uuid4().hex[:16]}"
        temp_media_key = f"AF1QipTemp_{uuid.uuid4().hex[:12]}"
        perm_media_key = f"AF1QipPerm_{uuid.uuid4().hex[:12]}"
        dummy_mpd = '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><Period></Period></MPD>'

        async def _setup_data():
            async with get_db() as db:
                # Temp item
                dref_temp = DriveRef(drive_id=f"drive_temp_{uuid.uuid4().hex[:8]}", token=temp_token, filename="video1.mp4")
                db.add(dref_temp)
                await db.flush()
                temp_item = TempImport(drive_ref_id=dref_temp.id, media_key=temp_media_key)
                db.add(temp_item)

                # Permanent item
                dref_perm = DriveRef(drive_id=f"drive_perm_{uuid.uuid4().hex[:8]}", token=perm_token, filename="video2.mp4")
                db.add(dref_perm)
                await db.flush()
                perm_item = PermanentItem(drive_ref_id=dref_perm.id, media_key=perm_media_key, email="test@example.com")
                db.add(perm_item)

        asyncio.run(_setup_data())

        # 3. Temp item: /manifest endpoint returns 400
        temp_manifest_res = self.client.get(f"/api/download/{temp_token}/manifest")
        self.assertEqual(temp_manifest_res.status_code, 400)
        self.assertIn("Streaming is only available", temp_manifest_res.json()["detail"])

        # 4. Download page for temp item should NOT contain Watch Video button
        temp_page = self.client.get(f"/download/{temp_token}")
        self.assertEqual(temp_page.status_code, 200)
        self.assertNotIn('id="watchBtn"', temp_page.text)

        # 5. Permanent item: mock mobile client and verify manifest endpoints
        mock_client = AsyncMock()
        mock_client.get_token_async.return_value = "fake_token_123"
        mock_client.get_stream_manifest_async.return_value = dummy_mpd
        mock_client.get_download_url_async.return_value = AsyncMock(download_url="https://googleusercontent.com/test", dedup_key=None)

        with patch("app.services.mobile_service.get_mobile_client", new_callable=AsyncMock) as mock_get_client, \
             patch("app.services.streaming_service.fetch_manifest_via_proxy", new_callable=AsyncMock) as mock_proxy:
            mock_get_client.return_value = (mock_client, None)
            mock_proxy.return_value = dummy_mpd

            # JSON manifest endpoint
            perm_manifest_res = self.client.get(f"/api/download/{perm_token}/manifest")
            self.assertEqual(perm_manifest_res.status_code, 200)
            data = perm_manifest_res.json()
            self.assertTrue(data["success"])
            self.assertIn("videos", data)
            self.assertNotIn("media_key", data)  # Security: must not leak Google Photos media_key

            # Raw .mpd endpoint
            mpd_res = self.client.get(f"/api/download/{perm_token}/manifest.mpd")
            self.assertEqual(mpd_res.status_code, 200)
            self.assertIn("application/dash+xml", mpd_res.headers.get("content-type", ""))
            self.assertEqual(mpd_res.text, dummy_mpd)

            # Download page for permanent item MUST contain Watch Video button linking to /player/{perm_token}
            perm_page = self.client.get(f"/download/{perm_token}")
            self.assertEqual(perm_page.status_code, 200)
            self.assertIn('id="watchBtn"', perm_page.text)
            self.assertIn(f"/player/{perm_token}", perm_page.text)

            # Dedicated full-browser and iframe player pages
            player_res = self.client.get(f"/player/{perm_token}")
            self.assertEqual(player_res.status_code, 200)
            self.assertIn("artplayer", player_res.text)

            embed_res = self.client.get(f"/embed/{perm_token}")
            self.assertEqual(embed_res.status_code, 200)
            self.assertIn("artplayer", embed_res.text)

    def test_18_visitor_count_and_public_privacy(self):
        from app.database import get_db
        from app.models import DriveRef, PermanentItem
        from sqlalchemy import select

        token = "vtest_" + uuid.uuid4().hex[:16]
        d_id = "vtest_drive_" + uuid.uuid4().hex[:12]

        async def _seed():
            async with get_db() as db:
                ref = DriveRef(
                    drive_id=d_id,
                    token=token,
                    filename="secret_movie.mp4",
                    file_size=1024,
                    file_status="ok",
                    visitor_count=0,
                )
                db.add(ref)
                await db.flush()
                perm = PermanentItem(
                    drive_ref_id=ref.id,
                    media_key="AF1QipSecretKey_" + uuid.uuid4().hex[:8],
                    email="admin@photos.com",
                )
                db.add(perm)
                await db.commit()

        asyncio.run(_seed())

        # 1. Public JSON status: must NOT leak drive_id or share_url
        res = self.client.get(f"/api/download/{token}")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertNotIn("drive_id", data)
        self.assertNotIn("share_url", data)

        # 2. First visit to download page: increments visitor_count from 0 to 1 and sets cookie
        client2 = TestClient(app)
        page1 = client2.get(f"/download/{token}")
        self.assertEqual(page1.status_code, 200)
        self.assertIn(f"viewed_{token}", page1.cookies)

        # Verify DB visitor_count is 1
        async def _get_count():
            async with get_db() as db:
                r = await db.execute(select(DriveRef.visitor_count).where(DriveRef.token == token))
                return r.scalar()

        self.assertEqual(asyncio.run(_get_count()), 1)

        # 3. Subsequent visits (refresh/F5 spam) with cookie: count stays 1
        page2 = client2.get(f"/download/{token}")
        self.assertEqual(page2.status_code, 200)
        self.assertEqual(asyncio.run(_get_count()), 1)

        # 4. Admin media list: admin CAN see visitor_count
        headers = getattr(self, "headers", None)
        if not headers:
            login_res = self.client.post("/api/auth/login", json={"username": "admin", "password": "secretpassword123"})
            headers = {"Authorization": f"Bearer {login_res.json()['access_token']}"}

        media_res = self.client.get("/api/media?search=" + token, headers=headers)
        self.assertEqual(media_res.status_code, 200)
        m_data = media_res.json()
        self.assertEqual(len(m_data["items"]), 1)
        self.assertEqual(m_data["items"][0]["visitor_count"], 1)


if __name__ == "__main__":
    unittest.main()



