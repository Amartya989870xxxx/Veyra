"""Deterministic decision policy — the safety boundary.

No model output reaches an action without passing through here. The policy is a pure
function of (score, hard violations, component health), it is versioned, and it is the
only place ``ALLOW``/``REVIEW``/``BLOCK`` is decided.

Thresholds start as the PRD's placeholders and are replaced by values chosen on the
**validation** split via expected-loss minimisation. The holdout never influences them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.versions import POLICY_VERSION
from app.features.authorization import AuthorizationViolation
from app.schemas.enums import ComponentStatus, Decision, DecisionStatus
from app.schemas.risk import ComponentHealth, ComponentScores

# PRD §14 Layer E placeholders. Overridden by tuned values from the evaluation runner.
DEFAULT_REVIEW_THRESHOLD = 0.45
DEFAULT_BLOCK_THRESHOLD = 0.75

# Violations severe enough to bypass the score entirely. Each is a breach of an explicit,
# customer-granted constraint, not a statistical judgement — which is exactly why a model
# score should not be able to wave it through.
BLOCKING_VIOLATIONS = {
    "delegation_expired",
    "delegation_not_yet_valid",
    "forbidden_category",
    "customer_mismatch",
    "agent_mismatch",
}

# Components without which a BLOCK is not defensible. If these are unavailable we may still
# ALLOW a clearly-safe transaction, but we will not block on a partial picture.
BLOCK_CRITICAL_COMPONENTS = {"transaction_risk", "campaign_risk"}


@dataclass
class PolicyDecision:
    decision: Decision
    status: DecisionStatus
    reason_code: str
    rationale: str
    review_threshold: float
    block_threshold: float
    policy_version: str = POLICY_VERSION
    bypassed_score: bool = False
    degraded_components: list[str] = field(default_factory=list)


class DecisionPolicy:
    def __init__(
        self,
        review_threshold: float = DEFAULT_REVIEW_THRESHOLD,
        block_threshold: float = DEFAULT_BLOCK_THRESHOLD,
        version: str = POLICY_VERSION,
    ) -> None:
        if not 0.0 <= review_threshold <= block_threshold <= 1.0:
            raise ValueError("thresholds must satisfy 0 <= review <= block <= 1")
        self.review_threshold = review_threshold
        self.block_threshold = block_threshold
        self.version = version

    def decide(
        self,
        risk_score: float,
        *,
        violations: list[AuthorizationViolation] | None = None,
        scores: ComponentScores | None = None,
        component_health: list[ComponentHealth] | None = None,
    ) -> PolicyDecision:
        violations = violations or []
        component_health = component_health or []
        degraded = [
            h.component
            for h in component_health
            if h.status in (ComponentStatus.DEGRADED, ComponentStatus.UNAVAILABLE)
        ]
        status = DecisionStatus.DEGRADED if degraded else DecisionStatus.OK

        # 1. Hard authorization breaches bypass the score in both directions: they cannot be
        #    argued down by a low model score, and they do not need a high one.
        blocking = [v for v in violations if v.code in BLOCKING_VIOLATIONS and v.hard]
        if blocking:
            codes = ", ".join(sorted({v.code for v in blocking}))
            return PolicyDecision(
                decision=Decision.BLOCK,
                status=status,
                reason_code="hard_authorization_violation",
                rationale=(
                    f"Blocked on an explicit authorization breach ({codes}). This is a "
                    "deterministic policy decision and does not depend on the risk score."
                ),
                review_threshold=self.review_threshold,
                block_threshold=self.block_threshold,
                policy_version=self.version,
                bypassed_score=True,
                degraded_components=degraded,
            )

        # 2. No component produced a score at all. There is nothing to threshold, so the
        #    only honest outcome is human review.
        if scores is not None and not scores.available():
            return PolicyDecision(
                decision=Decision.REVIEW,
                status=DecisionStatus.DEGRADED,
                reason_code="no_scoreable_components",
                rationale=(
                    "No risk component produced a usable score, so no risk assessment was "
                    "possible. Routed to manual review rather than assuming a value."
                ),
                review_threshold=self.review_threshold,
                block_threshold=self.block_threshold,
                policy_version=self.version,
                degraded_components=degraded or ["all_components"],
            )

        # 3. Score-driven bands.
        if risk_score >= self.block_threshold:
            missing = (
                BLOCK_CRITICAL_COMPONENTS - set(scores.available()) if scores else set()
            )
            if missing:
                # High score, incomplete evidence. Downgrade to review: blocking a paying
                # customer on a partial picture is the expensive kind of wrong.
                return PolicyDecision(
                    decision=Decision.REVIEW,
                    status=DecisionStatus.DEGRADED,
                    reason_code="block_downgraded_degraded_components",
                    rationale=(
                        f"Risk score {risk_score:.3f} is above the block threshold "
                        f"{self.block_threshold:.2f}, but {sorted(missing)} were unavailable. "
                        "Downgraded to review rather than blocking on partial evidence."
                    ),
                    review_threshold=self.review_threshold,
                    block_threshold=self.block_threshold,
                    policy_version=self.version,
                    degraded_components=degraded or sorted(missing),
                )
            return PolicyDecision(
                decision=Decision.BLOCK,
                status=status,
                reason_code="risk_above_block_threshold",
                rationale=(
                    f"Risk score {risk_score:.3f} is at or above the block threshold "
                    f"{self.block_threshold:.2f}."
                ),
                review_threshold=self.review_threshold,
                block_threshold=self.block_threshold,
                policy_version=self.version,
                degraded_components=degraded,
            )

        if risk_score >= self.review_threshold:
            return PolicyDecision(
                decision=Decision.REVIEW,
                status=status,
                reason_code="risk_in_review_band",
                rationale=(
                    f"Risk score {risk_score:.3f} falls between the review threshold "
                    f"{self.review_threshold:.2f} and the block threshold "
                    f"{self.block_threshold:.2f}."
                ),
                review_threshold=self.review_threshold,
                block_threshold=self.block_threshold,
                policy_version=self.version,
                degraded_components=degraded,
            )

        return PolicyDecision(
            decision=Decision.ALLOW,
            status=status,
            reason_code="risk_below_review_threshold",
            rationale=(
                f"Risk score {risk_score:.3f} is below the review threshold "
                f"{self.review_threshold:.2f} and no hard authorization constraint was breached."
            ),
            review_threshold=self.review_threshold,
            block_threshold=self.block_threshold,
            policy_version=self.version,
            degraded_components=degraded,
        )


def default_policy() -> DecisionPolicy:
    return DecisionPolicy()
