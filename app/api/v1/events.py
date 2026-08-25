"""Event ingestion endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, get_ingestion_service, rate_limit, require_api_key
from app.core.errors import NotFoundError
from app.core.logging import event_id_var
from app.ingestion.service import IngestionService
from app.schemas.entities import AgentAction
from app.schemas.events import (
    AgentActionEvent,
    CanonicalEvent,
    EventBatchRequest,
    EventBatchResponse,
    EventIngestResult,
)
from app.transactions import repository as repo

router = APIRouter(
    prefix="/api/v1", tags=["ingestion"], dependencies=[Depends(require_api_key), Depends(rate_limit)]
)


@router.post(
    "/events",
    response_model=EventBatchResponse,
    summary="Ingest canonical events (idempotent)",
    description=(
        "Accepts one event or a batch. Ingestion is idempotent on `idempotency_key`, which "
        "defaults to `event_id`: re-sending the same event produces no duplicate "
        "transaction, decision or campaign effect."
    ),
)
async def ingest_events(
    payload: CanonicalEvent | EventBatchRequest = Body(...),
    session: AsyncSession = Depends(db_session),
    service: IngestionService = Depends(get_ingestion_service),
) -> EventBatchResponse:
    events = payload.events if isinstance(payload, EventBatchRequest) else [payload]
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


@router.post(
    "/agents/{agent_id}/actions",
    response_model=EventBatchResponse,
    summary="Ingest agent action traces",
    description="Appends actions to an agent's trajectory. Idempotent on `action_id`.",
)
async def ingest_agent_actions(
    agent_id: str = Path(..., max_length=128),
    actions: list[AgentAction] = Body(..., max_length=500),
    session: AsyncSession = Depends(db_session),
    service: IngestionService = Depends(get_ingestion_service),
) -> EventBatchResponse:
    results: list[EventIngestResult] = []
    for action in actions:
        if action.agent_id != agent_id:
            results.append(
                EventIngestResult(
                    event_id=action.action_id,
                    accepted=False,
                    reason=f"action.agent_id '{action.agent_id}' does not match path '{agent_id}'",
                )
            )
            continue
        event = AgentActionEvent(
            event_id=f"evt_action_{action.action_id}",
            timestamp=action.timestamp,
            action=action,
        )
        outcome = await service.ingest(session, event)
        results.append(
            EventIngestResult(
                event_id=action.action_id,
                accepted=outcome.result.accepted,
                duplicate=outcome.result.duplicate,
                reason=outcome.result.reason,
            )
        )

    return EventBatchResponse(
        accepted=sum(1 for r in results if r.accepted),
        duplicates=sum(1 for r in results if r.duplicate),
        rejected=sum(1 for r in results if not r.accepted and not r.duplicate),
        results=results,
    )


@router.get(
    "/transactions/{transaction_id}",
    summary="Look up a transaction and its decision history",
)
async def get_transaction(
    transaction_id: str = Path(..., max_length=128),
    session: AsyncSession = Depends(db_session),
) -> dict:
    from app.audit import store as audit

    row = await repo.get_transaction(session, transaction_id)
    if row is None:
        raise NotFoundError(f"transaction '{transaction_id}' not found")

    decisions = await audit.decisions_for_transaction(session, transaction_id)
    return {
        "transaction": {
            "transaction_id": row.transaction_id,
            "merchant_id": row.merchant_id,
            "customer_id": row.customer_id,
            "agent_id": row.agent_id,
            "session_id": row.session_id,
            "amount": str(row.amount),
            "currency": row.currency,
            "merchant_category": row.merchant_category,
            "sku_id": row.sku_id,
            "quantity": row.quantity,
            "coupon_id": row.coupon_id,
            "device_id": row.device_id,
            "network_fingerprint": row.network_fingerprint,
            "payment_method": row.payment_method,
            "retry_count": row.retry_count,
            "status": row.status,
            "actor_type": row.actor_type,
            "timestamp": row.timestamp.isoformat(),
        },
        "decisions": [
            {
                "decision_id": d.decision_id,
                "decision": d.decision,
                "status": d.status,
                "risk_score": d.risk_score,
                "reason_code": d.reason_code,
                "rationale": d.rationale,
                "campaign_id": d.campaign_id,
                "case_id": d.case_id,
                "policy_version": d.policy_version,
                "feature_snapshot_hash": d.feature_snapshot_hash,
                "model_versions": d.model_versions,
                "degraded_components": d.degraded_components,
                "decided_at": d.decided_at.isoformat(),
                "latency_ms": d.latency_ms,
            }
            for d in decisions
        ],
    }
