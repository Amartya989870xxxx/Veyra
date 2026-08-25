"""Deterministic rule pack.

This serves two roles at once, and it is worth being explicit about both:

1. **Baseline 1** in the evaluation (PRD §22) — the "static rules" detector Veyra must beat.
2. The ``rule_violation_score`` component inside Veyra's own fusion.

Thresholds below are declared placeholders. They are swept on validation data by the
evaluation runner, never hand-tuned against the holdout. Each rule carries a weight; the
score is the bounded weighted sum, so a single rule can never on its own claim certainty.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.versions import RULES_VERSION
from app.schemas.enums import Severity

# Placeholder thresholds. Swept on validation; see reports/evaluation_report.md.
DEFAULT_THRESHOLDS = {
    "customer_velocity_60s": 5.0,
    "shared_device_customers": 3.0,
    "coupon_customer_concentration": 5.0,
    "retry_count": 3.0,
    "amount_vs_category_median": 8.0,
    "agent_payments_per_minute": 20.0,
    "agent_distinct_customers": 5.0,
    "cluster_failure_rate": 0.5,
    "instruments_per_customer": 3.0,
    "customers_per_device": 4.0,
    "scripted_cadence_cv": 0.12,
    "min_cluster_size": 5.0,
}


@dataclass(frozen=True)
class Rule:
    code: str
    feature: str
    threshold_key: str
    comparison: str  # "gt" or "lt"
    weight: float
    severity: Severity
    description: str
    expected: float | None = None
    requires_cluster: bool = False


RULES: list[Rule] = [
    Rule("velocity_burst", "tmp_customer_events_60s", "customer_velocity_60s", "gt", 0.10,
         Severity.MEDIUM, "customer transaction velocity in the last 60s", expected=1.0),
    Rule("shared_device_cluster", "graph_device_customer_degree", "shared_device_customers",
         "gt", 0.18, Severity.HIGH, "distinct customer accounts on this device", expected=1.0),
    Rule("coupon_concentration", "graph_coupon_customer_degree",
         "coupon_customer_concentration", "gt", 0.16, Severity.HIGH,
         "distinct accounts redeeming this coupon in-window", expected=1.0),
    Rule("retry_burst", "txn_retry_count", "retry_count", "gt", 0.10, Severity.MEDIUM,
         "payment retry count on this transaction", expected=0.0),
    Rule("amount_outlier", "txn_amount_ratio_category_median", "amount_vs_category_median",
         "gt", 0.08, Severity.LOW, "amount relative to the category median", expected=1.0),
    Rule("agent_payment_rate", "beh_payments_per_minute", "agent_payments_per_minute", "gt",
         0.12, Severity.MEDIUM, "payment requests per minute in this agent session",
         expected=2.0),
    Rule("agent_multi_account", "beh_agent_distinct_customers", "agent_distinct_customers",
         "gt", 0.16, Severity.HIGH, "distinct customer accounts driven by this agent",
         expected=1.0),
    Rule("cluster_failure_rate", "graph_cluster_failure_rate", "cluster_failure_rate", "gt",
         0.12, Severity.MEDIUM, "share of failed payments in the surrounding cluster",
         expected=0.05, requires_cluster=True),
    Rule("instrument_fan_out", "graph_instruments_per_customer", "instruments_per_customer",
         "gt", 0.14, Severity.HIGH, "distinct payment instruments per account in-cluster",
         expected=1.0),
    Rule("device_farm", "graph_customers_per_device", "customers_per_device", "gt", 0.18,
         Severity.HIGH, "accounts per device in the surrounding cluster", expected=1.0,
         requires_cluster=True),
    Rule("scripted_cadence", "graph_cluster_interarrival_cv", "scripted_cadence_cv", "lt",
         0.14, Severity.HIGH,
         "interarrival coefficient of variation in-cluster (low means metronomic)",
         expected=0.5, requires_cluster=True),
]

# A hard authorization breach is not a scored rule: it is a policy matter handled by the
# decision engine, which can bypass thresholds entirely.
HARD_VIOLATION_FEATURE = "auth_hard_violation"


@dataclass
class RuleHit:
    code: str
    description: str
    observed_value: float
    threshold: float
    expected_value: float | None
    severity: Severity
    weight: float


@dataclass
class RuleResult:
    score: float
    hits: list[RuleHit]
    version: str = RULES_VERSION

    @property
    def codes(self) -> list[str]:
        return [h.code for h in self.hits]


class RuleEngine:
    """Evaluates the rule pack against a feature snapshot."""

    version = RULES_VERSION

    def __init__(self, thresholds: dict[str, float] | None = None) -> None:
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}

    def evaluate(self, features: dict[str, float]) -> RuleResult:
        hits: list[RuleHit] = []
        cluster_size = features.get("graph_cluster_size", 0.0)
        min_cluster = self.thresholds["min_cluster_size"]

        for rule in RULES:
            if rule.requires_cluster and cluster_size < min_cluster:
                # Cluster-shaped rules are meaningless on a cluster of one. Skipping is
                # not the same as passing, and it keeps a lone transaction from being
                # scored on a "0% failure rate" that reflects nothing.
                continue
            observed = features.get(rule.feature)
            if observed is None:
                continue
            threshold = self.thresholds[rule.threshold_key]
            fired = observed > threshold if rule.comparison == "gt" else observed < threshold
            if fired:
                hits.append(
                    RuleHit(
                        code=rule.code,
                        description=rule.description,
                        observed_value=float(observed),
                        threshold=threshold,
                        expected_value=rule.expected,
                        severity=rule.severity,
                        weight=rule.weight,
                    )
                )

        raw = sum(h.weight for h in hits)
        # Saturating rather than linear: ten weak rules should not outrank one decisive one,
        # and the score must stay in [0, 1] to be fusable with calibrated probabilities.
        score = min(1.0, raw)
        if features.get(HARD_VIOLATION_FEATURE, 0.0) >= 1.0:
            score = max(score, 0.85)
        return RuleResult(score=score, hits=hits)


def default_rule_engine() -> RuleEngine:
    return RuleEngine()
