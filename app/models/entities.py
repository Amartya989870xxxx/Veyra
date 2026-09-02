"""Database models for the six purpose-built storage layers (Phase 1.4).

Each store has a distinct lifecycle, mutability, and retention policy:
1. `raw_events`: Immutable, append-only store for canonical normalized events.
2. `feature_store`: Window aggregates keyed on `(merchant_id, window_size, window_end)`.
3. `baseline_store`: Versioned expected behavioral statistics (median & MAD) per merchant.
4. `relationship_store`: Graph engine persistence with TTL'd entity-pair counters.
5. `incident_store`: First-class incident lifecycle, exposure, and evidence.
6. `eval_store`: Predictions, ground truth, and run metadata for reproducible evaluation.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, Money, UtcDateTime, id_column, utcnow
from app.schemas.enums import (
    ActionTier,
    BaselineConfidence,
    IncidentStatus,
    Severity,
    SplitName,
    WindowLabel,
)


class RawEventRow(Base):
    """1. `raw_events`: Append-only immutable log of every ingested event."""

    __tablename__ = "raw_events"

    event_id: Mapped[str] = id_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="synthetic")
    timestamp: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    merchant_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONType, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)


class FeatureStoreRow(Base):
    """2. `feature_store`: Window-aggregated features keyed by merchant, window size and timestamp."""

    __tablename__ = "feature_store"
    __table_args__ = (
        UniqueConstraint("merchant_id", "window_size", "window_end", name="uq_feature_merchant_window_ts"),
        Index("ix_feature_merchant_ts", "merchant_id", "window_end"),
    )

    id: Mapped[str] = id_column(primary_key=True)
    merchant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    window_size: Mapped[str] = mapped_column(String(16), nullable=False)  # 1m, 5m, 15m, 1h
    window_end: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    features: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    evidence: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)


class BaselineStoreRow(Base):
    """3. `baseline_store`: Versioned expected behavioral baselines and variability per merchant/hour."""

    __tablename__ = "baseline_store"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id", "feature_id", "window_size", "hour_of_week", "version",
            name="uq_baseline_merchant_feature_window_hour_ver",
        ),
        Index("ix_baseline_merchant_lookup", "merchant_id", "window_size", "hour_of_week"),
    )

    id: Mapped[str] = id_column(primary_key=True)
    merchant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    feature_id: Mapped[str] = mapped_column(String(64), nullable=False)
    window_size: Mapped[str] = mapped_column(String(16), nullable=False)
    hour_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 0..167
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    expected_median: Mapped[float] = mapped_column(Float, nullable=False)
    variability_mad: Mapped[float] = mapped_column(Float, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[str] = mapped_column(
        String(16), nullable=False, default=BaselineConfidence.MEDIUM.value
    )
    fit_period_start: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    fit_period_end: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)


class RelationshipStoreRow(Base):
    """4. `relationship_store`: Persistence layer for graph entity connections with TTL support."""

    __tablename__ = "relationship_store"
    __table_args__ = (
        Index("ix_rel_merchant_entity_a", "merchant_id", "entity_type_a", "entity_id_a"),
        Index("ix_rel_merchant_entity_b", "merchant_id", "entity_type_b", "entity_id_b"),
        Index("ix_rel_expires_at", "expires_at"),
    )

    id: Mapped[str] = id_column(primary_key=True)
    merchant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type_a: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id_a: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type_b: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id_b: Mapped[str] = mapped_column(String(128), nullable=False)
    co_occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    window_end: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class IncidentStoreRow(Base):
    """5. `incident_store`: First-class incidents with lifecycle, exposure, and evidence."""

    __tablename__ = "incident_store"
    __table_args__ = (
        Index("ix_incidents_merchant_status", "merchant_id", "status"),
        Index("ix_incidents_timeline", "first_flag_time", "last_flag_time"),
    )

    incident_id: Mapped[str] = id_column(primary_key=True)
    merchant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default=Severity.INFO.value)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=IncidentStatus.OPEN.value)
    action_tier: Mapped[str] = mapped_column(String(16), nullable=False, default=ActionTier.OBSERVE.value)
    first_flag_time: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    last_flag_time: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    window_sizes: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    exposure_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    baseline_confidence: Mapped[str] = mapped_column(
        String(16), nullable=False, default=BaselineConfidence.MEDIUM.value
    )
    evidence: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)


class EvalStoreRow(Base):
    """6. `eval_store`: Predictions, ground truth, and run metadata for reproducible evaluation."""

    __tablename__ = "eval_store"
    __table_args__ = (
        Index("ix_eval_run_split", "run_id", "split"),
        Index("ix_eval_merchant_window", "merchant_id", "window_size", "window_end"),
    )

    eval_id: Mapped[str] = id_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    split: Mapped[str] = mapped_column(String(32), nullable=False, default=SplitName.TEST.value)
    merchant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    window_size: Mapped[str] = mapped_column(String(16), nullable=False)
    window_end: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    detector_name: Mapped[str] = mapped_column(String(64), nullable=False)
    predicted_score: Mapped[float] = mapped_column(Float, nullable=False)
    action_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    ground_truth_label: Mapped[str] = mapped_column(String(32), nullable=False, default=WindowLabel.NORMAL.value)
    scenario_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    loss_incurred: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
