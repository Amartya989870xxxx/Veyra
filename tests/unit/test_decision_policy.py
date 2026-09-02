"""Unit tests for decision policies and operating point optimization (Phase 4.2 & ADR-006)."""

from __future__ import annotations

import pytest

from app.decision.operating_point import OperatingThresholds, choose_operating_thresholds
from app.decision.policy import DecisionPolicy
from app.schemas.enums import ActionTier


def test_choose_operating_thresholds_minimizes_loss():
    """Verify operating point selector chooses thresholds respecting capacity cap."""
    y_true = [0] * 80 + [1] * 20
    # True negatives get low probs, true positives get high probs
    y_prob = [0.05 + (i % 10) * 0.02 for i in range(80)] + [0.80 + (i % 10) * 0.015 for i in range(20)]

    thresholds = choose_operating_thresholds(
        y_true=y_true,
        y_prob=y_prob,
        review_capacity_cap=0.25,
        fp_cost_review=200.0,
    )

    assert 0.10 <= thresholds.theta_alert < thresholds.theta_review
    assert thresholds.theta_review < thresholds.theta_restrict <= 0.95
    assert thresholds.review_rate <= 0.25


def test_decision_policy_four_tiers():
    """Verify 4-tier decision mapping (OBSERVE, ALERT, REVIEW, RESTRICT)."""
    thresholds = OperatingThresholds(
        theta_alert=0.30,
        theta_review=0.60,
        theta_restrict=0.85,
    )
    policy = DecisionPolicy(thresholds=thresholds)

    # 1. Below alert threshold -> OBSERVE
    d_obs = policy.evaluate(0.15)
    assert d_obs.action_tier is ActionTier.OBSERVE

    # 2. Between alert and review -> ALERT
    d_alt = policy.evaluate(0.45)
    assert d_alt.action_tier is ActionTier.ALERT

    # 3. Between review and restrict -> REVIEW
    d_rev = policy.evaluate(0.70)
    assert d_rev.action_tier is ActionTier.REVIEW

    # 4. Exceeding restrict threshold -> RESTRICT
    d_res = policy.evaluate(0.92, dominant_scenario="card_testing_burst")
    assert d_res.action_tier is ActionTier.RESTRICT
    assert d_res.recommended_defensive_control == "RECOMMEND_INSTRUMENT_VELOCITY_CAP"
