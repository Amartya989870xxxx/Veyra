"""FastAPI router for inspecting merchant baseline profiles (Phase 6.1)."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.auth import AuthenticatedPrincipal, get_current_principal, resolve_tenant_scope
from app.models.repositories import BaselineStoreRepository

router = APIRouter(prefix="/merchants", tags=["Baselines v2"])


@router.get("/{merchant_id}/baselines")
async def get_merchant_baselines(
    merchant_id: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    session: AsyncSession = Depends(db_session),
) -> dict[str, Any]:
    merchant_id = resolve_tenant_scope(principal, merchant_id)
    rows = await BaselineStoreRepository.list_for_merchant(session, merchant_id)
    return {
        "merchant_id": merchant_id,
        "total_baselines": len(rows),
        "baselines": [
            {
                "feature_id": r.feature_id,
                "window_size": r.window_size,
                "hour_of_week": r.hour_of_week,
                "expected_median": r.expected_median,
                "variability_mad": r.variability_mad,
                "confidence": r.confidence,
                "sample_count": r.sample_count,
            }
            for r in rows
        ],
    }
