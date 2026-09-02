"""Veyra Password Hashing & Security Utilities (Checklist Items 9, 10).

Provides:
1. PBKDF2-HMAC-SHA256 with 600,000 iterations & salt (OWASP Recommended standard).
2. Constant-time comparison preventing timing attacks.
3. Cryptographically strong session & API key token generators.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from typing import Tuple

PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256 with a unique 16-byte random salt."""
    if not password:
        raise ValueError("Password cannot be empty")
    
    salt = secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    salt_b64 = base64.b64encode(salt).decode("utf-8")
    key_b64 = base64.b64encode(key).decode("utf-8")
    return f"pbkdf2:sha256:{PBKDF2_ITERATIONS}${salt_b64}${key_b64}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a stored hashed password in constant time."""
    if not plain_password or not hashed_password:
        return False
    
    try:
        scheme, algo, params = hashed_password.split(":")
        iter_str, salt_b64, key_b64 = params.split("$")
        iterations = int(iter_str)
        salt = base64.b64decode(salt_b64.encode("utf-8"))
        expected_key = base64.b64decode(key_b64.encode("utf-8"))
        
        computed_key = hashlib.pbkdf2_hmac(algo, plain_password.encode("utf-8"), salt, iterations)
        return secrets.compare_digest(computed_key, expected_key)
    except Exception:
        return False


def generate_api_key(prefix: str = "vy_live") -> Tuple[str, str]:
    """Generate a live API key and its secure SHA-256 storage hash.
    
    Returns (raw_key, key_hash). Raw key is only shown once to user.
    """
    raw_token = secrets.token_urlsafe(32)
    raw_key = f"{prefix}_{raw_token}"
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return raw_key, key_hash


def generate_session_token() -> str:
    """Generate a high-entropy 256-bit session token."""
    return secrets.token_urlsafe(32)
