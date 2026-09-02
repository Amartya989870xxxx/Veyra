"""Temporal safety and pipeline integration for the MAD baseline.

Two distinct things are tested here, and both matter:

1. **Temporal safety.** A baseline fitted on history that extends past the window it is
   applied to encodes that window's own future into its definition of "normal". The
   engine must refuse, loudly, rather than produce an optimistic number.

2. **Actual integration.** The component was previously implemented, storable, and
   exposed over an API, yet fitted nowhere and loaded nowhere — every `_dev` feature was
   a duplicate of its raw counterpart in both the evaluation runner and the production
   ScoringService. These tests assert the wiring exists, so it cannot silently rot back
   to inert.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.features.baselines import (
    BaselineConfidence,
    BaselineEngine,
    BaselineLeak,
    BaselineProfile,
    build_baseline_engine_from_rows,
    fit_baselines_from_window_history,
)
from app.features.engine import FeatureEngine
from app.windows import WindowSize

HISTORY_START = datetime(2026, 3, 1, 0, 0, tzinfo=UTC)
# hour-of-week slot the fixture history actually lands in (2026-03-01 is a Sunday).
HOW = HISTORY_START.weekday() * 24 + HISTORY_START.hour
KEY = ("m_1", "A.txn_rate", "5m", HOW)


def _history(n: int = 30, start: datetime | None = None, value: float = 10.0):
    start = start or HISTORY_START
    return [
        {
            "merchant_id": "m_1",
            "window_size": "5m",
            "window_end": start + timedelta(hours=24 * 7 * i),  # same hour-of-week slot
            "features": {"A.txn_rate": value + i},
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------- temporal safety


def test_fitting_records_its_fit_period():
    records = _history(5)
    engine = fit_baselines_from_window_history(records)
    profile = engine.get_baseline("m_1", "A.txn_rate", "5m", HOW)

    assert profile.fit_period_start == records[0]["window_end"]
    assert profile.fit_period_end == records[-1]["window_end"]


def test_applying_a_baseline_to_a_window_before_its_fit_period_end_raises():
    """The core guard: a baseline fitted through T cannot score a window ending before T."""
    engine = fit_baselines_from_window_history(_history(5))
    fit_end = engine.get_baseline("m_1", "A.txn_rate", "5m", HOW).fit_period_end

    with pytest.raises(BaselineLeak) as exc:
        engine.compute_deviation_twin(
            merchant_id="m_1",
            feature_id="A.txn_rate",
            value=50.0,
            window_size="5m",
            hour_of_week=HOW,
            window_end=fit_end - timedelta(days=1),
        )
    assert "future" in str(exc.value).lower()


def test_applying_a_baseline_forward_in_time_is_allowed():
    engine = fit_baselines_from_window_history(_history(5))
    fit_end = engine.get_baseline("m_1", "A.txn_rate", "5m", HOW).fit_period_end

    dev, _ = engine.compute_deviation_twin(
        merchant_id="m_1",
        feature_id="A.txn_rate",
        value=50.0,
        window_size="5m",
        hour_of_week=HOW,
        window_end=fit_end + timedelta(days=1),
    )
    assert dev != 50.0, "a fitted baseline must actually transform the value"


def test_in_sample_use_is_opt_in_only():
    """Transforming TRAIN with a TRAIN-fitted baseline is allowed only when asked for."""
    engine = fit_baselines_from_window_history(_history(5))
    fit_end = engine.get_baseline("m_1", "A.txn_rate", "5m", HOW).fit_period_end
    early = fit_end - timedelta(days=1)

    with pytest.raises(BaselineLeak):
        engine.compute_deviation_twin("m_1", "A.txn_rate", 50.0, "5m", HOW, window_end=early)

    permissive = engine.with_in_fit_period_use(True)
    dev, _ = permissive.compute_deviation_twin("m_1", "A.txn_rate", 50.0, "5m", HOW, window_end=early)
    assert isinstance(dev, float)
    # The strict engine must not have been mutated by creating the permissive view.
    assert engine.allow_in_fit_period_use is False


def test_feature_engine_arms_the_guard():
    """The guard must be live through the real feature path, not only direct calls."""
    engine = fit_baselines_from_window_history(_history(5))
    fit_end = engine.get_baseline("m_1", "A.txn_rate", "5m", HOW).fit_period_end
    feature_engine = FeatureEngine(baseline_engine=engine)

    # Exactly one week earlier: same hour-of-week slot (so the fitted profile is the one
    # looked up), but inside the fit period — which is precisely the leak case.
    with pytest.raises(BaselineLeak):
        feature_engine.extract_window_features(
            merchant_id="m_1",
            window_size=WindowSize.M5,
            window_end=fit_end - timedelta(days=7),
            transactions=[],
        )


def test_unknown_fit_period_skips_the_guard_rather_than_guessing():
    """Hand-built profiles (no recorded fit period) must not raise."""
    engine = BaselineEngine(
        merchant_baselines={
            KEY: BaselineProfile(
                expected_median=10.0,
                variability_mad=2.0,
                sample_count=30,
                confidence=BaselineConfidence.HIGH,
            )
        }
    )
    dev, _ = engine.compute_deviation_twin(
        "m_1", "A.txn_rate", 20.0, "5m", HOW, window_end=datetime(2020, 1, 1, tzinfo=UTC)
    )
    assert dev == pytest.approx((20.0 - 10.0) / 2.0)


# ---------------------------------------------------------------- real transformation


def test_fitted_baseline_actually_changes_the_feature_value():
    """Regression test for the defect this work fixes.

    With an unfitted engine every `_dev` twin equals its raw feature, which is what made
    the whole component inert. A fitted engine must produce something different.
    """
    unfitted = BaselineEngine()
    raw_dev, _ = unfitted.compute_deviation_twin("m_1", "A.txn_rate", 137.0, "5m", HOW)
    assert raw_dev == 137.0, "unfitted engine should pass the raw value through"

    fitted = fit_baselines_from_window_history(_history(20, value=10.0))
    fit_end = fitted.get_baseline("m_1", "A.txn_rate", "5m", HOW).fit_period_end
    fitted_dev, conf = fitted.compute_deviation_twin(
        "m_1", "A.txn_rate", 137.0, "5m", HOW, window_end=fit_end + timedelta(days=1)
    )
    assert fitted_dev != 137.0
    assert conf is BaselineConfidence.HIGH


def test_persistence_round_trip_preserves_the_fit_period():
    """The guard must survive a trip through `baseline_store`."""
    from app.models.entities import BaselineStoreRow

    fitted = fit_baselines_from_window_history(_history(6))
    profile = fitted.get_baseline("m_1", "A.txn_rate", "5m", HOW)

    row = BaselineStoreRow(
        id="b1",
        merchant_id="m_1",
        feature_id="A.txn_rate",
        window_size="5m",
        hour_of_week=HOW,
        version=1,
        expected_median=profile.expected_median,
        variability_mad=profile.variability_mad,
        sample_count=profile.sample_count,
        confidence=profile.confidence.value,
        fit_period_start=profile.fit_period_start,
        fit_period_end=profile.fit_period_end,
    )

    reloaded = build_baseline_engine_from_rows([row])
    reloaded_profile = reloaded.get_baseline("m_1", "A.txn_rate", "5m", HOW)
    assert reloaded_profile.expected_median == pytest.approx(profile.expected_median)
    assert reloaded_profile.fit_period_end == profile.fit_period_end
    assert reloaded.allow_in_fit_period_use is False

    with pytest.raises(BaselineLeak):
        reloaded.compute_deviation_twin(
            "m_1", "A.txn_rate", 5.0, "5m", HOW,
            window_end=profile.fit_period_end - timedelta(days=1),
        )


# ---------------------------------------------------------------- pipeline integration


def test_evaluation_runner_fits_baselines_on_train_only():
    """Integration guard: the runner must fit, freeze, and apply — not skip the step."""
    import inspect

    from app.evaluation import runner

    src = inspect.getsource(runner)
    assert "fit_baselines_from_window_history(" in src, "runner no longer fits baselines"
    assert "with_in_fit_period_use(True)" in src, "runner no longer distinguishes in-sample TRAIN use"
    # VAL/TEST must be extracted with the strict engine.
    assert "extract_split_features(val_labels, scoring_engine)" in src
    assert "extract_split_features(test_labels, scoring_engine)" in src


def test_scoring_service_loads_persisted_baselines_by_default():
    from app.serving.scoring_service import ScoringService

    service = ScoringService()
    assert service.load_persisted_baselines is True
    assert service.feature_engine is None

    injected = FeatureEngine()
    explicit = ScoringService(feature_engine=injected)
    assert explicit.load_persisted_baselines is False
    assert explicit.feature_engine is injected


@pytest.mark.asyncio
async def test_scoring_service_uses_baselines_from_the_store():
    """End-to-end: persisted baselines must reach the feature engine used for scoring."""
    from app.core.db import session_scope
    from app.models.repositories import BaselineStoreRepository
    from app.serving.scoring_service import ScoringService

    merchant_id = "m_baseline_integration_test"
    fit_end = datetime(2026, 3, 1, 0, 0, tzinfo=UTC)

    async with session_scope() as session:
        await BaselineStoreRepository.save_baseline(
            session=session,
            merchant_id=merchant_id,
            feature_id="A.txn_rate",
            window_size="5m",
            hour_of_week=HOW,
            expected_median=12.0,
            variability_mad=3.0,
            sample_count=40,
            confidence=BaselineConfidence.HIGH,
            fit_period_start=fit_end - timedelta(days=7),
            fit_period_end=fit_end,
        )

    service = ScoringService()
    async with session_scope() as session:
        engine = await service._resolve_feature_engine(session, merchant_id)
        assert engine.baseline_engine.is_fitted, "persisted baselines were not loaded"
        profile = engine.baseline_engine.get_baseline(merchant_id, "A.txn_rate", "5m", 0)
        assert profile.expected_median == pytest.approx(12.0)
        assert profile.fit_period_end == fit_end

        # A merchant with no fitted history must still score (cold start), not fail.
        cold = await service._resolve_feature_engine(session, "m_never_fitted_at_all")
        assert cold.baseline_engine.is_fitted is False
