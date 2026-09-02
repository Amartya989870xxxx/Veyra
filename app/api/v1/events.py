"""Event ingestion endpoints for Veyra v2."""

from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Body, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, get_ingestion_service, rate_limit
from app.core.auth import AuthenticatedPrincipal, get_current_principal, verify_tenant_access
from app.core.errors import NotFoundError
from app.core.logging import event_id_var
from app.ingestion.service import IngestionService
from app.models.repositories import RawEventsRepository
from app.schemas.events import (
    CanonicalEvent,
    EventBatchRequest,
    EventBatchResponse,
    EventIngestResult,
)

router = APIRouter(
    prefix="/api/v1",
    tags=["ingestion"],
    dependencies=[Depends(rate_limit)],
)


@router.post(
    "/events",
    response_model=EventBatchResponse,
    summary="Ingest canonical events (idempotent)",
    description=(
        "Accepts one event or a batch. Ingestion is idempotent on `idempotency_key`, which "
        "defaults to `event_id`: re-sending the same event produces no duplicate records. "
        "Every event's `merchant_id` must belong to the authenticated principal's tenant "
        "(system_service credentials excepted)."
    ),
)
async def ingest_events(
    payload: CanonicalEvent | EventBatchRequest = Body(...),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    session: AsyncSession = Depends(db_session),
    service: IngestionService = Depends(get_ingestion_service),
) -> EventBatchResponse:
    events = payload.events if isinstance(payload, EventBatchRequest) else [payload]
    for event in events:
        verify_tenant_access(principal, event.merchant_id)

    results: list[EventIngestResult] = []
    for event in events:
        event_id_var.set(event.event_id)
        outcome = await service.ingest(session, event)
        results.append(outcome.result)

    return EventBatchResponse(
        accepted=sum(1 for r in results if r.accepted),
        duplicates=sum(1 for r in results if r.duplicate),
        rejected=sum(1 for r in results if not r.accepted and not r.duplicate),
        results=results,
    )


@router.get(
    "/events/{event_id}",
    summary="Look up an ingested event by event_id",
)
async def get_event(
    event_id: str = Path(..., max_length=128),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    session: AsyncSession = Depends(db_session),
) -> dict:
    row = await RawEventsRepository.get_by_event_id(session, event_id)
    if row is None or not principal.can_access_merchant(row.merchant_id):
        raise NotFoundError(f"event '{event_id}' not found")

    return {
        "event_id": row.event_id,
        "event_type": row.event_type,
        "source": row.source,
        "timestamp": row.timestamp.isoformat(),
        "schema_version": row.schema_version,
        "idempotency_key": row.idempotency_key,
        "merchant_id": row.merchant_id,
        "payload_hash": row.payload_hash,
        "payload": row.payload,
        "ingested_at": row.ingested_at.isoformat(),
    }
