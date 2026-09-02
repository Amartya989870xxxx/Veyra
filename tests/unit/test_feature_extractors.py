"""Unit tests for feature extraction and statistical aggregators (Phase 3.1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.features.aggregator import WindowAgg, compute_window_features_dict
from app.registry import load_features
from app.schemas.enums import PaymentMethod
from app.windows import WindowSize
from data.generators.population import generate_merchant_population
from data.generators.timeline import generate_organic_timeline


@pytest.fixture
def sample_merchant_profile():
    return generate_merchant_population(n_merchants=1, seed=42)[0]


def test_empty_window_features_do_not_error(sample_merchant_profile):
    """Empty window must compute zero-state features without NaN or exceptions."""
    w_end = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)
    agg = WindowAgg(
        merchant_id=sample_merchant_profile.merchant.merchant_id,
        window_size=WindowSize.M5,
        window_end=w_end,
        transactions=[],
    )

    features = compute_window_features_dict(agg)
    assert len(features) > 0

    for fid, val in features.items():
        assert not (val != val), f"Feature {fid} produced NaN on empty window"
        assert not (val == float("inf") or val == float("-inf")), f"Feature {fid} produced infinite value"


def test_active_window_computes_expected_features(sample_merchant_profile):
    """Active transaction window computes non-zero statistics across Families A-I."""
    start_ts = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)
    txns = generate_organic_timeline(
        profile=sample_merchant_profile,
        start_time=start_ts,
        duration=timedelta(minutes=15),
        seed=42,
    )

    agg = WindowAgg(
        merchant_id=sample_merchant_profile.merchant.merchant_id,
        window_size=WindowSize.M15,
        window_end=start_ts + timedelta(minutes=15),
        transactions=txns,
    )

    features = compute_window_features_dict(agg)

    # Validate key feature values
    assert features["B.txn_count"] == float(len(txns))
    assert features["A.txn_rate"] > 0.0
    assert features["D.gmv"] > 0.0
    assert features["C.devices_per_txn"] > 0.0
    assert 0.0 <= features["C.failure_rate"] <= 1.0


def test_all_declared_feature_keys_computed():
    """Every non-graph declared feature in research/features.yaml must be computed."""
    declared = load_features()
    w_end = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)
    agg = WindowAgg(merchant_id="m_001", window_size=WindowSize.M5, window_end=w_end, transactions=[])
    features = compute_window_features_dict(agg)

    for fid, spec in declared.items():
        if spec.family != "J":  # Graph family is computed by GraphEngine
            assert fid in features, f"Feature {fid} declared in features.yaml but missing from aggregator"
