"""Temporal / campaign-timing features (PRD §13.5).

These operate on the past-only ego-neighbourhood: transactions in the recent window that
share an entity with the one being scored. Two things separate a coordinated burst from a
flash-sale crowd — arrival regularity, and how few distinct devices/networks produce the
burst — and both are measured here rather than assumed.
"""

from __future__ import annotations

from datetime import timedelta

from app.features.context import RiskContext
from app.features.util import coefficient_of_variation, gaps, repeat_gap_ratio, safe_div

TEMPORAL_FEATURE_NAMES = [
    "tmp_neighbourhood_size",
    "tmp_events_60s",
    "tmp_events_300s",
    "tmp_customer_events_60s",
    "tmp_customer_events_3600s",
    "tmp_device_events_60s",
    "tmp_network_events_60s",
    "tmp_agent_events_60s",
    "tmp_burst_intensity",
    "tmp_synchronized_events_2s",
    "tmp_interarrival_cv",
    "tmp_interarrival_repeat_ratio",
    "tmp_interarrival_mean",
    "tmp_span_seconds",
    "tmp_failure_rate_window",
    "tmp_retry_rate_window",
    "tmp_amount_similarity",
]


def _count_within(ctx: RiskContext, seconds: int, predicate=None) -> int:
    cutoff = ctx.now - timedelta(seconds=seconds)
    return sum(
        1
        for t in ctx.neighbourhood
        if t.timestamp >= cutoff and (predicate is None or predicate(t))
    )


def temporal_features(ctx: RiskContext) -> dict[str, float]:
    txn = ctx.transaction
    neighbours = ctx.neighbourhood
    features = dict.fromkeys(TEMPORAL_FEATURE_NAMES, 0.0)
    features["tmp_neighbourhood_size"] = float(len(neighbours))

    if not neighbours:
        return features

    timestamps = [t.timestamp for t in neighbours]
    span = max(1e-6, (max(timestamps) - min(timestamps)).total_seconds())
    gap_series = gaps(timestamps)

    events_60 = _count_within(ctx, 60)
    amounts = [t.amount for t in neighbours]
    mean_amount = sum(amounts) / len(amounts)
    # How tightly amounts cluster: scripted runs repeat near-identical values, real crowds
    # buying the same item vary by quantity, taxes and shipping.
    amount_similarity = (
        1.0 - min(1.0, coefficient_of_variation(amounts)) if len(amounts) >= 3 else 0.0
    )

    features.update(
        {
            "tmp_events_60s": float(events_60),
            "tmp_events_300s": float(_count_within(ctx, 300)),
            "tmp_customer_events_60s": float(
                _count_within(ctx, 60, lambda t: t.customer_id == txn.customer_id)
            ),
            "tmp_customer_events_3600s": float(
                _count_within(ctx, 3600, lambda t: t.customer_id == txn.customer_id)
            ),
            "tmp_device_events_60s": float(
                _count_within(ctx, 60, lambda t: t.device_id and t.device_id == txn.device_id)
            ),
            "tmp_network_events_60s": float(
                _count_within(
                    ctx, 60,
                    lambda t: t.network_fingerprint
                    and t.network_fingerprint == txn.network_fingerprint,
                )
            ),
            "tmp_agent_events_60s": float(
                _count_within(ctx, 60, lambda t: t.agent_id and t.agent_id == txn.agent_id)
            ),
            "tmp_burst_intensity": len(neighbours) / span,
            "tmp_synchronized_events_2s": float(
                sum(1 for t in timestamps if abs((ctx.now - t).total_seconds()) <= 2.0)
            ),
            "tmp_interarrival_cv": coefficient_of_variation(gap_series),
            "tmp_interarrival_repeat_ratio": repeat_gap_ratio(gap_series),
            "tmp_interarrival_mean": (
                sum(gap_series) / len(gap_series) if gap_series else 0.0
            ),
            "tmp_span_seconds": span,
            "tmp_failure_rate_window": safe_div(
                sum(1 for t in neighbours if t.status == "FAILED"), len(neighbours)
            ),
            "tmp_retry_rate_window": safe_div(
                sum(1 for t in neighbours if t.retry_count > 0), len(neighbours)
            ),
            "tmp_amount_similarity": amount_similarity,
        }
    )
    return features
