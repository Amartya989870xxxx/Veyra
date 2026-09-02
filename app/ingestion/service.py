"""Event ingestion, normalization and idempotency for Veyra v2.

Idempotency is enforced in two places:
1. A Redis ``SET NX`` claim is a fast path.
2. A unique constraint on ``raw_events.idempotency_key`` is the authoritative guarantee.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import stable_hash
from app.core.logging import get_logger
from app.core.metrics import EVENTS_DUPLICATE_TOTAL, EVENTS_INGESTED_TOTAL, METRICS
from app.core.redis_client import HotStateClient, get_hot_state
from app.core.versions import SCHEMA_VERSION
from app.models.entities import RawEventRow
from app.models.repositories import RawEventsRepository
from app.schemas.events import (
    CanonicalEvent,
    DisputeEvent,
    EventIngestResult,
    OrderStatusEvent,
    PaymentAttemptEvent,
    PaymentResultEvent,
    RefundEvent,
)

log = get_logger(__name__)

SUPPORTED_SCHEMA_VERSIONS = {SCHEMA_VERSION}
DEDUPE_TTL_SECONDS = 86_400


@dataclass
class IngestOutcome:
    result: EventIngestResult
    transaction_id: str | None = None
    degraded: bool = False


class IngestionService:
    def __init__(self, hot_state: HotStateClient | None = None) -> None:
        self.hot_state = hot_state or get_hot_state()

    @staticmethod
    def _payload_of(event: CanonicalEvent) -> dict:
        return event.model_dump(mode="json")

    async def ingest(self, session: AsyncSession, event: CanonicalEvent) -> IngestOutcome:
        """Validate, dedupe and persist one canonical event into raw_events."""
        if event.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            return IngestOutcome(
                EventIngestResult(
                    event_id=event.event_id,
                    accepted=False,
                    reason=(
                        f"unsupported schema_version '{event.schema_version}'; "
                        f"supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
                    ),
                )
            )

        key = event.idempotency_key or event.event_id
        claimed, degraded = await self.hot_state.claim_once(
            f"veyra:dedupe:{key}", event.event_id, DEDUPE_TTL_SECONDS
        )
        if not claimed:
            # Fast path indicates potential duplicate; verify in database
            if await RawEventsRepository.get_by_idempotency_key(session, key):
                METRICS.increment(EVENTS_DUPLICATE_TOTAL)
                return IngestOutcome(
                    EventIngestResult(
                        event_id=event.event_id,
                        accepted=False,
                        duplicate=True,
                        reason="event already ingested",
                    ),
                    degraded=degraded,
                )

        payload = self._payload_of(event)
        row = RawEventRow(
            event_id=event.event_id,
            event_type=str(event.event_type),
            source=event.source,
            schema_version=event.schema_version,
            idempotency_key=key,
            merchant_id=event.merchant_id,
            payload_hash=stable_hash(json.dumps(payload, sort_keys=True)),
            payload=payload,
            timestamp=event.timestamp,
        )

        session.add(row)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            METRICS.increment(EVENTS_DUPLICATE_TOTAL)
            return IngestOutcome(
                EventIngestResult(
                    event_id=event.event_id,
                    accepted=False,
                    duplicate=True,
                    reason="event already ingested",
                ),
                degraded=degraded,
            )

        txn_id = self._extract_transaction_id(event)
        METRICS.increment(EVENTS_INGESTED_TOTAL, event_type=str(event.event_type))
        return IngestOutcome(
            EventIngestResult(event_id=event.event_id, accepted=True),
            transaction_id=txn_id,
            degraded=degraded,
        )

    @staticmethod
    def _extract_transaction_id(event: CanonicalEvent) -> str | None:
        if isinstance(event, PaymentAttemptEvent):
            return event.payment_attempt.transaction_id
        if isinstance(event, PaymentResultEvent):
            return event.outcome.transaction_id
        if isinstance(event, RefundEvent):
            return event.refund.transaction_id
        if isinstance(event, DisputeEvent):
            return event.dispute.transaction_id
        if isinstance(event, OrderStatusEvent):
            return None
        return None

    async def ingest_batch(
        self, session: AsyncSession, events: list[CanonicalEvent]
    ) -> list[IngestOutcome]:
        outcomes = []
        for event in events:
            outcomes.append(await self.ingest(session, event))
        return outcomes
