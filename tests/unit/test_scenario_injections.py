"""Unit tests for scenario injection recipes and anti-leakage invariants (Phase 2.2 & 2.4)."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from data.generators.injection import inject_scenario_into_timeline
from data.generators.population import generate_merchant_population
from data.generators.recipes import SCENARIO_RECIPES
from data.generators.timeline import generate_organic_timeline


@pytest.fixture
def sample_merchant_profile():
    profiles = generate_merchant_population(n_merchants=1, seed=42)
    return profiles[0]


@pytest.mark.parametrize("scenario_id", list(SCENARIO_RECIPES.keys()))
def test_all_scenario_recipes_run_and_inject(sample_merchant_profile, scenario_id: str):
    """Verify that every scenario recipe executes without errors and emits valid transactions."""
    start_ts = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)
    base_txns = generate_organic_timeline(
        profile=sample_merchant_profile,
        start_time=start_ts,
        duration=timedelta(hours=2),
        seed=42,
    )

    combined = inject_scenario_into_timeline(
        profile=sample_merchant_profile,
        base_transactions=base_txns,
        scenario_id=scenario_id,
        start_time=start_ts + timedelta(minutes=30),
        intensity=1.0,
        seed=101,
    )

    assert len(combined) > len(base_txns)

    # Verify chronological sort
    for i in range(1, len(combined)):
        assert combined[i].attempt.timestamp >= combined[i - 1].attempt.timestamp

    # Check that injected transactions have valid scenario_id
    scenario_txns = [t for t in combined if t.scenario_id == scenario_id]
    assert len(scenario_txns) > 0


def test_anti_leakage_no_constant_sentinel_amount(sample_merchant_profile):
    """ADR-007 check: Card testing transactions must NOT all share an identical constant price."""
    start_ts = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)
    recipe_fn = SCENARIO_RECIPES["card_testing_burst"]

    rng = random.Random(42)
    txns = recipe_fn(sample_merchant_profile, start_ts, rng, intensity=1.0)

    amounts = {t.attempt.amount for t in txns}
    # Amounts must be varied across a distribution, not a fixed sentinel value like 1.00
    assert len(amounts) > 5, "Card testing amounts must draw from a continuous distribution"


def test_anti_leakage_variable_intensity(sample_merchant_profile):
    """ADR-007 check: Attack intensity scaling produces varied counts."""
    start_ts = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)
    recipe_fn = SCENARIO_RECIPES["card_testing_burst"]

    low_intensity_txns = recipe_fn(sample_merchant_profile, start_ts, random.Random(42), intensity=0.5)
    high_intensity_txns = recipe_fn(sample_merchant_profile, start_ts, random.Random(42), intensity=2.0)

    assert len(high_intensity_txns) > len(low_intensity_txns)
