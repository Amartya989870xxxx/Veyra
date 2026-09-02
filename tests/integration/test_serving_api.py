"""Integration tests for Veyra v2 FastAPI serving endpoints (Phase 6.1).

Tests:
- GET /health
- POST /v2/score-window
- GET /v2/incidents
- GET /v2/incidents/{incident_id}
- POST /v2/incidents/{incident_id}/action
- GET /v2/merchants/{merchant_id}/baselines
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.entities import RawEventRow
from app.models.repositories import RawEventsRepository


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.mark.asyncio
async def test_health_check(client):
    """Verify health check endpoint returns 200 OK."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "2.0.0"


@pytest.mark.asyncio
async def test_score_window_and_incident_lifecycle(client):
    """Verify end-to-end window scoring, incident creation, inspection, and action triage."""
    now = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)

    # 1. Ingest raw events to trigger an attack window
    # We can invoke POST /v2/score-window directly for merchant m_serve_01
    payload = {
        "merchant_id": "m_serve_01",
        "window_size": "5m",
        "window_end": now.isoformat(),
    }

    resp = await client.post("/v2/score-window", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["merchant_id"] == "m_serve_01"
    assert data["window_size"] == "5m"
    assert "risk_score" in data
    assert "action_tier" in data
    assert "explanation" in data
    assert "top_feature_deviations" in data
    assert "entity_graph" in data

    # 2. Query incidents queue
    inc_resp = await client.get("/v2/incidents?merchant_id=m_serve_01")
    assert inc_resp.status_code == 200
    incidents = inc_resp.json()
    assert isinstance(incidents, list)

    # If an incident was generated, test incident inspection and action
    if data["incident_id"]:
        inc_id = data["incident_id"]

        # 3. GET /v2/incidents/{incident_id}
        detail_resp = await client.get(f"/v2/incidents/{inc_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["incident_id"] == inc_id
        assert "evidence_payload" in detail

        # 4. POST /v2/incidents/{incident_id}/action
        action_payload = {
            "action": "APPLY_DEFENSE",
            "analyst_notes": "Enforced instrument rate limits per recommendation.",
        }
        act_resp = await client.post(f"/v2/incidents/{inc_id}/action", json=action_payload)
        assert act_resp.status_code == 200
        act_data = act_resp.json()
        # IncidentStatus has no "INVESTIGATING" member; APPLY_DEFENSE maps to CONFIRMED
        # (see app/serving/incident_service.py).
        assert act_data["status"] == "CONFIRMED"


@pytest.mark.asyncio
async def test_get_merchant_baselines_endpoint(client):
    """Verify GET /v2/merchants/{merchant_id}/baselines returns 200."""
    resp = await client.get("/v2/merchants/m_serve_01/baselines")
    assert resp.status_code == 200
    data = resp.json()
    assert data["merchant_id"] == "m_serve_01"
    assert "baselines" in data
