"""Unit tests for FeatureEngine coordination and downstream leakage enforcement (Phase 3.1 & ADR-004)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.features.baselines import BaselineEngine, BaselineProfile
from app.features.engine import FeatureEngine
from app.graph.engine import GraphEngine
from app.registry import DownstreamLeak, assert_no_downstream
from app.windows import WindowSize
from data.generators.population import generate_merchant_population
from data.generators.timeline import generate_organic_timeline


@pytest.fixture
def sample_profile():
    return generate_merchant_population(n_merchants=1, seed=42)[0]


def test_feature_engine_extracts_model_features_and_evidence(sample_profile):
    """Verify FeatureEngine produces clean model features, deviation twins, and evidence."""
    start_ts = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)
    txns = generate_organic_timeline(
        profile=sample_profile,
        start_time=start_ts,
        duration=timedelta(minutes=15),
        seed=42,
    )

    engine = FeatureEngine()
    vector = engine.extract_window_features(
        merchant_id=sample_profile.merchant.merchant_id,
        window_size=WindowSize.M15,
        window_end=start_ts + timedelta(minutes=15),
        transactions=txns,
    )

    assert len(vector.all_features) > 0
    assert len(vector.model_features) > 0
    assert len(vector.evidence) > 0

    # Verify model features contain deviation twins and core counts
    assert "A.txn_rate_dev" in vector.model_features
    assert "B.txn_count" in vector.model_features
    assert "C.failure_rate_dev" in vector.model_features
    assert "J.largest_cluster_vol_share" in vector.model_features

    # Verify evidence features contain raw entity counts and GMV for humans
    assert "B.unique_devices" in vector.evidence
    assert "D.gmv" in vector.evidence

    # Assert ADR-004: downstream-only features strictly absent from model_features
    assert "I.dispute_rate" not in vector.model_features
    assert "I.chargeback_rate" not in vector.model_features
    assert "I.rto_rate" not in vector.model_features


def test_feature_engine_asserts_no_downstream_leak():
    """Verify ADR-004 barrier raises DownstreamLeak when violated."""
    with pytest.raises(DownstreamLeak):
        assert_no_downstream(["A.txn_rate", "I.dispute_rate"])
