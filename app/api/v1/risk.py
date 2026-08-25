"""The risk decision endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, get_risk_service, rate_limit, require_api_key
from app.core.errors import NotFoundError, UnknownSchemaError
from app.core.versions import SCHEMA_VERSION
from app.risk.service import RiskService
from app.schemas.risk import RiskDecisionResponse, RiskEvaluateRequest

router = APIRouter(
    prefix="/api/v1/risk",
    tags=["risk"],
    dependencies=[Depends(require_api_key), Depends(rate_limit)],
)


@router.post(
    "/evaluate",
    response_model=RiskDecisionResponse,
    summary="Evaluate a transaction and return a bounded recommendation",
    description=(
        "Returns an evidence-backed ALLOW / REVIEW / BLOCK **recommendation**. Tyche never "
        "executes a financial action; the decision is advisory and the deterministic policy "
        "engine, not any model, decides it.\n\n"
        "Component scores are returned uncombined alongside the fused score. A `null` "
        "component means it genuinely could not be computed — it is never defaulted to a "
        "value — and `degraded_components` names every component that did not contribute."
    ),
)
async def evaluate_risk(
    request: RiskEvaluateRequest,
    session: AsyncSession = Depends(db_session),
    service: RiskService = Depends(get_risk_service),
) -> RiskDecisionResponse:
    if request.schema_version != SCHEMA_VERSION:
        raise UnknownSchemaError(
            f"unsupported schema_version '{request.schema_version}'",
            details={"supported": [SCHEMA_VERSION]},
        )
    evaluation = await service.evaluate(session, request)
    return evaluation.response


@router.get(
    "/decisions/{decision_id}",
    summary="Retrieve a persisted decision with its full audit record",
)
async def get_decision(
    decision_id: str = Path(..., max_length=128),
    session: AsyncSession = Depends(db_session),
) -> dict:
    from app.audit import store as audit

    row = await audit.get_decision(session, decision_id)
    if row is None:
        raise NotFoundError(f"decision '{decision_id}' not found")

    return {
        "decision_id": row.decision_id,
        "transaction_id": row.transaction_id,
        "decision": row.decision,
        "status": row.status,
        "risk_score": row.risk_score,
        "components": {
            "transaction_risk": row.transaction_risk,
            "behavior_risk": row.behavior_risk,
            "campaign_risk": row.campaign_risk,
            "intent_deviation": row.intent_deviation,
            "rule_violation_score": row.rule_violation_score,
        },
        "reason_code": row.reason_code,
        "rationale": row.rationale,
        "campaign_id": row.campaign_id,
        "case_id": row.case_id,
        "evidence": [
            {
                "signal": e.signal,
                "observed": e.observed,
                "observed_value": e.observed_value,
                "expected_value": e.expected_value,
                "severity": e.severity,
                "source": e.source,
                "direction": e.direction,
                "contribution": e.contribution,
            }
            for e in row.evidence
        ],
        "reproducibility": {
            "policy_version": row.policy_version,
            "feature_version": row.feature_version,
            "feature_snapshot_hash": row.feature_snapshot_hash,
            "model_versions": row.model_versions,
            "decided_at": row.decided_at.isoformat(),
        },
        "degraded_components": row.degraded_components,
        "component_health": row.component_health,
        "latency_ms": row.latency_ms,
        "request_id": row.request_id,
    }
