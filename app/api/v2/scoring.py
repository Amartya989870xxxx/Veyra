"""FastAPI router for online window scoring (Phase 6.1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.auth import AuthenticatedPrincipal, get_current_principal, resolve_tenant_scope
from app.serving.scoring_service import ScoringService
from app.windows import WindowSize

router = APIRouter(prefix="/score-window", tags=["Scoring v2"])


class ScoreWindowRequest(BaseModel):
    merchant_id: str = Field(..., description="Target merchant ID")
    window_size: WindowSize = Field(default=WindowSize.M5, description="Detection horizon (1m, 5m, 15m, 1h)")
    window_end: datetime | None = Field(default=None, description="Optional aligned window end timestamp (UTC)")


class ScoreWindowResponseDto(BaseModel):
    merchant_id: str
    window_size: str
    window_end: str
    risk_score: float
    action_tier: str
    recommended_defensive_control: str | None = None
    incident_id: str | None = None
    financial_exposure: dict[str, Any]
    explanation: str
    top_feature_deviations: list[dict[str, Any]]
    entity_graph: dict[str, Any]
    baseline_confidence: str
    model_version: str


@router.post("", response_model=ScoreWindowResponseDto)
async def score_window(
    req: ScoreWindowRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    session: AsyncSession = Depends(db_session),
) -> dict[str, Any]:
    merchant_id = resolve_tenant_scope(principal, req.merchant_id)
    service = ScoringService()
    try:
        res = await service.score_window(
            session=session,
            merchant_id=merchant_id,
            window_size=req.window_size,
            window_end=req.window_end,
        )
        return res.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to score window: {str(e)}")
