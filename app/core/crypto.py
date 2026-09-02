"""Veyra Cryptographic Subsystem (Checklist Items 5, 8).

Provides:
1. AES-GCM 256-bit authenticated encryption with random IVs for sensitive customer PII.
2. HMAC-SHA256 blind indexing and deterministic instrument tokenization.
3. Cryptographically secure constant-time comparisons.

Pepper resolution (``_effective_pepper``) has no production fallback in code. A prior
version of this module defaulted a missing ``VEYRA_CRYPTO_PEPPER`` to a string literal
committed to source — meaning "encrypted" PII was recoverable by anyone who could read
the repository if an operator forgot to set the environment variable. `Settings`
(app/core/config.py) now refuses to construct a `production` settings object without
`crypto_pepper` set, so the production branch below is defense-in-depth rather than the
only guard. Outside production, an explicit, clearly-labelled constant keeps a laptop
run or the test suite working without any configuration.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Final

from app.core.config import settings

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

_INSECURE_DEV_ONLY_PEPPER: Final[str] = "veyra-insecure-dev-only-pepper-never-use-in-production"
"""Used only outside `production`, and only when no explicit key/pepper was supplied.
Not a secret — it is committed to source deliberately, so nothing built with it should
ever be treated as confidential."""


def _effective_pepper(key_str: str | None) -> str:
    """Resolve the pepper for a single crypto operation. Fails closed in production."""
    if key_str:
        return key_str
    if settings.crypto_pepper:
        return settings.crypto_pepper
    if settings.environment == "production":
        # Defense-in-depth: Settings._production_fails_closed already prevents a
        # production process from reaching this line without crypto_pepper set.
        raise RuntimeError(
            "VEYRA_CRYPTO_PEPPER is required in production and was not configured."
        )
    return _INSECURE_DEV_ONLY_PEPPER


def generate_master_key() -> str:
    """Generate a 256-bit random base64-encoded master key."""
    return base64.b64encode(secrets.token_bytes(32)).decode("utf-8")


def derive_key(secret_str: str) -> bytes:
    """Derive a deterministic 32-byte key from a secret string."""
    return hashlib.sha256(secret_str.encode("utf-8")).digest()


def encrypt_sensitive_field(plaintext: str, key_str: str | None = None) -> str:
    """Encrypt sensitive plaintext using AES-256-GCM authenticated encryption.
    
    Returns base64 string formatted as: iv (12 bytes) + ciphertext + tag (16 bytes).
    """
    if not plaintext:
        return ""
    
    key = derive_key(_effective_pepper(key_str))
    if HAS_CRYPTOGRAPHY:
        aesgcm = AESGCM(key)
        iv = secrets.token_bytes(12)
        ciphertext = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
        return base64.b64encode(iv + ciphertext).decode("utf-8")
    else:
        # Fallback authenticated XOR-HMAC cipher if cryptography lib is absent
        iv = secrets.token_bytes(16)
        stream_key = hashlib.sha256(key + iv).digest()
        plain_bytes = plaintext.encode("utf-8")
        encrypted = bytes(b ^ stream_key[i % len(stream_key)] for i, b in enumerate(plain_bytes))
        tag = hmac.new(key, iv + encrypted, hashlib.sha256).digest()[:16]
        return base64.b64encode(iv + tag + encrypted).decode("utf-8")


def decrypt_sensitive_field(encrypted_b64: str, key_str: str | None = None) -> str:
    """Decrypt an AES-256-GCM encrypted base64 payload."""
    if not encrypted_b64:
        return ""
    
    key = derive_key(_effective_pepper(key_str))
    raw = base64.b64decode(encrypted_b64.encode("utf-8"))
    
    if HAS_CRYPTOGRAPHY:
        if len(raw) < 28:
            raise ValueError("Invalid encrypted payload size")
        iv = raw[:12]
        ciphertext = raw[12:]
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(iv, ciphertext, None)
        return plaintext.decode("utf-8")
    else:
        if len(raw) < 32:
            raise ValueError("Invalid encrypted payload size")
        iv = raw[:16]
        tag = raw[16:32]
        encrypted = raw[32:]
        computed_tag = hmac.new(key, iv + encrypted, hashlib.sha256).digest()[:16]
        if not secrets.compare_digest(tag, computed_tag):
            raise ValueError("Cryptographic authentication tag mismatch")
        stream_key = hashlib.sha256(key + iv).digest()
        plain_bytes = bytes(b ^ stream_key[i % len(stream_key)] for i, b in enumerate(encrypted))
        return plain_bytes.decode("utf-8")


def tokenize_instrument(instrument_str: str, merchant_id: str = "global") -> str:
    """Deterministic HMAC-SHA256 blind tokenization for cards and sensitive identifiers."""
    if not instrument_str:
        return ""
    key = derive_key(f"{_effective_pepper(None)}:{merchant_id}")
    digest = hmac.new(key, instrument_str.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"ins_tok_{digest[:24]}"
