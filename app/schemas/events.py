"""Canonical event envelope.

Every externally accepted event carries ``event_id``, ``event_type``, ``source``,
``timestamp`` and ``schema_version``. ``idempotency_key`` defaults to ``event_id`` so
replay is safe even when a client omits it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.versions import SCHEMA_VERSION
from app.schemas.entities import Dispute, OrderOutcome, PaymentAttempt, PaymentOutcome, Refund
from app.schemas.enums import EventType


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
    def _default_idempotency_and_merchant(self) -> EventEnvelope:
        if not self.idempotency_key:
            object.__setattr__(self, "idempotency_key", self.event_id)
        return self


class PaymentAttemptEvent(EventEnvelope):
    event_type: Literal[EventType.PAYMENT_ATTEMPT] = EventType.PAYMENT_ATTEMPT
    payment_attempt: PaymentAttempt

    @model_validator(mode="after")
    def _sync_merchant_and_timestamp(self) -> PaymentAttemptEvent:
        if not self.merchant_id:
            object.__setattr__(self, "merchant_id", self.payment_attempt.merchant_id)
        return self


class PaymentResultEvent(EventEnvelope):
    event_type: Literal[EventType.PAYMENT_RESULT] = EventType.PAYMENT_RESULT
    outcome: PaymentOutcome


class RefundEvent(EventEnvelope):
    event_type: Literal[EventType.REFUND] = EventType.REFUND
    refund: Refund


class DisputeEvent(EventEnvelope):
    """Dispute event. Label source ONLY per ADR-004."""

    event_type: Literal[EventType.DISPUTE] = EventType.DISPUTE
    dispute: Dispute


class OrderStatusEvent(EventEnvelope):
    event_type: Literal[EventType.ORDER_STATUS] = EventType.ORDER_STATUS
    order: OrderOutcome

    @model_validator(mode="after")
    def _sync_merchant(self) -> OrderStatusEvent:
        if not self.merchant_id:
            object.__setattr__(self, "merchant_id", self.order.merchant_id)
        return self


CanonicalEvent = Annotated[
    PaymentAttemptEvent | PaymentResultEvent | RefundEvent | DisputeEvent | OrderStatusEvent,
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
