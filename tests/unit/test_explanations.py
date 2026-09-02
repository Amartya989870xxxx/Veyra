"""Unit tests for explanation generation and visual evidence payloads (Phase 6.2)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import pytest

from app.decision.exposure import compute_incident_exposure
from app.decision.policy import PolicyDecision
from app.explanations.generator import generate_incident_narrative
from app.explanations.visual_evidence import (
    build_entity_graph_payload,
    build_top_feature_deviations,
)
from app.schemas.entities import PaymentAttempt
from app.schemas.enums import ActionTier
from app.windows import WindowSize


def test_generate_incident_narrative_highlights_key_deviations():
    """Verify narrative generator produces contextual comparison and recommended action."""
    features = {
        "B.txn_count": 45.0,
        "D.gmv": 150000.0,
        "C.failure_rate": 0.82,
        "A.txn_rate_dev": 5.4,
        "J.largest_cluster_vol_share": 0.88,
        "J.bipartite_gini": 0.92,
        "C.instrument_novelty": 0.95,
    }
    decision = PolicyDecision(
        action_tier=ActionTier.RESTRICT,
        risk_score=0.94,
        recommended_defensive_control="RECOMMEND_INSTRUMENT_VELOCITY_CAP",
        rationale="High volume of issuer card declines on novel instrument hashes.",
    )
    exposure = compute_incident_exposure(at_risk_gmv=150000.0, n_txns=45)

    narrative = generate_incident_narrative(
        merchant_id="m_001",
        window_size=WindowSize.M5,
        risk_score=0.94,
        policy_decision=decision,
        features=features,
        exposure=exposure,
    )

    assert "45 transactions" in narrative
    assert "+5.4 MADs" in narrative
    assert "High Entity Concentration" in narrative
    assert "RECOMMEND_INSTRUMENT_VELOCITY_CAP" in narrative
    assert "RESTRICT" in narrative


def test_build_visual_evidence_payloads():
    """Verify visual evidence builder formats top deviations and bipartite graph nodes/edges."""
    features = {
        "A.txn_rate": 15.0,
        "A.txn_rate_dev": 4.5,
        "C.failure_rate": 0.80,
        "C.failure_rate_dev": 6.2,
        "J.largest_cluster_vol_share_dev": 5.1,
    }

    deviations = build_top_feature_deviations(features, top_k=3)
    assert len(deviations) == 3
    assert deviations[0]["feature_id"] == "C.failure_rate"
    assert deviations[0]["deviation_mad"] == 6.2

    now = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)
    attempts = [
        PaymentAttempt(
            transaction_id="txn_01",
            merchant_id="m_001",
            customer_id="cus_01",
            device_fp="dev_01",
            instrument_fp="ins_01",
            amount=Decimal("100.00"),
            timestamp=now,
        ),
        PaymentAttempt(
            transaction_id="txn_02",
            merchant_id="m_001",
            customer_id="cus_02",
            device_fp="dev_01",
            instrument_fp="ins_02",
            amount=Decimal("100.00"),
            timestamp=now,
        ),
    ]

    graph = build_entity_graph_payload(attempts)
    assert graph["total_nodes"] > 0
    assert graph["total_edges"] > 0
    assert any(n["type"] == "device" for n in graph["nodes"])
