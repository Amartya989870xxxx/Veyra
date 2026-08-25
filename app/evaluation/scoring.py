"""Offline feature extraction over a benchmark dataset.

One chronological pass over every transaction, using the same
:class:`StreamingContextBuilder` the replay path uses. The neighbourhood of a validation
transaction may legitimately contain training-split traffic — that is what production looks
like — and it is safe because context construction never touches a label. Ground truth is
attached only after the fact, and the group split keeps related episodes together.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from app.core.logging import get_logger
from app.evaluation.dataset import ActionRecord, Dataset, DelegationRecord, TxnRecord
from app.features.baselines import Baselines
from app.features.context import (
    ActionView,
    DelegationView,
    RiskContext,
    StreamingContextBuilder,
    TxnView,
)
from app.features.engine import ALL_FEATURE_NAMES, FeatureEngine

log = get_logger(__name__)


def to_txn_view(record: TxnRecord) -> TxnView:
    return TxnView(
        transaction_id=record.transaction_id,
        merchant_id=record.merchant_id,
        customer_id=record.customer_id,
        agent_id=record.agent_id,
        session_id=record.session_id,
        delegation_id=record.delegation_id,
        amount=float(record.amount),
        currency=record.currency,
        merchant_category=record.merchant_category,
        sku_id=record.sku_id,
        quantity=record.quantity,
        coupon_id=record.coupon_id,
        coupon_value=float(record.coupon_value),
        device_id=record.device_id,
        network_fingerprint=record.network_fingerprint,
        payment_method=record.payment_method,
        instrument_fingerprint=record.instrument_fingerprint,
        retry_count=record.retry_count,
        status=record.status,
        actor_type=record.actor_type,
        timestamp=record.timestamp,
    )


def to_action_view(record: ActionRecord) -> ActionView:
    return ActionView(
        action_id=record.action_id,
        agent_id=record.agent_id,
        session_id=record.session_id,
        sequence_number=record.sequence_number,
        action_type=record.action_type,
        tool_name=record.tool_name,
        timestamp=record.timestamp,
        merchant_id=record.merchant_id,
        sku_id=record.sku_id,
    )


def to_delegation_view(record: DelegationRecord) -> DelegationView:
    return DelegationView(
        delegation_id=record.delegation_id,
        customer_id=record.customer_id,
        agent_id=record.agent_id,
        purpose=record.purpose,
        max_amount=float(record.max_amount),
        currency=record.currency,
        allowed_categories=list(record.allowed_categories),
        forbidden_categories=list(record.forbidden_categories),
        allowed_merchants=list(record.allowed_merchants),
        merchant_policy=record.merchant_policy,
        approval_required_above=(
            float(record.approval_required_above)
            if record.approval_required_above is not None
            else None
        ),
        issued_at=record.issued_at,
        expires_at=record.expires_at,
    )


@dataclass
class FeatureFrame:
    """Extracted features plus aligned ground truth. The unit the evaluator works on."""

    feature_names: list[str]
    matrix: np.ndarray
    labels: np.ndarray
    amounts: np.ndarray
    transaction_ids: list[str] = field(default_factory=list)
    group_ids: list[str] = field(default_factory=list)
    campaign_ids: list[str | None] = field(default_factory=list)
    scenarios: list[str] = field(default_factory=list)
    hard_negatives: np.ndarray | None = None
    label_classes: list[str] = field(default_factory=list)
    violations_by_txn: dict[str, list] = field(default_factory=dict)
    latency_ms: list[float] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.labels)

    def select(self, names: list[str]) -> np.ndarray:
        index = {name: i for i, name in enumerate(self.feature_names)}
        columns = [index[name] for name in names]
        return self.matrix[:, columns]

    def mask(self, indices: np.ndarray | list[int]) -> FeatureFrame:
        indices = np.asarray(indices, dtype=int)
        return FeatureFrame(
            feature_names=self.feature_names,
            matrix=self.matrix[indices],
            labels=self.labels[indices],
            amounts=self.amounts[indices],
            transaction_ids=[self.transaction_ids[i] for i in indices],
            group_ids=[self.group_ids[i] for i in indices],
            campaign_ids=[self.campaign_ids[i] for i in indices],
            scenarios=[self.scenarios[i] for i in indices],
            hard_negatives=(
                self.hard_negatives[indices] if self.hard_negatives is not None else None
            ),
            label_classes=[self.label_classes[i] for i in indices],
            violations_by_txn=self.violations_by_txn,
            latency_ms=[self.latency_ms[i] for i in indices] if self.latency_ms else [],
        )


def extract_features(
    dataset: Dataset,
    baselines: Baselines | None = None,
    window_seconds: int = 900,
    max_neighbours: int = 400,
    progress_every: int = 2500,
) -> FeatureFrame:
    """Single chronological pass producing a feature row per transaction."""
    engine = FeatureEngine(baselines=baselines)
    builder = StreamingContextBuilder(
        window_seconds=window_seconds, max_neighbours=max_neighbours
    )

    rows: list[list[float]] = []
    labels: list[int] = []
    amounts: list[float] = []
    txn_ids: list[str] = []
    group_ids: list[str] = []
    campaign_ids: list[str | None] = []
    scenarios: list[str] = []
    hard_negatives: list[int] = []
    label_classes: list[str] = []
    violations: dict[str, list] = {}
    latencies: list[float] = []

    started = time.perf_counter()
    for index, record in enumerate(dataset.transactions):
        view = to_txn_view(record)
        session_actions_raw = dataset.actions_by_session.get(record.session_id or "", [])
        actions = [to_action_view(a) for a in session_actions_raw]
        delegation = (
            to_delegation_view(dataset.delegations[record.delegation_id])
            if record.delegation_id and record.delegation_id in dataset.delegations
            else None
        )

        ctx: RiskContext = builder.build(view, actions=actions, delegation=delegation)
        # Session action traces for the neighbourhood, used for sequence-similarity.
        ctx.session_actions_by_session = {
            t.session_id: [
                to_action_view(a) for a in dataset.actions_by_session.get(t.session_id, [])
            ]
            for t in (*ctx.neighbourhood, view)
            if t.session_id
        }

        row_start = time.perf_counter()
        snapshot = engine.extract(ctx)
        latencies.append((time.perf_counter() - row_start) * 1000)

        rows.append([snapshot.values.get(name, 0.0) for name in ALL_FEATURE_NAMES])
        labels.append(1 if record.is_abusive else 0)
        amounts.append(float(record.amount))
        txn_ids.append(record.transaction_id)
        group_ids.append(record.group_id)
        campaign_ids.append(record.campaign_id)
        scenarios.append(record.scenario)
        hard_negatives.append(1 if record.hard_negative else 0)
        label_classes.append(record.label_class)
        if snapshot.violations:
            violations[record.transaction_id] = snapshot.violations

        builder.observe(view, actions)

        if progress_every and index and index % progress_every == 0:
            log.info(
                "feature_extraction_progress",
                extra={"processed": index, "elapsed_s": round(time.perf_counter() - started, 1)},
            )

    return FeatureFrame(
        feature_names=list(ALL_FEATURE_NAMES),
        matrix=np.asarray(rows, dtype=float),
        labels=np.asarray(labels, dtype=int),
        amounts=np.asarray(amounts, dtype=float),
        transaction_ids=txn_ids,
        group_ids=group_ids,
        campaign_ids=campaign_ids,
        scenarios=scenarios,
        hard_negatives=np.asarray(hard_negatives, dtype=int),
        label_classes=label_classes,
        violations_by_txn=violations,
        latency_ms=latencies,
    )


def split_frame(frame: FeatureFrame, assignment: dict[str, str]) -> dict[str, FeatureFrame]:
    """Partition an extracted frame using the dataset's group assignment."""
    buckets: dict[str, list[int]] = {"train": [], "validation": [], "holdout": []}
    for i, group_id in enumerate(frame.group_ids):
        buckets[assignment[group_id]].append(i)
    return {name: frame.mask(indices) for name, indices in buckets.items()}
