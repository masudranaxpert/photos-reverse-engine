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


if __name__ == "__main__":
    unittest.main()
