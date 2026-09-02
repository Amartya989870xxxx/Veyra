"""FastAPI router for incident inspection and analyst actions (Phase 6.1)."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.auth import AuthenticatedPrincipal, get_current_principal, resolve_tenant_scope
from app.schemas.enums import IncidentStatus
from app.serving.incident_service import IncidentService

router = APIRouter(prefix="/incidents", tags=["Incidents v2"])


class ApplyActionRequest(BaseModel):
    action: str = Field(..., description="Action to take: ACKNOWLEDGE, APPLY_DEFENSE, DISMISS, RESOLVE")
    analyst_notes: str = Field(default="", description="Optional context / notes from analyst")


@router.get("")
async def list_incidents(
    merchant_id: str | None = Query(default=None, description="Filter by merchant ID"),
    status: str | None = Query(default=None, description="Filter by incident status (ACTIVE, INVESTIGATING, RESOLVED)"),
    limit: int = Query(default=50, ge=1, le=200),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    session: AsyncSession = Depends(db_session),
) -> list[dict[str, Any]]:
    scoped_merchant_id = resolve_tenant_scope(principal, merchant_id)
    service = IncidentService(session)
    rows = await service.list_incidents(merchant_id=scoped_merchant_id, status=status, limit=limit)
    # `IncidentStoreRow` has no `window_size`/`window_end`/`recommended_action` columns —
    # it has `window_sizes` (a list; an incident can span more than one horizon),
    # `last_flag_time`, and a `recommended_control` key inside the `evidence` JSON blob.
    # This previously read attributes that don't exist and raised AttributeError the
    # first time this endpoint returned a non-empty result; no prior test surfaced it
    # because it only ever ran against an empty list.
    return [
        {
            "incident_id": r.incident_id,
            "merchant_id": r.merchant_id,
            "window_size": r.window_sizes[0] if r.window_sizes else None,
            "window_end": r.last_flag_time.isoformat(),
            "action_tier": r.action_tier,
            "risk_score": r.risk_score,
            "status": r.status,
            "recommended_action": (r.evidence or {}).get("recommended_control"),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/{incident_id}")
async def get_incident(
    incident_id: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    session: AsyncSession = Depends(db_session),
) -> dict[str, Any]:
    service = IncidentService(session)
    row = await service.get_incident(incident_id)
    # Cross-tenant access returns the same 404 as "does not exist" rather than 403, so
    # an incident ID cannot be used to probe whether it belongs to another merchant.
    if not row or not principal.can_access_merchant(row.merchant_id):
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")

    evidence = row.evidence or {}
    return {
        "incident_id": row.incident_id,
        "merchant_id": row.merchant_id,
        "window_size": row.window_sizes[0] if row.window_sizes else None,
        "window_end": row.last_flag_time.isoformat(),
        "action_tier": row.action_tier,
        "risk_score": row.risk_score,
        "status": row.status,
        "evidence_payload": evidence,
        "recommended_action": evidence.get("recommended_control"),
        "analyst_notes": evidence.get("analyst_notes", ""),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.post("/{incident_id}/action")
async def apply_incident_action(
    incident_id: str,
    req: ApplyActionRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    session: AsyncSession = Depends(db_session),
) -> dict[str, Any]:
    service = IncidentService(session)
    existing = await service.get_incident(incident_id)
    if not existing or not principal.can_access_merchant(existing.merchant_id):
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")

    updated = await service.apply_action(
        incident_id=incident_id,
        action=req.action,
        analyst_notes=req.analyst_notes,
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")

    return {
        "incident_id": updated.incident_id,
        "status": updated.status,
        "analyst_notes": (updated.evidence or {}).get("analyst_notes", ""),
        "message": f"Successfully applied action {req.action} to incident {incident_id}",
    }
