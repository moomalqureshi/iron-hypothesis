import base64
import hashlib
import hmac
import os

from cryptography.fernet import Fernet

from ironman.config import get_settings


def _fernet() -> Fernet:
    key = get_settings().token_enc_key
    if not key:
        # Derive a stable key from the secret so local dev works; production sets token_enc_key.
        key = base64.urlsafe_b64encode(
            hashlib.sha256(get_settings().secret_key.encode()).digest()
        ).decode()
    return Fernet(key)


def encrypt(s: str) -> str:
    return _fernet().encrypt(s.encode()).decode()


def decrypt(s: str) -> str:
    return _fernet().decrypt(s.encode()).decode()


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1)
    return base64.b64encode(salt + dk).decode()


def verify_password(pw: str, stored: str) -> bool:
    raw = base64.b64decode(stored)
    salt, dk = raw[:16], raw[16:]
    return hmac.compare_digest(hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1), dk)


def pseudonym(internal_id: str) -> str:
    key = get_settings().pseudonym_key.encode()
    return "ath_" + hmac.new(key, internal_id.encode(), hashlib.sha256).hexdigest()[:12]
