"""Regression tests for synthetic-generator shortcuts.

Each test here pins a specific artifact that was found by measurement (single-feature
AUC sweeps and zero-variance checks over generated windows) and then removed. They exist
so the shortcuts cannot reappear silently — a generator that hands the model a constant
makes every downstream metric meaningless, and the failure is invisible in aggregate
scores because the scores go *up*.

What these tests do NOT claim: that the generator is now realistic. Attack recipes still
concentrate entities more cleanly than production traffic would, and that residual is
documented as a limitation in research/BENCHMARK_RESULTS.md rather than tested away here.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from data.generators.population import generate_merchant_population
from data.generators.recipes import (
    inject_bin_enumeration_attack,
    inject_device_farm_ring,
    inject_flash_sale_spike,
    inject_promo_coupon_harvesting,
    inject_subscription_renewal_batch,
)

START = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def profile():
    return generate_merchant_population(n_merchants=1, seed=42)[0]


def _amounts(txns):
    return [float(t.attempt.amount) for t in txns]


def _codes(txns):
    return [t.outcome.failure_code for t in txns if t.outcome and t.outcome.failure_code]


def test_promo_abuse_amounts_are_not_a_single_constant(profile):
    """Was: every harvested order priced at exactly 501.00, so amount variance was 0."""
    txns = inject_promo_coupon_harvesting(profile, START, random.Random(1), intensity=1.0)
    amounts = _amounts(txns)

    assert len(set(amounts)) > 5, "promo abuse amounts collapsed back to a constant"
    assert min(amounts) >= 501.0, "promo abuse should still sit above the discount threshold"


def test_subscription_renewals_use_plan_tiers_not_one_price(profile):
    """Was: every renewal at exactly avg_ticket_size — a hard negative with zero variance."""
    txns = inject_subscription_renewal_batch(profile, START, random.Random(2), intensity=1.0)
    amounts = set(_amounts(txns))

    assert len(amounts) >= 2, "subscription batch is still a single-price constant"


def test_attack_decline_codes_are_a_distribution_not_one_value(profile):
    """Was: one hard-coded failure code per scenario, so decline entropy was exactly 0."""
    farm = _codes(inject_device_farm_ring(profile, START, random.Random(3), intensity=1.5))
    enum = _codes(inject_bin_enumeration_attack(profile, START, random.Random(4), intensity=1.5))

    assert len(set(farm)) > 1, "device farm still emits a single decline code"
    assert len(set(enum)) > 1, "BIN enumeration still emits a single decline code"


def test_bin_enumeration_identities_vary_between_episodes(profile):
    """Was: one global device fingerprint and BIN hash shared by every episode ever."""
    a = inject_bin_enumeration_attack(profile, START, random.Random(5), intensity=1.0)
    b = inject_bin_enumeration_attack(profile, START, random.Random(6), intensity=1.0)

    dev_a = {t.attempt.device_fp for t in a}
    dev_b = {t.attempt.device_fp for t in b}
    bins_a = {t.attempt.instrument_meta.bin_hash for t in a if t.attempt.instrument_meta}
    bins_b = {t.attempt.instrument_meta.bin_hash for t in b if t.attempt.instrument_meta}

    assert dev_a != dev_b, "every BIN-enumeration episode shares one attacker device"
    assert bins_a != bins_b, "every BIN-enumeration episode targets one global BIN"


def test_flash_sale_has_returning_buyers_not_a_perfect_one_to_one_mapping(profile):
    """The largest artifact found: every flash-sale buyer had a unique device/card/IP.

    That put legitimate surges at `devices_per_txn == 1.0` and attacks near 0.2, making
    the flash-sale-vs-attack discrimination — the product's core claim — separable by a
    single column.
    """
    txns = inject_flash_sale_spike(profile, START, random.Random(7), intensity=1.0)
    assert len(txns) > 40, "fixture too small to measure reuse"

    devices = [t.attempt.device_fp for t in txns]
    devices_per_txn = len(set(devices)) / len(devices)

    assert devices_per_txn < 0.95, (
        f"flash sale still has a near 1:1 device mapping ({devices_per_txn:.3f}); "
        "legitimate surges must contain returning buyers"
    )


def test_organic_traffic_repeats_entities_within_a_window():
    """Legitimate traffic needs a device-sharing tail (households, office NAT, retries)."""
    from datetime import timedelta

    from data.generators.timeline import generate_organic_timeline

    profile = generate_merchant_population(n_merchants=1, seed=11)[0]
    txns = generate_organic_timeline(
        profile=profile, start_time=START, duration=timedelta(hours=6), seed=11
    )
    assert len(txns) > 50, "fixture too small to measure reuse"

    devices = [t.attempt.device_fp for t in txns]
    assert len(set(devices)) < len(devices), "organic traffic never repeats a device"


def test_generator_changes_remain_reproducible_for_a_fixed_seed(profile):
    """Every fix above uses the injected RNG, so seeds must still reproduce exactly."""
    a = inject_promo_coupon_harvesting(profile, START, random.Random(99), intensity=1.0)
    b = inject_promo_coupon_harvesting(profile, START, random.Random(99), intensity=1.0)

    assert _amounts(a) == _amounts(b)
    assert [t.attempt.device_fp for t in a] == [t.attempt.device_fp for t in b]
