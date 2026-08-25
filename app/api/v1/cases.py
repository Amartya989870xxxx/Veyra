"""Campaign and case investigation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, rate_limit, require_api_key
from app.cases import service as cases
from app.core.errors import NotFoundError, ValidationError
from app.schemas.enums import CaseStatus
from app.schemas.risk import CampaignResponse, RiskCaseResponse

router = APIRouter(
    prefix="/api/v1", tags=["investigation"],
    dependencies=[Depends(require_api_key), Depends(rate_limit)],
)


@router.get("/campaigns", response_model=list[CampaignResponse], summary="List detected campaigns")
async def list_campaigns(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(db_session),
) -> list[CampaignResponse]:
    rows = await cases.list_campaigns(session, limit=limit)
    return [cases.campaign_to_response(r) for r in rows]


@router.get(
    "/campaigns/{campaign_id}",
    response_model=CampaignResponse,
    summary="Inspect one detected campaign",
)
async def get_campaign(
    campaign_id: str = Path(..., max_length=128),
    session: AsyncSession = Depends(db_session),
) -> CampaignResponse:
    row = await cases.get_campaign(session, campaign_id)
    if row is None:
        raise NotFoundError(f"campaign '{campaign_id}' not found")
    return cases.campaign_to_response(row)


@router.get("/cases", response_model=list[RiskCaseResponse], summary="List investigation cases")
async def list_cases(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(db_session),
) -> list[RiskCaseResponse]:
    rows = await cases.list_cases(session, status=status, limit=limit)
    return [cases.case_to_response(r) for r in rows]


@router.get(
    "/cases/{case_id}", response_model=RiskCaseResponse, summary="Inspect one investigation case"
)
async def get_case(
    case_id: str = Path(..., max_length=128),
    session: AsyncSession = Depends(db_session),
) -> RiskCaseResponse:
    row = await cases.get_case(session, case_id)
    if row is None:
        raise NotFoundError(f"case '{case_id}' not found")
    return cases.case_to_response(row)


@router.patch(
    "/cases/{case_id}",
    response_model=RiskCaseResponse,
    summary="Update analyst status, notes or resolution",
)
async def update_case(
    case_id: str = Path(..., max_length=128),
    status: str | None = Body(default=None, embed=True),
    note: str | None = Body(default=None, embed=True, max_length=2000),
    resolution: str | None = Body(default=None, embed=True, max_length=64),
    session: AsyncSession = Depends(db_session),
) -> RiskCaseResponse:
    row = await cases.get_case(session, case_id)
    if row is None:
        raise NotFoundError(f"case '{case_id}' not found")

    if status is not None:
        try:
            row.status = str(CaseStatus(status))
        except ValueError as exc:
            raise ValidationError(
                f"invalid case status '{status}'",
                details={"allowed": [s.value for s in CaseStatus]},
            ) from exc
    if note:
        row.analyst_notes = [*(row.analyst_notes or []), note][:200]
    if resolution is not None:
        row.resolution = resolution
    await session.flush()
    return cases.case_to_response(row)
