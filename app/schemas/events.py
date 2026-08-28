"""Canonical event envelope.

Every externally accepted event carries ``event_id``, ``event_type``, ``source``,
``timestamp`` and ``schema_version`` (one-shot prompt §5). ``idempotency_key`` defaults
to ``event_id`` so replay is safe even when a client omits it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.versions import SCHEMA_VERSION
from app.schemas.entities import AgentAction, AgentDelegation, AgentSession, Order, Transaction
from app.schemas.enums import EventType, PaymentStatus


class EventEnvelope(BaseModel):
    """Shared envelope fields. Subclasses bind a payload to an ``event_type``."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(..., min_length=1, max_length=128)
    event_type: EventType
    source: str = Field(default="synthetic", max_length=64)
    timestamp: datetime
    schema_version: str = Field(default=SCHEMA_VERSION, max_length=16)
    idempotency_key: str | None = Field(default=None, max_length=128)
    merchant_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _default_idempotency(self) -> EventEnvelope:
        if not self.idempotency_key:
            object.__setattr__(self, "idempotency_key", self.event_id)
        return self


class TransactionAttemptEvent(EventEnvelope):
    event_type: Literal[EventType.TRANSACTION_ATTEMPT] = EventType.TRANSACTION_ATTEMPT
    transaction: Transaction

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "event_id": "evt_0001",
                    "event_type": "TRANSACTION_ATTEMPT",
                    "source": "synthetic",
                    "timestamp": "2026-02-14T10:31:04Z",
                    "schema_version": SCHEMA_VERSION,
                    "transaction": Transaction.model_config["json_schema_extra"]["examples"][0],
                }
            ]
        },
    )


class PaymentResultEvent(EventEnvelope):
    event_type: Literal[EventType.PAYMENT_RESULT] = EventType.PAYMENT_RESULT
    transaction_id: str = Field(..., max_length=128)
    status: PaymentStatus
    failure_reason: str | None = Field(default=None, max_length=128)


class AgentActionEvent(EventEnvelope):
    event_type: Literal[EventType.AGENT_ACTION] = EventType.AGENT_ACTION
    action: AgentAction


class SessionStartedEvent(EventEnvelope):
    event_type: Literal[EventType.SESSION_STARTED] = EventType.SESSION_STARTED
    session: AgentSession


class DelegationCreatedEvent(EventEnvelope):
    event_type: Literal[EventType.DELEGATION_CREATED] = EventType.DELEGATION_CREATED
    delegation: AgentDelegation


class OrderCreatedEvent(EventEnvelope):
    event_type: Literal[EventType.ORDER_CREATED] = EventType.ORDER_CREATED
    order: Order


CanonicalEvent = Annotated[
    TransactionAttemptEvent | PaymentResultEvent | AgentActionEvent | SessionStartedEvent | DelegationCreatedEvent | OrderCreatedEvent,
    Field(discriminator="event_type"),
]


class EventBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[CanonicalEvent] = Field(..., min_length=1, max_length=500)


class EventIngestResult(BaseModel):
    event_id: str
    accepted: bool
    duplicate: bool = False
    reason: str | None = None


class EventBatchResponse(BaseModel):
    accepted: int
    duplicates: int
    rejected: int
    results: list[EventIngestResult]
