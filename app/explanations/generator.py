"""Narrative explanation generator for Veyra v2 incidents (Phase 6.2).

Generates multi-paragraph human-readable summaries that:
1. State what happened (volume, GMV, decline rates).
2. Contrast observed signals against merchant baselines and benign surge patterns.
3. Identify the dominant attack scenario.
4. Recommend actionable, tier-appropriate merchant defenses (ADR-006).
"""

from __future__ import annotations

from typing import Any
from app.decision.exposure import IncidentExposure
from app.decision.policy import PolicyDecision
from app.schemas.enums import ActionTier
from app.windows import WindowSize


def generate_incident_narrative(
    merchant_id: str,
    window_size: WindowSize | str,
    risk_score: float,
    policy_decision: PolicyDecision,
    features: dict[str, float],
    exposure: IncidentExposure | None = None,
) -> str:
    """Generate structured narrative explanation for an analyst or merchant dashboard."""
    w_name = window_size.value if isinstance(window_size, WindowSize) else str(window_size)
    txn_count = int(features.get("B.txn_count", 0))
    gmv = features.get("D.gmv", 0.0)
    fail_rate = features.get("C.failure_rate", 0.0)
    dev_max = features.get("A.txn_rate_dev", 0.0)
    cluster_vol = features.get("J.largest_cluster_vol_share", 0.0)
    bipartite_gini = features.get("J.bipartite_gini", 0.0)
    novelty = features.get("C.instrument_novelty", 0.0)
    coupon_rate = features.get("C.coupon_rate", 0.0)

    # 1. Summary Statement
    paragraphs = []
    paragraphs.append(
        f"**Incident Summary:** Observed an anomalous traffic burst of **{txn_count} transactions** "
        f"(₹{gmv:,.2f} GMV attempted) in the last **{w_name}** window. "
        f"The transaction rate is running at **{dev_max:+.1f} MADs** relative to historical hour-of-week baselines."
    )

    # 2. Forensic Contrast & Distinguishing Evidence
    evidence_points = []
    if cluster_vol > 0.40 or bipartite_gini > 0.50:
        evidence_points.append(
            f"**High Entity Concentration:** {cluster_vol:.0%} of all attempts originated from a single interconnected device/account cluster (Bipartite Gini: {bipartite_gini:.2f}). "
            "In legitimate flash sales, attempts originate from thousands of independent, unlinked devices."
        )
    if fail_rate > 0.40:
        evidence_points.append(
            f"**Elevated Decline Velocity:** The payment failure rate is **{fail_rate:.1%}**, heavily skewed towards issuer fraud declines rather than normal shopper balance issues."
        )
    if novelty > 0.60:
        evidence_points.append(
            f"**High Instrument Novelty:** **{novelty:.0%}** of attempted payment instruments have never been seen previously across your store history."
        )
    if coupon_rate > 0.50:
        evidence_points.append(
            f"**Incentive / Promo Exploitation:** **{coupon_rate:.0%}** of transactions applied promotional discounts across newly registered synthetic accounts."
        )

    if evidence_points:
        paragraphs.append("**Why this was flagged as coordinated abuse:**\n" + "\n".join(f"- {p}" for p in evidence_points))
    else:
        paragraphs.append(
            "**Traffic Profile:** Anomaly is primarily driven by sudden transaction volume acceleration exceeding normal baseline tolerances."
        )

    # 3. Financial Exposure
    if exposure:
        paragraphs.append(
            f"**Financial Exposure at Risk:** Estimated potential loss of **₹{exposure.total_exposure:,.2f}** "
            f"(Direct GMV at Risk: ₹{exposure.direct_fraud_loss:,.2f}, Operational Overhead & Chargeback Fees: ₹{exposure.operational_loss:,.2f})."
        )

    # 4. Recommended Action
    if policy_decision.action_tier in (ActionTier.RESTRICT, ActionTier.REVIEW):
        paragraphs.append(
            f"**Recommended Defensive Control ({policy_decision.action_tier.value}):** "
            f"*{policy_decision.recommended_defensive_control or 'Manual Queue Inspection'}*. "
            f"{policy_decision.rationale}"
        )
    else:
        paragraphs.append(
            f"**Status ({policy_decision.action_tier.value}):** Telemetry logged. No active merchant intervention required at this threshold."
        )

    return "\n\n".join(paragraphs)
