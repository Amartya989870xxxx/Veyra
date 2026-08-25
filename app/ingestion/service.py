"""Event ingestion, normalization and idempotency.

Idempotency is enforced in two places, and the order matters:

1. A Redis ``SET NX`` claim is a *fast path* only. It can be wrong when Redis is down, and
   the code assumes it can be.
2. A unique constraint on ``ingested_events.idempotency_key`` is the actual guarantee. A
   duplicate surfaces as an ``IntegrityError``, which is caught and reported as a duplicate
   rather than an error.

This ordering means a Redis outage degrades throughput, never correctness: the same event
sent twice still produces one transaction, one decision and one campaign effect.
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
from app.models.entities import IngestedEventRow
from app.schemas.events import (
    AgentActionEvent,
    DelegationCreatedEvent,
    EventIngestResult,
    OrderCreatedEvent,
    PaymentResultEvent,
    SessionStartedEvent,
    TransactionAttemptEvent,
)
from app.transactions import repository as repo

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
    def _payload_of(event) -> dict:
        return event.model_dump(mode="json")

    async def ingest(self, session: AsyncSession, event) -> IngestOutcome:
        """Validate, dedupe and persist one canonical event."""
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
            # The fast path says duplicate. Confirm against the database, because a Redis
            # key can outlive a rolled-back transaction and we must not drop a real event.
            if await session.get(IngestedEventRow, event.event_id):
                METRICS.increment(EVENTS_DUPLICATE_TOTAL)
                return IngestOutcome(
                    EventIngestResult(
                        event_id=event.event_id, accepted=False, duplicate=True,
                        reason="event already ingested",
                    ),
                    degraded=degraded,
                )

        payload = self._payload_of(event)
        row = IngestedEventRow(
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
            # The authoritative duplicate check. This is the guarantee, not the Redis claim.
            await session.rollback()
            METRICS.increment(EVENTS_DUPLICATE_TOTAL)
            return IngestOutcome(
                EventIngestResult(
                    event_id=event.event_id, accepted=False, duplicate=True,
                    reason="event already ingested",
                ),
                degraded=degraded,
            )

        transaction_id = await self._apply(session, event)
        METRICS.increment(EVENTS_INGESTED_TOTAL, event_type=str(event.event_type))
        return IngestOutcome(
            EventIngestResult(event_id=event.event_id, accepted=True),
            transaction_id=transaction_id,
            degraded=degraded,
        )

    async def _apply(self, session: AsyncSession, event) -> str | None:
        """Project a canonical event onto the domain tables."""
        if isinstance(event, TransactionAttemptEvent):
            await repo.save_transaction(session, event.transaction)
            return event.transaction.transaction_id

        if isinstance(event, PaymentResultEvent):
            row = await repo.get_transaction(session, event.transaction_id)
            if row is not None:
                row.status = str(event.status)
            return event.transaction_id

        if isinstance(event, AgentActionEvent):
            await repo.save_action(session, event.action)
            return None

        if isinstance(event, SessionStartedEvent):
            await repo.save_session(session, event.session)
            return None

        if isinstance(event, DelegationCreatedEvent):
            await repo.save_delegation(session, event.delegation)
            return None

        if isinstance(event, OrderCreatedEvent):
            await repo.save_order(session, event.order)
            return None

        return None

    async def ingest_batch(self, session: AsyncSession, events: list) -> list[IngestOutcome]:
        outcomes = []
        for event in events:
            outcomes.append(await self.ingest(session, event))
        return outcomes
