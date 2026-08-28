"""ORM models for decisions, evidence, campaigns, cases and evaluation runs.

``risk_decisions`` is append-only and immutable by convention: a re-evaluation writes a
new row rather than mutating an old one, so the audit trail is a complete history.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JSONType, Money, UtcDateTime, id_column, utcnow


class RiskDecisionRow(Base):
    __tablename__ = "risk_decisions"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_risk_decisions_idempotency_key"),
        Index("ix_risk_decisions_txn", "transaction_id"),
        Index("ix_risk_decisions_decided_at", "decided_at"),
    )

    decision_id: Mapped[str] = id_column(primary_key=True)
    transaction_id: Mapped[str] = id_column()
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    merchant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    customer_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    campaign_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    case_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)

    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    transaction_risk: Mapped[float | None] = mapped_column(Float, nullable=True)
    behavior_risk: Mapped[float | None] = mapped_column(Float, nullable=True)
    campaign_risk: Mapped[float | None] = mapped_column(Float, nullable=True)
    intent_deviation: Mapped[float | None] = mapped_column(Float, nullable=True)
    rule_violation_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    amount: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR")

    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_snapshot: Mapped[dict] = mapped_column(JSONType, default=dict)
    model_versions: Mapped[dict] = mapped_column(JSONType, default=dict)
    degraded_components: Mapped[list] = mapped_column(JSONType, default=list)
    component_health: Mapped[list] = mapped_column(JSONType, default=list)

    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    evidence: Mapped[list[RiskEvidenceRow]] = relationship(
        back_populates="decision_row", cascade="all, delete-orphan", lazy="selectin"
    )


class RiskEvidenceRow(Base):
    __tablename__ = "risk_evidence"
    __table_args__ = (Index("ix_risk_evidence_signal", "signal"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("risk_decisions.decision_id", ondelete="CASCADE"), nullable=False
    )
    signal: Mapped[str] = mapped_column(String(64), nullable=False)
    observed: Mapped[str] = mapped_column(Text, nullable=False)
    observed_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    severity: Mapped[str] = mapped_column(String(16), default="info")
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(24), default="increases_risk")
    contribution: Mapped[float | None] = mapped_column(Float, nullable=True)

    decision_row: Mapped[RiskDecisionRow] = relationship(back_populates="evidence")


class CampaignRow(Base):
    __tablename__ = "campaigns"
    __table_args__ = (Index("ix_campaigns_detected_at", "detected_at"),)

    campaign_id: Mapped[str] = id_column(primary_key=True)
    cluster_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    campaign_risk: Mapped[float] = mapped_column(Float, nullable=False)
    size: Mapped[int] = mapped_column(Integer, default=0)
    customer_count: Mapped[int] = mapped_column(Integer, default=0)
    agent_count: Mapped[int] = mapped_column(Integer, default=0)
    device_count: Mapped[int] = mapped_column(Integer, default=0)
    shared_entities: Mapped[dict] = mapped_column(JSONType, default=dict)
    transaction_ids: Mapped[list] = mapped_column(JSONType, default=list)
    evidence: Mapped[list] = mapped_column(JSONType, default=list)
    graph_version: Mapped[str] = mapped_column(String(64), default="graph-networkx-v1")
    detected_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class RiskCaseRow(Base):
    __tablename__ = "risk_cases"
    __table_args__ = (
        UniqueConstraint("campaign_id", name="uq_risk_cases_campaign_id"),
        Index("ix_risk_cases_status", "status"),
    )

    case_id: Mapped[str] = id_column(primary_key=True)
    campaign_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="open")
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    decision_ids: Mapped[list] = mapped_column(JSONType, default=list)
    transaction_ids: Mapped[list] = mapped_column(JSONType, default=list)
    evidence: Mapped[list] = mapped_column(JSONType, default=list)
    analyst_notes: Mapped[list] = mapped_column(JSONType, default=list)
    resolution: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class EvaluationRunRow(Base):
    __tablename__ = "evaluation_runs"

    run_id: Mapped[str] = id_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    dataset_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dataset_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    seed: Mapped[int] = mapped_column(Integer, default=42)
    detectors: Mapped[list] = mapped_column(JSONType, default=list)
    cost_model: Mapped[dict] = mapped_column(JSONType, default=dict)
    dataset_summary: Mapped[dict] = mapped_column(JSONType, default=dict)
    results: Mapped[list] = mapped_column(JSONType, default=list)
    threshold_sweep: Mapped[dict] = mapped_column(JSONType, default=dict)
    leakage_check: Mapped[dict] = mapped_column(JSONType, default=dict)
    report_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class SemanticErrorRow(Base):
    """Persisted record of every rejected/malformed semantic-model response (PRD §25.2)."""

    __tablename__ = "semantic_errors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    error_code: Mapped[str] = mapped_column(String(64), nullable=False)
    error_detail: Mapped[str] = mapped_column(Text, nullable=False)
    raw_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
