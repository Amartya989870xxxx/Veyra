"""Unit tests for robust MAD baselines and deviation twins (Phase 3.2)."""

from __future__ import annotations

from datetime import UTC, datetime
import statistics
import pytest

from app.features.baselines import (
    BaselineEngine,
    BaselineProfile,
    compute_median_and_mad,
    fit_baselines_from_window_history,
)
from app.schemas.enums import BaselineConfidence
from app.windows import WindowSize


def test_mad_robustness_against_outlier_spike():
    """Verify MAD is resilient to injected extreme fraud spike outliers compared to standard deviation."""
    # Clean historical values: ~10 transactions/min with small noise
    clean_series = [10.0 + (i % 3) * 0.5 for i in range(50)]
    med_clean, mad_clean = compute_median_and_mad(clean_series)
    std_clean = statistics.stdev(clean_series)

    # Injected attack spike: 500 transactions/min
    poisoned_series = clean_series + [500.0, 600.0]
    med_poisoned, mad_poisoned = compute_median_and_mad(poisoned_series)
    std_poisoned = statistics.stdev(poisoned_series)

    # Standard deviation gets massively inflated by the outlier
    assert std_poisoned > std_clean * 5.0

    # MAD remains rock solid (robust scale)
    assert abs(mad_poisoned - mad_clean) < 1.0
    assert abs(med_poisoned - med_clean) < 0.5


def test_deviation_twin_calculation():
    """Verify deviation twin computation produces expected standard score."""
    baselines = {
        ("m_001", "A.txn_rate", "5m", 42): BaselineProfile(
            expected_median=10.0,
            variability_mad=2.0,
            sample_count=50,
            confidence=BaselineConfidence.HIGH,
        )
    }
    engine = BaselineEngine(merchant_baselines=baselines)

    # Observed value 16.0 -> deviation = (16.0 - 10.0) / 2.0 = +3.0 MADs
    dev, conf = engine.compute_deviation_twin(
        merchant_id="m_001",
        feature_id="A.txn_rate",
        value=16.0,
        window_size=WindowSize.M5,
        hour_of_week=42,
    )

    assert dev == pytest.approx(3.0, abs=1e-4)
    assert conf is BaselineConfidence.HIGH


def test_cold_start_category_fallback():
    """Merchants with no history must fall back to category profile and report LOW confidence."""
    cat_baselines = {
        ("electronics", "A.txn_rate", "5m", 10): BaselineProfile(
            expected_median=15.0,
            variability_mad=3.0,
            sample_count=100,
            confidence=BaselineConfidence.MEDIUM,
        )
    }
    engine = BaselineEngine(
        category_baselines=cat_baselines,
        merchant_categories={"m_new": "electronics"},
    )

    dev, conf = engine.compute_deviation_twin(
        merchant_id="m_new",
        feature_id="A.txn_rate",
        value=21.0,
        window_size=WindowSize.M5,
        hour_of_week=10,
    )

    # (21.0 - 15.0) / 3.0 = 2.0
    assert dev == pytest.approx(2.0, abs=1e-4)
    assert conf is BaselineConfidence.LOW, "Cold-start fallback must report LOW confidence"
