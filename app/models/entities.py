"""ORM models for canonical entities and ingested events.

Idempotency is enforced at the database level: ``ingested_events.event_id`` and
``ingested_events.idempotency_key`` are unique, and each canonical record keys on its own
natural synthetic ID. Application logic can be retried safely because the constraint,
not the code path, is the guarantee (one-shot prompt §16).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, Money, UtcDateTime, id_column, utcnow


class MerchantRow(Base):
    __tablename__ = "merchants"

    merchant_id: Mapped[str] = id_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_policy_id: Mapped[str] = mapped_column(String(64), default="policy_default_v1")
    is_known: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class CustomerRow(Base):
    __tablename__ = "customers"

    customer_id: Mapped[str] = id_column(primary_key=True)
    segment: Mapped[str] = mapped_column(String(32), default="retail")
    home_country: Mapped[str] = mapped_column(String(2), default="IN")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class AgentRow(Base):
    __tablename__ = "agents"

    agent_id: Mapped[str] = id_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), default="synthetic")
    application_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trust_tier: Mapped[str] = mapped_column(String(32), default="standard")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class AgentDelegationRow(Base):
    __tablename__ = "agent_delegations"

    delegation_id: Mapped[str] = id_column(primary_key=True)
    customer_id: Mapped[str] = id_column(index=True)
    agent_id: Mapped[str] = id_column(index=True)
    purpose: Mapped[str] = mapped_column(String(64), default="general_purchase")
    max_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    allowed_categories: Mapped[list] = mapped_column(JSONType, default=list)
    forbidden_categories: Mapped[list] = mapped_column(JSONType, default=list)
    allowed_merchants: Mapped[list] = mapped_column(JSONType, default=list)
    allowed_actions: Mapped[list] = mapped_column(JSONType, default=list)
    merchant_policy: Mapped[str] = mapped_column(String(32), default="known_or_approved")
    approval_required_above: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class AgentSessionRow(Base):
    __tablename__ = "agent_sessions"

    session_id: Mapped[str] = id_column(primary_key=True)
    agent_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    customer_id: Mapped[str] = id_column(index=True)
    actor_type: Mapped[str] = mapped_column(String(16), default="AGENT")
    device_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    network_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class AgentActionRow(Base):
    __tablename__ = "agent_actions"
    __table_args__ = (
        Index("ix_agent_actions_session_seq", "session_id", "sequence_number"),
        Index("ix_agent_actions_agent_ts", "agent_id", "timestamp"),
    )

    action_id: Mapped[str] = id_column(primary_key=True)
    agent_id: Mapped[str] = id_column()
    session_id: Mapped[str] = id_column()
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    merchant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sku_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    action_metadata: Mapped[dict] = mapped_column(JSONType, default=dict)


class OrderRow(Base):
    __tablename__ = "orders"

    order_id: Mapped[str] = id_column(primary_key=True)
    merchant_id: Mapped[str] = id_column(index=True)
    customer_id: Mapped[str] = id_column(index=True)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    sku_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class TransactionRow(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_customer_ts", "customer_id", "timestamp"),
        Index("ix_transactions_agent_ts", "agent_id", "timestamp"),
        Index("ix_transactions_device_ts", "device_id", "timestamp"),
        Index("ix_transactions_ts", "timestamp"),
    )

    transaction_id: Mapped[str] = id_column(primary_key=True)
    merchant_id: Mapped[str] = id_column()
    customer_id: Mapped[str] = id_column()
    agent_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    delegation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    merchant_category: Mapped[str] = mapped_column(String(64), nullable=False)
    sku_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    coupon_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    coupon_value: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    device_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    network_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    payment_method: Mapped[str] = mapped_column(String(32), default="upi")
    instrument_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="ATTEMPTED")
    actor_type: Mapped[str] = mapped_column(String(16), default="HUMAN")
    timestamp: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class IngestedEventRow(Base):
    """Append-only ledger of accepted events; the idempotency boundary."""

    __tablename__ = "ingested_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_ingested_events_idempotency_key"),
        Index("ix_ingested_events_type_ts", "event_type", "timestamp"),
    )

    event_id: Mapped[str] = id_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="synthetic")
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    merchant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    timestamp: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    received_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class EntityRelationshipRow(Base):
    """Canonical relationship store; the graph engine reads bounded windows from here."""

    __tablename__ = "entity_relationships"
    __table_args__ = (
        UniqueConstraint(
            "source_type", "source_id", "target_type", "target_id", "relationship",
            name="uq_entity_relationships_edge",
        ),
        Index("ix_entity_relationships_target", "target_type", "target_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    relationship: Mapped[str] = mapped_column(String(48), nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    first_seen: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    observation_count: Mapped[int] = mapped_column(Integer, default=1)
