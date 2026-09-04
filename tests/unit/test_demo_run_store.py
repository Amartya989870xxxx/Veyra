"""Retention and ownership bounds on the demo run store (Part 7, E-adjacent).

The store exists so the explorer has something to page through; these pin that it can
never become an unbounded accumulation of synthetic runs, and that one principal's run
is not readable by another.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from app.core.auth import AuthenticatedPrincipal, UserRole
from app.features.engine import WindowFeatureVector
from app.schemas.enums import BaselineConfidence
from app.serving.demo_run_store import DemoRunRecord, DemoRunStore
from app.windows import WindowSize


def _record(run_id: str, created_by: str = "principal_a") -> DemoRunRecord:
    return DemoRunRecord(
        run_id=run_id,
        created_by=created_by,
        created_at=datetime(2026, 3, 2, 12, 0, tzinfo=UTC),
        scenario_id="card_testing_burst",
        merchant_category="electronics",
        merchant_id="m_test",
        window_size=WindowSize.M5,
        window_end=datetime(2026, 3, 2, 12, 0, tzinfo=UTC),
        transactions=[],
        feature_vector=WindowFeatureVector(
            merchant_id="m_test",
            window_size=WindowSize.M5,
            window_end=datetime(2026, 3, 2, 12, 0, tzinfo=UTC),
            all_features={},
            model_features={},
            evidence={},
            baseline_confidence=BaselineConfidence.LOW,
        ),
        entity_graph_payload={"nodes": [], "edges": [], "total_nodes": 0, "total_edges": 0},
        risk_score=0.5,
        action_tier="OBSERVE",
        abusive_count=0,
        is_labelled_attack=True,
    )


def _principal(
    pid: str = "principal_a", role: UserRole = UserRole.ANALYST
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(principal_id=pid, merchant_id="m_test", role=role)


def test_store_is_bounded_by_max_runs() -> None:
    store = DemoRunStore(max_runs=3, ttl_seconds=3600)
    for i in range(10):
        store.put(_record(f"run_{i}"))

    assert len(store) == 3
    # Oldest evicted first.
    assert store.get("run_0", _principal()) is None
    assert store.get("run_9", _principal()) is not None


def test_runs_expire_after_ttl() -> None:
    store = DemoRunStore(max_runs=10, ttl_seconds=0)
    store.put(_record("run_ttl"))
    time.sleep(0.01)
    assert store.get("run_ttl", _principal()) is None


def test_another_principal_cannot_read_a_run() -> None:
    """Reads as 'not found' rather than 'forbidden', so a run_id cannot be used to probe
    whether another principal ran a demo — the same choice /v2/incidents makes."""
    store = DemoRunStore()
    store.put(_record("run_owned", created_by="principal_a"))

    assert store.get("run_owned", _principal("principal_a")) is not None
    assert store.get("run_owned", _principal("principal_b")) is None


def test_system_service_may_read_any_run() -> None:
    store = DemoRunStore()
    store.put(_record("run_owned", created_by="principal_a"))
    platform_principal = _principal("svc", UserRole.SYSTEM_SERVICE)
    assert store.get("run_owned", platform_principal) is not None


def test_unknown_run_id_returns_none() -> None:
    assert DemoRunStore().get("run_nope", _principal()) is None
