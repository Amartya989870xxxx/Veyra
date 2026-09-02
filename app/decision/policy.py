"""Four-tier decision policy (Phase 4.2 & ADR-006).

Maps fraud spike probabilities to four actionable operational tiers:
- OBSERVE:  Logged silently for telemetry
- ALERT:    Merchant notification sent
- REVIEW:   Incident queued for human fraud analyst review
- RESTRICT: Recommends defensive control (step-up auth, rate-limit, disable promo).
            Crucially: Does NOT auto-decline live payments.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.decision.operating_point import OperatingThresholds
from app.schemas.enums import ActionTier


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    action_tier: ActionTier
    risk_score: float
    recommended_defensive_control: str | None = None
    rationale: str = ""


class DecisionPolicy:
    """Evaluates incident risk probabilities and assigns action tiers."""

    def __init__(self, thresholds: OperatingThresholds | None = None) -> None:
        self.thresholds = thresholds or OperatingThresholds()

    def evaluate(self, risk_score: float, dominant_scenario: str | None = None) -> PolicyDecision:
        score = float(risk_score)
        t = self.thresholds

        if score >= t.theta_restrict:
            # Recommends defensive control based on scenario
            if dominant_scenario == "card_testing_burst":
                control = "RECOMMEND_INSTRUMENT_VELOCITY_CAP"
                rationale = "Extreme instrument novelty and issuer declines detected. Recommend applying a 5-attempt/minute cap per IP."
            elif dominant_scenario == "promo_coupon_harvesting":
                control = "RECOMMEND_SUSPEND_PROMO_COUPON"
                rationale = "Rapid redemption across new synthetic accounts. Recommend pausing coupon code."
            elif dominant_scenario == "device_farm_ring":
                control = "RECOMMEND_DEVICE_CHALLENGE"
                rationale = "High account concentration on small device cluster. Recommend step-up biometric/2FA."
            else:
                control = "RECOMMEND_STEP_UP_AUTHENTICATION"
                rationale = "High confidence fraud spike. Recommend step-up verification."

            return PolicyDecision(
                action_tier=ActionTier.RESTRICT,
                risk_score=score,
                recommended_defensive_control=control,
                rationale=rationale,
            )

        if score >= t.theta_review:
            return PolicyDecision(
                action_tier=ActionTier.REVIEW,
                risk_score=score,
                recommended_defensive_control=None,
                rationale="Elevated risk score exceeding review threshold. Incident queued for analyst review.",
            )

        if score >= t.theta_alert:
            return PolicyDecision(
                action_tier=ActionTier.ALERT,
                risk_score=score,
                recommended_defensive_control=None,
                rationale="Moderate traffic anomaly detected. Notification sent to merchant dashboard.",
            )

        return PolicyDecision(
            action_tier=ActionTier.OBSERVE,
            risk_score=score,
            recommended_defensive_control=None,
            rationale="Traffic pattern within expected baseline tolerances.",
        )
