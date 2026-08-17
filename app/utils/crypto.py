"""
Token encryption/decryption using Fernet symmetric encryption.
Protects OAuth refresh tokens at rest in the database.
"""
import json
import os
import base64
from typing import Optional, Any

try:
    from cryptography.fernet import Fernet, InvalidToken
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


def _get_fernet(key: str) -> Optional[Any]:
    """Get a Fernet instance from the encryption key."""
    if not CRYPTO_AVAILABLE or not key:
        return None
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        return None


def generate_encryption_key() -> str:
    """Generate a new Fernet encryption key. Run once and store in .env."""
    if not CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography package not installed")
    return Fernet.generate_key().decode()


def encrypt_json(data: dict, key: str) -> Optional[str]:
    """Encrypt a dict as JSON string. Returns base64-encoded ciphertext or None."""
    fernet = _get_fernet(key)
    if not fernet:
        # Fall back to plain JSON if encryption not configured (dev mode)
        return json.dumps(data)
    try:
        plaintext = json.dumps(data).encode()
        return fernet.encrypt(plaintext).decode()
    except Exception:
        return None


def decrypt_json(ciphertext: str, key: str) -> Optional[dict]:
    """Decrypt an encrypted JSON string. Returns dict or None."""
    if not ciphertext:
        return None

    fernet = _get_fernet(key)
    if not fernet:
        # Try parsing as plain JSON (dev mode fallback)
        try:
            return json.loads(ciphertext)
        except Exception:
            return None
    try:
        plaintext = fernet.decrypt(ciphertext.encode())
        return json.loads(plaintext)
    except (InvalidToken, Exception):
        # Try plain JSON as fallback (in case key changed)
        try:
            return json.loads(ciphertext)
        except Exception:
            return None
