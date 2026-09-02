"""Authentication, tenant isolation, crypto fail-closed, and CORS tests.

Added during the production-hardening pass. Before this pass, `app/core/auth.py`'s
RBAC/tenant-isolation logic (`AuthenticatedPrincipal`, `verify_tenant_access`) was
exercised only by unit tests calling it directly in isolation
(`tests/security/test_security_suite.py`) and was never wired into a single FastAPI route — no
test in the suite ever sent an HTTP request that a cross-tenant caller should have been
denied. These tests exercise the real request path end to end: real routes, real
dependency injection, real `Settings` construction.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import ApiKeyEntry, Settings, get_settings
from app.main import app

MERCHANT_A_KEY = "vy_test_merchant_a_key"
MERCHANT_B_KEY = "vy_test_merchant_b_key"
SYSTEM_KEY = "vy_test_system_key"


@pytest.fixture
def configured_keys(monkeypatch):
    """Install real API keys for two merchants plus a system credential, and force
    credential checking on so the non-production demo bypass does not mask the
    behaviour under test. `monkeypatch` restores the original settings automatically."""
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "api_keys",
        [
            ApiKeyEntry(key=MERCHANT_A_KEY, merchant_id="m_alpha", role="analyst"),
            ApiKeyEntry(key=MERCHANT_B_KEY, merchant_id="m_bravo", role="analyst"),
            ApiKeyEntry(key=SYSTEM_KEY, merchant_id="global", role="system_service"),
        ],
    )
    monkeypatch.setattr(settings, "require_auth", True)
    return settings


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://authtest") as c:
        yield c


# ------------------------------------------------------------------------------------
# AUTHENTICATION
# ------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_access_to_protected_route_fails(client, configured_keys):
    resp = await client.get("/v2/incidents")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_valid_authenticated_access_succeeds(client, configured_keys):
    resp = await client.get("/v2/incidents", headers={"X-API-Key": MERCHANT_A_KEY})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_invalid_credentials_fail(client, configured_keys):
    resp = await client.get("/v2/incidents", headers={"X-API-Key": "not_a_real_key"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_ingestion_endpoint_also_requires_auth_when_configured(client, configured_keys):
    resp = await client.post(
        "/api/v1/events",
        json={
            "event_id": "evt_auth_test_1",
            "event_type": "PAYMENT_ATTEMPT",
            "timestamp": "2026-03-02T12:00:00Z",
            "payment_attempt": {
                "transaction_id": "txn_auth_1",
                "merchant_id": "m_alpha",
                "customer_id": "cus_1",
                "amount": 100.0,
                "currency": "INR",
                "timestamp": "2026-03-02T12:00:00Z",
                "device_fp": "dv_1",
                "instrument_fp": "ins_1",
            },
        },
    )
    assert resp.status_code == 401


def test_production_cannot_silently_bypass_authentication():
    """The literal issue the audit flagged: `environment == "production"` used to be
    unreachable because `Settings`'s Literal type didn't include the value at all. It
    does now, and `require_auth=False` must not matter once environment=production."""
    with pytest.raises(Exception):
        Settings(environment="production", crypto_pepper=None, api_keys=[], cors_allowed_origins="")

    configured = dict(
        crypto_pepper="p",
        api_keys=[{"key": "k", "merchant_id": "m", "role": "analyst"}],
        cors_allowed_origins="https://example.com",
    )
    assert Settings(environment="production", **configured).auth_required is True
    assert Settings(environment="production", require_auth=False, **configured).auth_required is True
    assert Settings(environment="local", require_auth=False).auth_required is False


# ------------------------------------------------------------------------------------
# TENANT ISOLATION
# ------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merchant_cannot_list_another_merchants_incidents(client, configured_keys):
    resp = await client.get("/v2/incidents?merchant_id=m_bravo", headers={"X-API-Key": MERCHANT_A_KEY})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_merchant_cannot_retrieve_another_merchants_baselines(client, configured_keys):
    resp = await client.get("/v2/merchants/m_bravo/baselines", headers={"X-API-Key": MERCHANT_A_KEY})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_client_supplied_merchant_id_cannot_override_authenticated_tenant(client, configured_keys):
    """Merchant A's key, scoring a window it claims is for merchant B: must be denied,
    not silently rescoped to A and not silently honoured for B."""
    resp = await client.post(
        "/v2/score-window",
        json={"merchant_id": "m_bravo", "window_size": "5m"},
        headers={"X-API-Key": MERCHANT_A_KEY},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_unscoped_request_defaults_to_own_tenant_not_all_tenants(client, configured_keys):
    """Before this pass, GET /v2/incidents with no merchant_id listed incidents across
    every merchant (`IncidentStoreRepository.list_incidents(merchant_id=None)` applies
    no filter). An authenticated non-system caller must never see that."""
    resp = await client.get("/v2/incidents", headers={"X-API-Key": MERCHANT_A_KEY})
    assert resp.status_code == 200
    for row in resp.json():
        assert row["merchant_id"] == "m_alpha"


@pytest.mark.asyncio
async def test_system_service_key_can_access_any_merchant(client, configured_keys):
    resp = await client.get("/v2/merchants/m_bravo/baselines", headers={"X-API-Key": SYSTEM_KEY})
    assert resp.status_code == 200
    assert resp.json()["merchant_id"] == "m_bravo"


@pytest.mark.asyncio
async def test_cross_tenant_incident_lookup_denied(client, configured_keys):
    """GET /v2/incidents/{id} carries no merchant_id in the URL at all — the loaded
    row's merchant_id against the caller is the only enforcement point there is."""
    import uuid

    from app.core.db import session_scope
    from app.models.entities import IncidentStoreRow

    incident_id = f"inc_test_cross_tenant_{uuid.uuid4().hex[:12]}"
    now = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)
    async with session_scope() as session:
        session.add(
            IncidentStoreRow(
                incident_id=incident_id,
                merchant_id="m_bravo",
                status="OPEN",
                action_tier="RESTRICT",
                first_flag_time=now,
                last_flag_time=now,
                window_sizes=["5m"],
                risk_score=0.9,
                evidence={},
                explanation="test fixture row",
            )
        )

    denied = await client.get(f"/v2/incidents/{incident_id}", headers={"X-API-Key": MERCHANT_A_KEY})
    assert denied.status_code == 404  # not 403: existence is not disclosed cross-tenant

    owner = await client.get(f"/v2/incidents/{incident_id}", headers={"X-API-Key": MERCHANT_B_KEY})
    assert owner.status_code == 200

    action_denied = await client.post(
        f"/v2/incidents/{incident_id}/action",
        json={"action": "ACKNOWLEDGE"},
        headers={"X-API-Key": MERCHANT_A_KEY},
    )
    assert action_denied.status_code == 404


# ------------------------------------------------------------------------------------
# CRYPTO FAIL-CLOSED
# ------------------------------------------------------------------------------------


def test_production_startup_fails_without_crypto_pepper():
    with pytest.raises(Exception):
        Settings(
            environment="production",
            crypto_pepper=None,
            api_keys=[{"key": "k", "merchant_id": "m", "role": "analyst"}],
            cors_allowed_origins="https://example.com",
        )


def test_no_production_fallback_secret_silently_used(monkeypatch):
    from app.core import crypto
    from app.core.config import settings as live_settings

    monkeypatch.setattr(live_settings, "environment", "production")
    monkeypatch.setattr(live_settings, "crypto_pepper", None)
    with pytest.raises(RuntimeError):
        crypto._effective_pepper(None)


def test_encryption_still_works_with_a_configured_pepper(monkeypatch):
    from app.core import crypto
    from app.core.config import settings as live_settings

    monkeypatch.setattr(live_settings, "crypto_pepper", "an-explicitly-configured-test-pepper")
    plaintext = "customer_ssn_or_card_9988"
    enc = crypto.encrypt_sensitive_field(plaintext)
    assert enc != plaintext
    assert crypto.decrypt_sensitive_field(enc) == plaintext


# ------------------------------------------------------------------------------------
# CORS
# ------------------------------------------------------------------------------------


def test_production_cors_rejects_wildcard_only_configuration():
    with pytest.raises(Exception):
        Settings(
            environment="production",
            crypto_pepper="p",
            api_keys=[{"key": "k", "merchant_id": "m", "role": "analyst"}],
            cors_allowed_origins="*",
        )


@pytest.mark.asyncio
async def test_production_cors_trusts_configured_origin_and_rejects_others(monkeypatch):
    from app.main import create_app

    monkeypatch.setenv("VEYRA_ENVIRONMENT", "production")
    monkeypatch.setenv("VEYRA_CRYPTO_PEPPER", "p")
    monkeypatch.setenv("VEYRA_API_KEYS", '[{"key":"k","merchant_id":"m","role":"analyst"}]')
    monkeypatch.setenv("VEYRA_CORS_ALLOWED_ORIGINS", "https://trusted.example.com")
    get_settings.cache_clear()
    try:
        prod_app = create_app()
        transport = ASGITransport(app=prod_app)
        async with AsyncClient(transport=transport, base_url="http://prodtest") as c:
            trusted = await c.get("/health", headers={"Origin": "https://trusted.example.com"})
            assert trusted.headers.get("access-control-allow-origin") == "https://trusted.example.com"

            untrusted = await c.get("/health", headers={"Origin": "https://evil.example.com"})
            assert untrusted.headers.get("access-control-allow-origin") is None
    finally:
        get_settings.cache_clear()
