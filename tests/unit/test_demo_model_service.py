"""The demo model's training contract (Part 7, B & C).

These pin the two properties that make the demo path honest: the detector is genuinely
fitted, and it is never fitted on the window it is about to score.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.serving.demo_model_service import (
    TRAINING_DAYS,
    TRAINING_START,
    DemoModelService,
    get_demo_model_service,
)

# The anchor `app/api/v2/demo.py::simulate_scenario` builds every demo window against.
DEMO_WINDOW_ANCHOR = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def service() -> DemoModelService:
    """Module-scoped: fitting costs ~20s and the production code caches it per process
    for exactly the same reason."""
    svc = get_demo_model_service()
    svc.ensure_trained()
    return svc


def test_detector_is_actually_fitted(service: DemoModelService) -> None:
    """B: the demo path scores through a real fitted detector, not a stub."""
    assert service.is_ready
    assert service._detector is not None
    assert service._detector.is_fitted is True
    assert (
        service._detector.feature_names
    ), "a fitted detector must have resolved its feature columns"


def test_training_corpus_ends_before_any_demo_window_begins(service: DemoModelService) -> None:
    """C: training data and scored demo data are separated *by construction*.

    This is the invariant that replaces the offline harness's chronological split on the
    demo path. It holds regardless of what seed a request passes, because the separation
    is temporal rather than probabilistic.
    """
    info = service.info
    assert info.training_window_end <= DEMO_WINDOW_ANCHOR, (
        "the training corpus must end before the earliest demo window anchor"
    )
    # And with real margin, not by a second.
    assert (DEMO_WINDOW_ANCHOR - info.training_window_end).days >= 7


def test_training_corpus_covers_every_hour_of_week_bucket() -> None:
    """Baselines are keyed by hour-of-week. A corpus shorter than a week leaves the demo
    window's own bucket unfitted, which silently collapses every `_dev` twin into a copy
    of its raw feature."""
    assert TRAINING_DAYS >= 7
    assert TRAINING_START.weekday() == 0, "start on a Monday so a 7-day span tiles the week cleanly"


def test_model_is_cached_not_retrained_per_call(service: DemoModelService) -> None:
    """A browser click must not retrain the model."""
    _, trained_first = service.ensure_trained()
    _, trained_second = service.ensure_trained()
    assert trained_first is False, "fixture already trained it"
    assert trained_second is False
    assert service.info.trained_at is not None


def test_scores_are_probabilities(service: DemoModelService) -> None:
    from app.features.engine import FeatureEngine

    empty_vector = FeatureEngine().extract_window_features(
        merchant_id="m_probe",
        window_size=__import__("app.windows", fromlist=["WindowSize"]).WindowSize.M5,
        window_end=DEMO_WINDOW_ANCHOR,
        transactions=[],
    )
    scores = service.score([empty_vector.model_features])
    assert len(scores) == 1
    assert 0.0 <= scores[0] <= 1.0


def test_operating_thresholds_are_fitted_and_ordered(service: DemoModelService) -> None:
    """Regression: the demo's four tiers must all be reachable.

    `choose_operating_thresholds` can return `theta_alert > theta_review` when the
    expected-loss sweep picks a low review threshold, because the alert tier is derived
    as `max(0.15, review - 0.20)`. `DecisionPolicy` checks restrict, then review, then
    alert, so an inverted pair silently removes ALERT from the tier ladder. The demo path
    normalises the ordering in `_monotonic`; this pins that it stays normalised.
    """
    t = service.thresholds
    assert 0.0 < t.theta_alert <= t.theta_review <= t.theta_restrict <= 1.0


def test_monotonic_repairs_inverted_thresholds() -> None:
    from app.decision.operating_point import OperatingThresholds
    from app.serving.demo_model_service import _monotonic

    inverted = OperatingThresholds(theta_alert=0.15, theta_review=0.10, theta_restrict=0.30)
    fixed = _monotonic(inverted)
    assert (fixed.theta_alert, fixed.theta_review, fixed.theta_restrict) == (0.10, 0.15, 0.30)


def test_training_corpus_contains_both_classes(service: DemoModelService) -> None:
    """A single-class corpus cannot fit a classifier at all; the service raises rather
    than silently scoring with a degenerate model."""
    assert service.info.training_positive_windows > 0
    assert service.info.training_windows > service.info.training_positive_windows
