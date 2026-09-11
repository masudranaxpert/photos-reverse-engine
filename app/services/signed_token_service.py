"""
Signed token service for time-limited, alphanumeric expiring download URLs.
Uses HMAC-SHA256 and Base62 encoding (0-9, a-z, A-Z) to generate secure,
tamper-proof 45-character strings with built-in expiration and unique salt.
"""
import hashlib
import hmac
import secrets
import struct
import time

from app.config import SECRET_KEY

BASE62_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
TOKEN_TTL_SECONDS = 5400  # 1.5 hours (90 minutes)


def _int_to_base62(num: int) -> str:
    """Encode an integer to a Base62 alphanumeric string."""
    if num == 0:
        return BASE62_ALPHABET[0]
    res = []
    base = len(BASE62_ALPHABET)
    while num > 0:
        num, rem = divmod(num, base)
        res.append(BASE62_ALPHABET[rem])
    return "".join(reversed(res))


def _base62_to_int(s: str) -> int:
    """Decode a Base62 alphanumeric string back to an integer."""
    base = len(BASE62_ALPHABET)
    num = 0
    for char in s:
        idx = BASE62_ALPHABET.find(char)
        if idx == -1:
            raise ValueError(f"Invalid Base62 character: {char}")
        num = num * base + idx
    return num


def create_expiring_token(raw_hex_token: str, ttl_seconds: int = TOKEN_TTL_SECONDS) -> str:
    """
    Generate an exact 45-character URL-safe alphanumeric string containing the raw hex token,
    creation timestamp, random salt, and HMAC-SHA256 signature.
    """
    token_bytes = bytes.fromhex(raw_hex_token)
    now = int(time.time())
    salt = secrets.token_bytes(4)
    payload = token_bytes + struct.pack("!I", now) + salt  # 16 + 4 + 4 = 24 bytes
    sig = hmac.new(SECRET_KEY.encode("utf-8"), payload, hashlib.sha256).digest()[:9]  # 9 bytes HMAC -> total 33 bytes
    data = payload + sig
    num = int.from_bytes(data, "big")
    b62 = _int_to_base62(num)
    return b62.rjust(45, "0")


def verify_expiring_token(token_str: str, max_age: int = TOKEN_TTL_SECONDS) -> tuple[str | None, str]:
    """
    Verify an expiring Base62 token.

    Returns:
        tuple (hex_token, status) where status is:
        - 'valid': Signature and age are valid
        - 'expired': Signature is valid, but elapsed time > max_age
        - 'invalid': Corrupted, tampered, or invalid format
    """
    try:
        if len(token_str) != 45:
            return None, "invalid"
        num = _base62_to_int(token_str)
        data = num.to_bytes(33, "big")
        payload = data[:24]
        sig = data[24:]
        expected_sig = hmac.new(SECRET_KEY.encode("utf-8"), payload, hashlib.sha256).digest()[:9]
        if not hmac.compare_digest(sig, expected_sig):
            return None, "invalid"
        token_bytes = payload[:16]
        timestamp = struct.unpack("!I", payload[16:20])[0]
        now = int(time.time())
        hex_token = token_bytes.hex()
        if now - timestamp > max_age or timestamp > now + 60:
            return hex_token, "expired"
        return hex_token, "valid"
    except Exception:
        return None, "invalid"
