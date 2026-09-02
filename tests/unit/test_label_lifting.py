"""Unit tests for window label lifting and sensitivity analysis (Phase 2.3 & ADR-003)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.schemas.enums import WindowLabel
from app.windows import WindowSize
from data.generators.injection import inject_scenario_into_timeline
from data.generators.lifting import (
    compute_label_sensitivity,
    lift_labels_to_windows,
)
from data.generators.population import generate_merchant_population
from data.generators.timeline import generate_organic_timeline


@pytest.fixture
def sample_profile():
    return generate_merchant_population(n_merchants=1, seed=42)[0]


def test_label_lifting_distinguishes_flash_sale_from_fraud_spike(sample_profile):
    """ADR-003: Flash sale must lift to LEGIT_SPIKE and NOT FRAUD_SPIKE."""
    start_ts = datetime(2026, 3, 2, 10, 0, 0, tzinfo=UTC)

    # 1. Base timeline
    base_txns = generate_organic_timeline(
        profile=sample_profile,
        start_time=start_ts,
        duration=timedelta(hours=2),
        seed=42,
    )

    # 2. Inject flash sale at 10:30
    sale_txns = inject_scenario_into_timeline(
        profile=sample_profile,
        base_transactions=base_txns,
        scenario_id="flash_sale_spike",
        start_time=start_ts + timedelta(minutes=30),
        seed=101,
    )

    # 3. Lift labels
    window_labels = lift_labels_to_windows(
        transactions=sale_txns,
        merchant_id=sample_profile.merchant.merchant_id,
        window_sizes=(WindowSize.M5, WindowSize.M15),
    )

    labels_set = {l.label for l in window_labels}
    assert WindowLabel.LEGIT_SPIKE in labels_set
    assert WindowLabel.FRAUD_SPIKE not in labels_set, (
        "Flash sale was erroneously lifted as FRAUD_SPIKE! Hard negative separation violated."
    )


def test_label_lifting_identifies_card_testing_as_fraud_spike(sample_profile):
    """ADR-003: Card testing burst must lift to FRAUD_SPIKE when exceeding K and M."""
    start_ts = datetime(2026, 3, 2, 10, 0, 0, tzinfo=UTC)

    base_txns = generate_organic_timeline(
        profile=sample_profile,
        start_time=start_ts,
        duration=timedelta(hours=2),
        seed=42,
    )

    # Inject card testing burst at 10:30
    attack_txns = inject_scenario_into_timeline(
        profile=sample_profile,
        base_transactions=base_txns,
        scenario_id="card_testing_burst",
        start_time=start_ts + timedelta(minutes=30),
        intensity=1.5,
        seed=202,
    )

    window_labels = lift_labels_to_windows(
        transactions=attack_txns,
        merchant_id=sample_profile.merchant.merchant_id,
        window_sizes=(WindowSize.M5,),
        K=5,
        M=0.20,
    )

    fraud_windows = [w for w in window_labels if w.label is WindowLabel.FRAUD_SPIKE]
    assert len(fraud_windows) > 0, "Card testing burst failed to lift to FRAUD_SPIKE"

    # Verify that positive window satisfies K and M
    for w in fraud_windows:
        assert w.n_abusive >= 5
        assert w.abusive_share >= 0.20


def test_compute_label_sensitivity_grid(sample_profile):
    """Verify that sensitivity table computes varying label counts across K and M."""
    start_ts = datetime(2026, 3, 2, 10, 0, 0, tzinfo=UTC)

    base_txns = generate_organic_timeline(
        profile=sample_profile,
        start_time=start_ts,
        duration=timedelta(hours=1),
        seed=42,
    )

    attack_txns = inject_scenario_into_timeline(
        profile=sample_profile,
        base_transactions=base_txns,
        scenario_id="card_testing_burst",
        start_time=start_ts + timedelta(minutes=15),
        intensity=1.0,
        seed=303,
    )

    sensitivity = compute_label_sensitivity(
        transactions=attack_txns,
        merchant_id=sample_profile.merchant.merchant_id,
        K_grid=(3, 5, 10),
        M_grid=(0.10, 0.20, 0.40),
    )

    assert len(sensitivity) == 9  # 3x3 grid
    assert (5, 0.20) in sensitivity
    assert sensitivity[(5, 0.20)]["FRAUD_SPIKE"] > 0
