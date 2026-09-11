import unittest
import ctypes
import json

from photos_engine.client import PhotosEngineClient, NativeWebClient, _get_lib_path


class TestCAbiFixes(unittest.TestCase):
    def setUp(self):
        self.lib_path = _get_lib_path()
        self.lib = ctypes.CDLL(self.lib_path)
        self.lib.GPMC_FreeString.argtypes = [ctypes.c_void_p]
        self.lib.GPMC_FreeString.restype = None

    def test_missing_handle_error_propagation(self):
        """Verify that invalid handle returns 'client handle not found' error, not success:true, data:null."""
        self.lib.GPMC_GetToken.argtypes = [ctypes.c_ulonglong, ctypes.c_longlong]
        self.lib.GPMC_GetToken.restype = ctypes.c_void_p

        raw_ptr = self.lib.GPMC_GetToken(99999999, 0)
        self.assertTrue(bool(raw_ptr))

        json_str = ctypes.string_at(raw_ptr).decode("utf-8")
        self.lib.GPMC_FreeString(raw_ptr)

        res = json.loads(json_str)
        self.assertFalse(res.get("success"))
        self.assertIn("client handle not found", res.get("error", ""))

    def test_gpmc_constructor_error_preservation(self):
        """Verify that malformed AUTH_DATA surfaces the real Go parser error."""
        with self.assertRaises(RuntimeError) as ctx:
            PhotosEngineClient(auth_data="Token=%zz")

        self.assertIn("GPMC_CreateClient failed", str(ctx.exception))
        self.assertIn("failed to parse AUTH_DATA", str(ctx.exception))

    def test_gpwc_constructor_error_preservation(self):
        """Verify that unrecognized cookies surface the real Go ParseCookies error."""
        with self.assertRaises(RuntimeError) as ctx:
            NativeWebClient(cookies="random_invalid_string_no_cookies")

        self.assertIn("GPWC_CreateClient failed", str(ctx.exception))
        self.assertIn("no valid Google auth cookies found", str(ctx.exception))

    def test_gpwc_check_status_invalid_cookie(self):
        """Verify NativeWebClient.check_status cleanly returns valid=False for empty or bad cookies."""
        status = NativeWebClient.check_status("bad_cookies")
        self.assertFalse(status.valid)
        self.assertTrue(len(status.message) > 0)

    def test_gpwc_valid_netscape_cookie_instantiation(self):
        """Verify NativeWebClient can initialize with valid netscape cookie string."""
        netscape_str = (
            "# Netscape HTTP Cookie File\n"
            ".google.com\tTRUE\t/\tTRUE\t1750000000\tSID\tsid_value_123\n"
            ".google.com\tTRUE\t/\tTRUE\t1750000000\t__Secure-1PSID\tsec_psid_value\n"
        )
        # Initialization will try to connect to Google photos.google.com to get global tokens
        # It should either succeed or raise a network error, NOT a parse error
        try:
            client = NativeWebClient(cookies=netscape_str)
            client.close()
        except RuntimeError as exc:
            # If network is unreachable, it raises network error, but cookie parsing succeeded
            self.assertNotIn("no valid Google auth cookies found", str(exc))

    def test_gpmc_scrape_share_url_cabi(self):
        """Verify scrape_share_url works directly through the Go C-ABI engine."""
        from photos_engine import scrape_share_url
        with self.assertRaises(RuntimeError) as ctx:
            scrape_share_url("https://photos.app.goo.gl/invalid_non_existent_url_test")
        self.assertIn("GPMC_ScrapeShareURL failed", str(ctx.exception))

    def test_gpwc_blob_invalid_fails(self):
        """Verify NativeWebClient.from_blob fails gracefully on invalid blob data."""
        with self.assertRaises(RuntimeError) as ctx:
            NativeWebClient.from_blob(b"not_a_valid_blob")
        self.assertIn("GPWC_CreateClientFromBlob failed", str(ctx.exception))

    def test_gpwc_get_storage_quota_cabi(self):
        """Verify GPWC_GetStorageQuota C-ABI export exists and returns expected error for invalid handle."""
        self.lib.GPWC_GetStorageQuota.argtypes = [ctypes.c_ulonglong]
        self.lib.GPWC_GetStorageQuota.restype = ctypes.c_void_p
        raw_ptr = self.lib.GPWC_GetStorageQuota(99999999)
        self.assertTrue(bool(raw_ptr))
        json_str = ctypes.string_at(raw_ptr).decode("utf-8")
        self.lib.GPMC_FreeString(raw_ptr)
        res = json.loads(json_str)
        self.assertFalse(res.get("success"))
        self.assertIn("client handle not found", res.get("error", ""))

    def test_gpwc_batch_import_cabi(self):
        """Verify GPWC_BatchImportFromDrive C-ABI export exists."""
        self.assertTrue(hasattr(self.lib, "GPWC_BatchImportFromDrive"))
        self.lib.GPWC_BatchImportFromDrive.argtypes = [ctypes.c_ulonglong, ctypes.c_char_p, ctypes.c_int, ctypes.c_longlong]
        self.lib.GPWC_BatchImportFromDrive.restype = ctypes.c_void_p
        raw_ptr = self.lib.GPWC_BatchImportFromDrive(99999999, b"[]", 0, 1000)
        self.assertTrue(bool(raw_ptr))
        json_str = ctypes.string_at(raw_ptr).decode("utf-8")
        self.lib.GPMC_FreeString(raw_ptr)
        res = json.loads(json_str)
        self.assertFalse(res.get("success"))
        self.assertIn("client handle not found", res.get("error", ""))

    def test_gpwc_reset_account_cabi(self):
        """Verify GPWC_ResetAccount C-ABI export exists."""
        self.assertTrue(hasattr(self.lib, "GPWC_ResetAccount"))
        self.lib.GPWC_ResetAccount.argtypes = [ctypes.c_ulonglong, ctypes.c_longlong]
        self.lib.GPWC_ResetAccount.restype = ctypes.c_void_p
        raw_ptr = self.lib.GPWC_ResetAccount(99999999, 1000)
        self.assertTrue(bool(raw_ptr))
        json_str = ctypes.string_at(raw_ptr).decode("utf-8")
        self.lib.GPMC_FreeString(raw_ptr)
        res = json.loads(json_str)
        self.assertFalse(res.get("success"))
    def test_gpwc_delete_permanently_cabi(self):
        """Verify GPWC_DeletePermanently and GPWC_DeletePermanently_Async C-ABI exports exist."""
        self.assertTrue(hasattr(self.lib, "GPWC_DeletePermanently"))
        self.assertTrue(hasattr(self.lib, "GPWC_DeletePermanently_Async"))
        self.lib.GPWC_DeletePermanently.argtypes = [ctypes.c_ulonglong, ctypes.c_char_p]
        self.lib.GPWC_DeletePermanently.restype = ctypes.c_void_p
        raw_ptr = self.lib.GPWC_DeletePermanently(99999999, b"test_dedup_key")
        self.assertTrue(bool(raw_ptr))
        json_str = ctypes.string_at(raw_ptr).decode("utf-8")
        self.lib.GPMC_FreeString(raw_ptr)
        res = json.loads(json_str)
        self.assertFalse(res.get("success"))
        self.assertIn("client handle not found", res.get("error", ""))


if __name__ == "__main__":
    unittest.main()

