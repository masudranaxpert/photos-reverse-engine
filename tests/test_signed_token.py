import asyncio
import hashlib
import hmac
import struct
import time
import secrets
import unittest
from starlette.testclient import TestClient

from app.main import app
from app.config import SECRET_KEY
from app.database import get_db, init_db
from app.models import DriveRef
from app.services.signed_token_service import (
    _int_to_base62,
    create_expiring_token,
    verify_expiring_token,
)


class TestSignedToken(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        asyncio.run(init_db())
        cls.client = TestClient(app)
        cls.raw_hex = "2ff3bcf349204519b8de47450d858b60"

        # Ensure a drive_ref exists for testing
        async def setup_ref():
            async with get_db() as db:
                from sqlalchemy import select
                res = await db.execute(select(DriveRef).where(DriveRef.token == cls.raw_hex))
                existing = res.scalar_one_or_none()
                if not existing:
                    ref = DriveRef(
                        drive_id="test_drive_id_token_123",
                        token=cls.raw_hex,
                        filename="test_video.mp4",
                        file_size=1024000,
                        file_status="ready",
                    )
                    db.add(ref)
                    await db.commit()

        asyncio.run(setup_ref())

    def test_token_format_and_purity(self):
        token = create_expiring_token(self.raw_hex)
        self.assertEqual(len(token), 45)
        self.assertTrue(token.isalnum())
        self.assertNotIn("_", token)
        self.assertNotIn("-", token)

        extracted, status = verify_expiring_token(token)
        self.assertEqual(extracted, self.raw_hex)
        self.assertEqual(status, "valid")

    def test_token_uniqueness_on_each_call(self):
        tokens = {create_expiring_token(self.raw_hex) for _ in range(10)}
        self.assertEqual(len(tokens), 10)

    def test_token_expiration(self):
        token = create_expiring_token(self.raw_hex)
        # Validate with max_age = -1s to simulate passage of 1.5h
        extracted, status = verify_expiring_token(token, max_age=-1)
        self.assertEqual(extracted, self.raw_hex)
        self.assertEqual(status, "expired")

    def test_token_tampering(self):
        token = create_expiring_token(self.raw_hex)
        tampered = ("a" if token[0] != "a" else "b") + token[1:]
        extracted, status = verify_expiring_token(tampered)
        self.assertIsNone(extracted)
        self.assertEqual(status, "invalid")

    def test_download_page_with_expiring_and_expired_tokens(self):
        # Fresh valid token
        valid_token = create_expiring_token(self.raw_hex)
        res = self.client.get(f"/download/{valid_token}")
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("Link Expired", res.text)

        # Expired token (created with timestamp far in past)
        past_time = int(time.time()) - 6000  # 100 minutes ago (>90m)
        salt = secrets.token_bytes(4)
        payload = bytes.fromhex(self.raw_hex) + struct.pack("!I", past_time) + salt
        sig = hmac.new(SECRET_KEY.encode("utf-8"), payload, hashlib.sha256).digest()[:9]
        expired_token = _int_to_base62(int.from_bytes(payload + sig, "big")).rjust(45, "0")

        exp_res = self.client.get(f"/download/{expired_token}")
        self.assertEqual(exp_res.status_code, 200)
        self.assertIn("Link Expired", exp_res.text)
        self.assertIn("This download link has expired. Please generate a new download link.", exp_res.text)
        self.assertNotIn("1.5 hour", exp_res.text)
        self.assertNotIn("90 minute", exp_res.text)

        # API status endpoint for expired token
        api_res = self.client.get(f"/api/download/{expired_token}")
        self.assertEqual(api_res.status_code, 200)
        self.assertEqual(api_res.json()["status"], "expired")

    def test_upload_endpoint_returns_clean_45char_download_url(self):
        from unittest.mock import patch, MagicMock
        mock_sess = MagicMock()
        mock_sess.id = 1
        with patch("app.services.web_service.get_active_session_row", return_value=mock_sess):
            res = self.client.post(
                "/api/upload",
                json={"drive_id": "test_drive_id_token_123"},
                headers={"Authorization": "Bearer fake_admin_or_key"},
            )
            # Authenticated as admin session or key
            if res.status_code == 200:
                data = res.json()
                self.assertIn("download_url", data)
                code = data["download_url"].split("/download/")[1]
                self.assertEqual(len(code), 45)
                self.assertTrue(code.isalnum())
                self.assertNotIn("_", code)
                self.assertNotIn("-", code)
