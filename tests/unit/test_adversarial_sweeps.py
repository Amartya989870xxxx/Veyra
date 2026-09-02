"""Unit tests for adversarial evasion injection recipes (Phase 7.1)."""

from __future__ import annotations

from datetime import UTC, datetime
import random
import pytest

from data.generators.population import generate_merchant_population
from data.generators.recipes import (
    SCENARIO_RECIPES,
    inject_card_testing_low_value,
    inject_low_volume_relationship_anomaly,
    inject_ring_under_flash_sale,
    inject_slow_ramp_infiltration,
)


@pytest.fixture
def sample_profile():
    return generate_merchant_population(n_merchants=1, seed=42)[0]


def test_ring_under_flash_sale_combines_legit_and_fraud(sample_profile):
    """Verify E1 produces mix of benign flash sale buyers and fraud ring attempts."""
    now = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)
    rng = random.Random(42)

    txns = inject_ring_under_flash_sale(sample_profile, now, rng, intensity=1.0)
    assert len(txns) > 20

    # Must contain both abusive and non-abusive transactions
    abusive_count = sum(1 for t in txns if t.is_abusive)
    benign_count = sum(1 for t in txns if not t.is_abusive)

    assert abusive_count > 0
    assert benign_count > 0


def test_slow_ramp_infiltration_ramps_smoothly(sample_profile):
    """Verify E2 generates gradual linear transaction volume acceleration."""
    now = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)
    rng = random.Random(42)

    txns = inject_slow_ramp_infiltration(sample_profile, now, rng, intensity=1.0)
    assert len(txns) > 30

    # Spans ~60 minutes
    times = [t.attempt.timestamp for t in txns]
    span_min = (max(times) - min(times)).total_seconds() / 60.0
    assert span_min > 40.0


def test_low_volume_relationship_anomaly_generates_small_cluster(sample_profile):
    """Verify E4 generates high entity sharing with sub-threshold transaction counts."""
    now = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)
    rng = random.Random(42)

    txns = inject_low_volume_relationship_anomaly(sample_profile, now, rng, intensity=1.0)
    assert 6 <= len(txns) <= 15
    # All transactions share the same device
    devices = {t.attempt.device_fp for t in txns}
    assert len(devices) == 1


def test_card_testing_low_value_generates_micro_amounts(sample_profile):
    """Verify E6 generates micro-amounts between ₹5 and ₹45."""
    now = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)
    rng = random.Random(42)

    txns = inject_card_testing_low_value(sample_profile, now, rng, intensity=1.0)
    assert len(txns) >= 25
    for t in txns:
        assert 5.0 <= float(t.attempt.amount) <= 45.0
