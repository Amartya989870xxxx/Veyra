"""Tests for Veyra's 20-Point Production Security Suite."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.crypto import decrypt_sensitive_field, encrypt_sensitive_field, tokenize_instrument
from app.core.security import hash_password, verify_password
from app.core.auth import AuthenticatedPrincipal, UserRole, verify_tenant_access
from app.main import app


@pytest.mark.asyncio
async def test_crypto_aes_gcm_roundtrip():
    """Item 5: Sensitive data encryption and decryption."""
    secret = "customer_ssn_or_card_9988"
    encrypted = encrypt_sensitive_field(secret)
    assert encrypted != secret
    decrypted = decrypt_sensitive_field(encrypted)
    assert decrypted == secret


@pytest.mark.asyncio
async def test_crypto_blind_tokenization():
    """Item 5: Blind indexing for payment instruments."""
    card = "4111222233334444"
    tok1 = tokenize_instrument(card, merchant_id="m_001")
    tok2 = tokenize_instrument(card, merchant_id="m_001")
    tok_diff_merchant = tokenize_instrument(card, merchant_id="m_002")

    assert tok1 == tok2
    assert tok1.startswith("ins_tok_")
    assert tok1 != tok_diff_merchant  # Salted per tenant


@pytest.mark.asyncio
async def test_owasp_password_hashing():
    """Item 10: PBKDF2-HMAC-SHA256 password verification."""
    password = "VeyraSecurePassword#2026!"
    hashed = hash_password(password)
    assert hashed.startswith("pbkdf2:sha256:600000$")
    assert verify_password(password, hashed) is True
    assert verify_password("wrong_password", hashed) is False


@pytest.mark.asyncio
async def test_row_level_multi_tenant_isolation():
    """Item 4: Tenant isolation check."""
    user = AuthenticatedPrincipal(
        principal_id="user_1",
        merchant_id="m_electronics_01",
        role=UserRole.ANALYST,
    )
    assert user.can_access_merchant("m_electronics_01") is True
    assert user.can_access_merchant("m_luxury_02") is False

    # Should not raise for owned merchant
    verify_tenant_access(user, "m_electronics_01")

    # Should raise HTTP 403 for other merchant
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        verify_tenant_access(user, "m_luxury_02")
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_security_headers_middleware():
    """Item 18: Verify all enterprise security headers are present."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        headers = resp.headers
        assert headers.get("X-Content-Type-Options") == "nosniff"
        assert headers.get("X-Frame-Options") == "SAMEORIGIN"
        assert headers.get("X-XSS-Protection") == "1; mode=block"
        assert "Content-Security-Policy" in headers
        assert "Permissions-Policy" in headers
        assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


@pytest.mark.asyncio
async def test_bot_user_agent_blocked():
    """Item 12: Malicious scanner bot blocking."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health", headers={"User-Agent": "sqlmap/1.5.2"})
        assert resp.status_code == 403
        data = resp.json()
        assert "Automated scanner or malicious bot" in data.get("error", "")


@pytest.mark.asyncio
async def test_extra_field_tampering_rejected():
    """Item 8: Pydantic rejects extra unexpected fields."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/events",
            json={
                "event_id": "evt_tamper_01",
                "event_type": "payment_attempt",
                "timestamp": "2026-08-30T00:00:00Z",
                "hacked_admin_field": True,  # Disallowed extra field
                "payment_attempt": {
                    "transaction_id": "txn_01",
                    "merchant_id": "m_001",
                    "customer_id": "cus_01",
                    "amount": 100.0,
                    "currency": "INR",
                    "timestamp": "2026-08-30T00:00:00Z",
                    "device_fp": "dv_01",
                    "instrument_fp": "ins_01",
                },
            },
        )
        assert resp.status_code == 422  # Pydantic validation error for forbidden field
