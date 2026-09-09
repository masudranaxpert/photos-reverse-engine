"""
Unit tests for cookie parsing, stores (file & database), session manager, and web client.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from photos_engine.cookies import (
    DatabaseCookieStore,
    FileCookieStore,
    SessionManager,
    build_cookie_header,
    format_netscape_cookies,
    parse_cookie_source,
    parse_json_cookies,
    parse_netscape_cookies,
)
from photos_engine.models import CookieStatus, DownloadInfo, DriveImportResult
from photos_engine.web_client import GooglePhotosWebClient, _parse_batchexecute_body, _safe_get

SAMPLE_NETSCAPE = """# Netscape HTTP Cookie File
.google.com\tTRUE\t/\tTRUE\t1893456000\tSID\tsid_sample_value
#HttpOnly_.google.com\tTRUE\t/\tTRUE\t1893456000\t__Secure-1PSID\tpsid_sample_value
#HttpOnly_.google.com\tTRUE\t/\tTRUE\t1893456000\t__Secure-1PSIDTS\tsidts_sample_value
.google.com\tTRUE\t/\tTRUE\t1893456000\tOSID\tosid_sample_value
"""

SAMPLE_JSON = json.dumps([
    {"name": "SID", "value": "sid_json_val", "domain": ".google.com"},
    {"name": "__Secure-1PSID", "value": "psid_json_val", "domain": ".google.com"},
    {"name": "__Secure-1PSIDTS", "value": "sidts_json_val", "domain": ".google.com"},
    {"name": "OSID", "value": "osid_json_val", "domain": ".google.com"},
])


class TestCookieParsing(unittest.TestCase):
    def test_parse_netscape(self):
        cookies = parse_netscape_cookies(SAMPLE_NETSCAPE)
        self.assertEqual(len(cookies), 4)
        names = {c["name"]: c["value"] for c in cookies}
        self.assertEqual(names["SID"], "sid_sample_value")
        self.assertEqual(names["__Secure-1PSID"], "psid_sample_value")
        self.assertEqual(names["__Secure-1PSIDTS"], "sidts_sample_value")
        self.assertEqual(names["OSID"], "osid_sample_value")

    def test_parse_json(self):
        cookies = parse_json_cookies(SAMPLE_JSON)
        self.assertEqual(len(cookies), 4)
        names = {c["name"]: c["value"] for c in cookies}
        self.assertEqual(names["SID"], "sid_json_val")
        self.assertEqual(names["OSID"], "osid_json_val")

    def test_parse_cookie_source_validation(self):
        cookies, missing = parse_cookie_source(SAMPLE_NETSCAPE)
        self.assertEqual(missing, [])
        self.assertEqual(len(cookies), 4)

        # Incomplete cookies
        partial = ".google.com\tTRUE\t/\tTRUE\t0\tSID\t123"
        cookies, missing = parse_cookie_source(partial)
        self.assertIn("__Secure-1PSID", missing)
        self.assertIn("__Secure-1PSIDTS", missing)

    def test_format_and_header(self):
        cookies = parse_netscape_cookies(SAMPLE_NETSCAPE)
        header = build_cookie_header(cookies)
        self.assertIn("SID=sid_sample_value", header)
        self.assertIn("OSID=osid_sample_value", header)

        netscape_text = format_netscape_cookies(cookies)
        self.assertIn("# Netscape HTTP Cookie File", netscape_text)
        self.assertIn("sid_sample_value", netscape_text)


class TestFileCookieStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cookie_file = Path(self.temp_dir) / "test_cookies.txt"
        self.cookie_file.write_text(SAMPLE_NETSCAPE, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_and_save(self):
        store = FileCookieStore(self.cookie_file)
        cookies = store.load_cookies("default")
        self.assertEqual(len(cookies), 4)

        # Save session blob
        test_blob = "marshaled_test_blob_data_123"
        store.save_session_blob("default", test_blob)
        loaded_blob = store.load_session_blob("default")
        self.assertEqual(loaded_blob, test_blob)


class TestDatabaseCookieStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_sessions.db"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_custom_columns_and_persistence(self):
        store = DatabaseCookieStore(
            db_source=self.db_path,
            table_name="my_custom_cookies",
            session_id_col="sess_id",
            blob_col="blob_data",
            is_active_col="active_flag",
            account_col="user_email",
            is_valid_col="status_ok",
            updated_at_col="last_seen",
        )

        test_blob = "db_marshaled_blob_data_xyz"
        store.save_session_blob("session_1", test_blob, account="test@gmail.com", is_valid=True)

        loaded = store.load_session_blob("session_1")
        self.assertEqual(loaded, test_blob)

        # Verify update
        store.save_session_blob("session_1", "updated_blob_abc", account="test@gmail.com", is_valid=True)
        self.assertEqual(store.load_session_blob("session_1"), "updated_blob_abc")

        store.close()


class TestSessionManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cookie_file = Path(self.temp_dir) / "cookies.txt"
        self.cookie_file.write_text(SAMPLE_NETSCAPE, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_session_lifecycle_and_reuse(self):
        store = FileCookieStore(self.cookie_file)
        manager = SessionManager(store=store, sync_interval_seconds=1.0)

        session1 = manager.get_session("default")
        self.assertIsNotNone(session1)

        # Verify session is cached in memory
        session2 = manager.get_session("default")
        self.assertIs(session1, session2)

        # Debounced sync
        manager.debounced_sync("default", session1, force=True)
        self.assertIsNotNone(store.load_session_blob("default"))

        manager.close()


class TestBatchexecuteHelpers(unittest.TestCase):
    def test_safe_get(self):
        data = [[["media123", "dedup456"]], 1]
        self.assertEqual(_safe_get(data, 0, 0, 0), "media123")
        self.assertEqual(_safe_get(data, 0, 0, 1), "dedup456")
        self.assertIsNone(_safe_get(data, 0, 99))
        self.assertIsNone(_safe_get(None, 0))

    def test_parse_batchexecute_body(self):
        body = ')]}\'\n[["wrb.fr","SusGud","[[[\\"drive1\\",[\\"media1\\",null,null,\\"dedup1\\"]]]]",null,null,null,"generic"]]'
        parsed = _parse_batchexecute_body(body, "SusGud")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[0][0][0], "drive1")
        self.assertEqual(parsed[0][0][1][0], "media1")
        self.assertEqual(parsed[0][0][1][3], "dedup1")


class TestNativeWebClient(unittest.TestCase):
    def test_native_cgo_check_status(self):
        from photos_engine import NativeWebClient
        status = NativeWebClient.check_status(SAMPLE_NETSCAPE)
        self.assertIsNotNone(status)
        self.assertIsInstance(status.valid, bool)


if __name__ == "__main__":
    unittest.main()
