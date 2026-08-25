"""Evidence construction.

Every decision must be explainable from structured evidence alone (PRD §18). Two rules
shape this module:

* **Evidence cuts both ways.** A flash-sale burst and a device farm both trip velocity
  signals. What separates them is the *mitigating* evidence — jittered arrivals, one device
  per account, real browsing before payment. Emitting only aggravating signals would make
  every hard negative look damning and give an analyst no way to clear it.
* **No hidden reasoning.** Observations are computed from named features with stated
  observed and expected values. Nothing here reports model internals.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.features.engine import FeatureSnapshot
from app.risk.rules import RuleResult
from app.schemas.enums import EvidenceDirection, Severity, SignalSource
from app.schemas.risk import RiskEvidence

MAX_EVIDENCE_ITEMS = 14

_SEVERITY_RANK = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}


@dataclass(frozen=True)
class Observation:
    """A declarative evidence rule: fire when ``feature`` crosses ``threshold``."""

    signal: str
    feature: str
    threshold: float
    comparison: str
    severity: Severity
    source: SignalSource
    direction: EvidenceDirection
    template: str
    expected: float | None = None
    requires: tuple[tuple[str, str, float], ...] = ()


AGGRAVATING: list[Observation] = [
    Observation(
        "shared_device_cluster", "graph_device_customer_degree", 3, "gt", Severity.HIGH,
        SignalSource.GRAPH_ENGINE, EvidenceDirection.INCREASES_RISK,
        "{value:.0f} customer accounts share this device fingerprint in the current window",
        expected=1.0,
    ),
    Observation(
        "shared_network_cluster", "graph_network_customer_degree", 6, "gt", Severity.MEDIUM,
        SignalSource.GRAPH_ENGINE, EvidenceDirection.INCREASES_RISK,
        "{value:.0f} customer accounts share this network fingerprint", expected=1.0,
    ),
    Observation(
        "coupon_concentration", "graph_coupon_customer_degree", 5, "gt", Severity.HIGH,
        SignalSource.GRAPH_ENGINE, EvidenceDirection.INCREASES_RISK,
        "the same coupon was redeemed across {value:.0f} distinct accounts in-window",
        expected=1.0,
    ),
    Observation(
        "sku_targeting", "graph_sku_customer_degree", 8, "gt", Severity.MEDIUM,
        SignalSource.GRAPH_ENGINE, EvidenceDirection.INCREASES_RISK,
        "{value:.0f} distinct accounts targeted the same SKU in-window", expected=1.0,
    ),
    Observation(
        "device_account_farm", "graph_customers_per_device", 4, "gt", Severity.HIGH,
        SignalSource.GRAPH_ENGINE, EvidenceDirection.INCREASES_RISK,
        "the surrounding cluster averages {value:.1f} accounts per device", expected=1.0,
        requires=(("graph_cluster_size", "gt", 4),),
    ),
    Observation(
        "instrument_fan_out", "graph_instruments_per_customer", 2.5, "gt", Severity.HIGH,
        SignalSource.GRAPH_ENGINE, EvidenceDirection.INCREASES_RISK,
        "{value:.1f} distinct payment instruments per account in the cluster", expected=1.0,
        requires=(("graph_cluster_size", "gt", 4),),
    ),
    Observation(
        "action_sequence_similarity", "graph_cluster_sequence_similarity", 0.7, "gt",
        Severity.HIGH, SignalSource.GRAPH_ENGINE, EvidenceDirection.INCREASES_RISK,
        "{value:.0%} of sessions in the cluster replay an identical action sequence",
        expected=0.2, requires=(("graph_cluster_size", "gt", 4),),
    ),
    Observation(
        "scripted_cluster_cadence", "graph_cluster_interarrival_cv", 0.15, "lt", Severity.HIGH,
        SignalSource.TEMPORAL_ENGINE, EvidenceDirection.INCREASES_RISK,
        "cluster arrivals are near-metronomic (interarrival CoV {value:.2f}), which is "
        "characteristic of a scheduler rather than a crowd",
        expected=0.5, requires=(("graph_cluster_size", "gt", 4),),
    ),
    Observation(
        "cluster_failure_rate", "graph_cluster_failure_rate", 0.5, "gt", Severity.MEDIUM,
        SignalSource.GRAPH_ENGINE, EvidenceDirection.INCREASES_RISK,
        "{value:.0%} of transactions in the surrounding cluster failed", expected=0.05,
        requires=(("graph_cluster_size", "gt", 4),),
    ),
    Observation(
        "scripted_session_cadence", "beh_action_gap_cv", 0.12, "lt", Severity.MEDIUM,
        SignalSource.BEHAVIOR_ENGINE, EvidenceDirection.INCREASES_RISK,
        "agent actions arrive on a near-constant interval (CoV {value:.2f})", expected=0.5,
        requires=(("beh_actions_in_session", "gt", 4),),
    ),
    Observation(
        "payment_heavy_trajectory", "beh_payment_action_ratio", 0.6, "gt", Severity.MEDIUM,
        SignalSource.BEHAVIOR_ENGINE, EvidenceDirection.INCREASES_RISK,
        "{value:.0%} of this session's actions are payment requests, with little discovery "
        "activity beforehand", expected=0.2,
        requires=(("beh_actions_in_session", "gt", 2),),
    ),
    Observation(
        "agent_multi_account", "beh_agent_distinct_customers", 5, "gt", Severity.HIGH,
        SignalSource.BEHAVIOR_ENGINE, EvidenceDirection.INCREASES_RISK,
        "this agent has transacted for {value:.0f} distinct customer accounts", expected=1.0,
    ),
    Observation(
        "retry_burst", "txn_retry_count", 3, "gt", Severity.MEDIUM,
        SignalSource.TRANSACTION_ENGINE, EvidenceDirection.INCREASES_RISK,
        "the payment has been retried {value:.0f} times", expected=0.0,
    ),
    Observation(
        "customer_velocity", "tmp_customer_events_60s", 5, "gt", Severity.MEDIUM,
        SignalSource.TEMPORAL_ENGINE, EvidenceDirection.INCREASES_RISK,
        "{value:.0f} transactions from this customer in the last 60 seconds", expected=1.0,
    ),
    Observation(
        "amount_outlier", "txn_amount_ratio_customer_mean", 6, "gt", Severity.MEDIUM,
        SignalSource.TRANSACTION_ENGINE, EvidenceDirection.INCREASES_RISK,
        "amount is {value:.1f}x this customer's historical average", expected=1.0,
        requires=(("txn_customer_txn_count_log", "gt", 1.0),),
    ),
]

MITIGATING: list[Observation] = [
    Observation(
        "organic_arrival_jitter", "graph_cluster_interarrival_cv", 0.45, "gt", Severity.INFO,
        SignalSource.TEMPORAL_ENGINE, EvidenceDirection.DECREASES_RISK,
        "arrivals in this cluster are irregularly spaced (interarrival CoV {value:.2f}), "
        "consistent with independent buyers rather than a script",
        expected=0.5, requires=(("graph_cluster_size", "gt", 4),),
    ),
    Observation(
        "device_diversity", "graph_customers_per_device", 1.3, "lt", Severity.INFO,
        SignalSource.GRAPH_ENGINE, EvidenceDirection.DECREASES_RISK,
        "each account in the cluster uses its own device ({value:.1f} accounts per device)",
        expected=1.0, requires=(("graph_cluster_size", "gt", 4),),
    ),
    Observation(
        "discovery_trajectory_present", "beh_browse_ratio", 0.5, "gt", Severity.INFO,
        SignalSource.BEHAVIOR_ENGINE, EvidenceDirection.DECREASES_RISK,
        "{value:.0%} of the agent's actions were search/compare/browse steps before payment",
        expected=0.4, requires=(("beh_actions_in_session", "gt", 3),),
    ),
    Observation(
        "sequence_diversity", "graph_cluster_sequence_similarity", 0.4, "lt", Severity.INFO,
        SignalSource.GRAPH_ENGINE, EvidenceDirection.DECREASES_RISK,
        "sessions in the cluster follow varied action sequences ({value:.0%} share the modal "
        "sequence)", expected=0.2, requires=(("graph_cluster_size", "gt", 4),),
    ),
    Observation(
        "established_customer", "txn_customer_txn_count_log", 2.0, "gt", Severity.INFO,
        SignalSource.TRANSACTION_ENGINE, EvidenceDirection.DECREASES_RISK,
        "this customer has an established transaction history with the merchant set",
        expected=0.0,
    ),
    Observation(
        "low_cluster_failure_rate", "graph_cluster_failure_rate", 0.1, "lt", Severity.INFO,
        SignalSource.GRAPH_ENGINE, EvidenceDirection.DECREASES_RISK,
        "payments in the surrounding cluster are succeeding normally ({value:.0%} failure rate)",
        expected=0.05, requires=(("graph_cluster_size", "gt", 4),),
    ),
]


def _fires(features: dict[str, float], obs: Observation) -> bool:
    for name, comparison, threshold in obs.requires:
        value = features.get(name)
        if value is None:
            return False
        if comparison == "gt" and not value > threshold:
            return False
        if comparison == "lt" and not value < threshold:
            return False
    value = features.get(obs.feature)
    if value is None:
        return False
    return value > obs.threshold if obs.comparison == "gt" else value < obs.threshold


def observation_evidence(features: dict[str, float]) -> list[RiskEvidence]:
    evidence: list[RiskEvidence] = []
    for obs in (*AGGRAVATING, *MITIGATING):
        if not _fires(features, obs):
            continue
        value = features[obs.feature]
        evidence.append(
            RiskEvidence(
                signal=obs.signal,
                observed=obs.template.format(value=value),
                observed_value=round(float(value), 4),
                expected_value=obs.expected,
                severity=obs.severity,
                source=obs.source,
                direction=obs.direction,
            )
        )
    return evidence


def rule_evidence(rules: RuleResult) -> list[RiskEvidence]:
    return [
        RiskEvidence(
            signal=f"rule_{hit.code}",
            observed=(
                f"{hit.description}: observed {hit.observed_value:.2f} against threshold "
                f"{hit.threshold:.2f}"
            ),
            observed_value=round(hit.observed_value, 4),
            expected_value=hit.expected_value,
            severity=hit.severity,
            source=SignalSource.RULE_ENGINE,
            direction=EvidenceDirection.INCREASES_RISK,
            contribution=hit.weight,
        )
        for hit in rules.hits
    ]


def component_evidence(
    contributions: dict[str, float], scores: dict[str, float | None]
) -> list[RiskEvidence]:
    """One line per component: its score and its signed contribution to the fused logit."""
    evidence: list[RiskEvidence] = []
    for name, score in scores.items():
        if score is None:
            continue
        contribution = contributions.get(name, 0.0)
        evidence.append(
            RiskEvidence(
                signal=f"component_{name}",
                observed=f"{name.replace('_', ' ')} scored {score:.3f}",
                observed_value=round(float(score), 4),
                severity=(
                    Severity.HIGH if score >= 0.7
                    else Severity.MEDIUM if score >= 0.45
                    else Severity.INFO
                ),
                source=SignalSource.POLICY_ENGINE,
                direction=(
                    EvidenceDirection.INCREASES_RISK if contribution > 0
                    else EvidenceDirection.DECREASES_RISK if contribution < 0
                    else EvidenceDirection.NEUTRAL
                ),
                contribution=round(float(contribution), 4),
            )
        )
    return evidence


def rank_and_trim(evidence: list[RiskEvidence], limit: int = MAX_EVIDENCE_ITEMS) -> list[RiskEvidence]:
    """Most severe first, de-duplicated by signal, with at least some mitigating evidence kept.

    Trimming purely by severity would drop every mitigating item, since mitigating evidence
    is INFO by nature — and an analyst reviewing a hard negative needs exactly those lines.
    """
    seen: set[str] = set()
    unique: list[RiskEvidence] = []
    for item in evidence:
        if item.signal in seen:
            continue
        seen.add(item.signal)
        unique.append(item)

    aggravating = [e for e in unique if e.direction != EvidenceDirection.DECREASES_RISK]
    mitigating = [e for e in unique if e.direction == EvidenceDirection.DECREASES_RISK]
    aggravating.sort(key=lambda e: (_SEVERITY_RANK[e.severity], -(e.contribution or 0)))

    reserved = min(len(mitigating), max(2, limit // 4))
    kept = aggravating[: limit - reserved] + mitigating[:reserved]
    kept.sort(key=lambda e: (_SEVERITY_RANK[e.severity], e.signal))
    return kept


def build_snapshot_evidence(snapshot: FeatureSnapshot, rules: RuleResult) -> list[RiskEvidence]:
    return observation_evidence(snapshot.values) + rule_evidence(rules)
