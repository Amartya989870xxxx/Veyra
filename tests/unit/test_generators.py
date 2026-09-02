"""Unit tests for population and organic timeline generators (Phase 2.1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from data.generators.population import generate_merchant_population
from data.generators.timeline import generate_organic_timeline, hour_of_week_rate_multiplier


def test_merchant_population_generation():
    """Verify that merchant population generates valid entities across size bands."""
    profiles = generate_merchant_population(n_merchants=6, seed=42)
    assert len(profiles) == 6

    # Verify categories and size bands
    size_bands = {p.merchant.size_band for p in profiles}
    assert "small" in size_bands
    assert "medium" in size_bands
    assert "enterprise" in size_bands

    for p in profiles:
        assert p.merchant.merchant_id.startswith("m_")
        assert len(p.customer_pool) >= 100
        assert len(p.device_pool) >= 100
        assert len(p.instrument_pool) >= 100
        assert len(p.ip_pool) >= 100
        assert p.hourly_baseline_txns > 0
        assert p.avg_ticket_size > Decimal("0.00")


def test_hour_of_week_seasonality():
    """Verify hour-of-week rate multiplier behaves with expected diurnal cycles."""
    # Night trough (03:00 UTC) vs afternoon peak (14:00 UTC)
    trough_ts = datetime(2026, 3, 2, 3, 0, 0, tzinfo=UTC)   # Monday 03:00
    peak_ts = datetime(2026, 3, 2, 14, 0, 0, tzinfo=UTC)    # Monday 14:00

    mult_trough = hour_of_week_rate_multiplier(trough_ts)
    mult_peak = hour_of_week_rate_multiplier(peak_ts)

    assert mult_peak > mult_trough
    assert mult_trough < 0.20
    assert mult_peak > 1.0


def test_organic_timeline_generation():
    """Verify that organic timeline simulation produces valid chronological events."""
    profiles = generate_merchant_population(n_merchants=1, seed=42)
    profile = profiles[0]

    start_ts = datetime(2026, 3, 2, 0, 0, 0, tzinfo=UTC)
    duration = timedelta(hours=6)

    txns = generate_organic_timeline(
        profile=profile,
        start_time=start_ts,
        duration=duration,
        seed=123,
    )

    assert len(txns) > 0

    # Assert strictly chronological timestamps within bounds
    for i in range(len(txns)):
        t = txns[i]
        assert start_ts <= t.attempt.timestamp < start_ts + duration
        assert t.scenario_id == "normal_day"
        assert t.is_abusive is False
        assert t.is_spike is False
        assert t.attempt.amount > Decimal("0.00")
        assert t.outcome.timestamp >= t.attempt.timestamp

        if i > 0:
            assert t.attempt.timestamp >= txns[i - 1].attempt.timestamp
