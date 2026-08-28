"""Campaign persistence and analyst case management.

A campaign is a detected cluster; a case is the analyst-facing container for it. Both are
keyed so that repeated detection of the same cluster updates one record rather than
producing a new one per transaction — the "no duplicate campaign effect" half of the
idempotency requirement.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import campaign_id as new_campaign_id
from app.core.ids import case_id as new_case_id
from app.core.logging import get_logger
from app.core.metrics import CAMPAIGNS_DETECTED_TOTAL, CASES_CREATED_TOTAL, METRICS
from app.graph.base import CampaignCandidate
from app.models.risk import CampaignRow, RiskCaseRow
from app.schemas.enums import CaseStatus, EvidenceDirection, Severity, SignalSource
from app.schemas.risk import CampaignResponse, RiskCaseResponse, RiskEvidence

log = get_logger(__name__)

CASE_SEVERITY_THRESHOLDS = ((0.8, Severity.CRITICAL), (0.6, Severity.HIGH), (0.4, Severity.MEDIUM))


def severity_for(score: float) -> Severity:
    for threshold, severity in CASE_SEVERITY_THRESHOLDS:
        if score >= threshold:
            return severity
    return Severity.LOW


def candidate_evidence(candidate: CampaignCandidate) -> list[RiskEvidence]:
    return [
        RiskEvidence(
            signal=reason["signal"],
            observed=reason["observed"],
            observed_value=reason.get("observed_value"),
            expected_value=reason.get("expected_value"),
            severity=Severity.HIGH,
            source=SignalSource.GRAPH_ENGINE,
            direction=EvidenceDirection.INCREASES_RISK,
        )
        for reason in candidate.reasons
    ]


async def upsert_campaign(
    session: AsyncSession, candidate: CampaignCandidate, graph_version: str
) -> tuple[CampaignRow, bool]:
    """Create or refresh a campaign record, keyed on the cluster's content hash."""
    cluster = candidate.cluster
    stmt = select(CampaignRow).where(CampaignRow.cluster_key == cluster.cluster_key)
    existing = (await session.execute(stmt)).scalar_one_or_none()

    evidence = [e.model_dump(mode="json") for e in candidate_evidence(candidate)]
    if existing is not None:
        existing.campaign_risk = candidate.score
        existing.size = cluster.size
        existing.customer_count = cluster.customer_count
        existing.agent_count = cluster.agent_count
        existing.device_count = cluster.device_count
        existing.shared_entities = cluster.shared_entities
        existing.transaction_ids = cluster.transaction_ids[:500]
        existing.evidence = evidence
        existing.updated_at = datetime.now(UTC)
        return existing, False

    row = CampaignRow(
        campaign_id=new_campaign_id(),
        cluster_key=cluster.cluster_key,
        campaign_risk=candidate.score,
        size=cluster.size,
        customer_count=cluster.customer_count,
        agent_count=cluster.agent_count,
        device_count=cluster.device_count,
        shared_entities=cluster.shared_entities,
        transaction_ids=cluster.transaction_ids[:500],
        evidence=evidence,
        graph_version=graph_version,
        detected_at=cluster.last_seen or datetime.now(UTC),
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            return existing, False
        raise
    METRICS.increment(CAMPAIGNS_DETECTED_TOTAL)
    return row, True


async def open_case_for_campaign(
    session: AsyncSession, campaign: CampaignRow, decision_ids: list[str] | None = None
) -> tuple[RiskCaseRow, bool]:
    """One case per campaign. Repeat detections append to it rather than opening a new one."""
    stmt = select(RiskCaseRow).where(RiskCaseRow.campaign_id == campaign.campaign_id)
    existing = (await session.execute(stmt)).scalar_one_or_none()

    if existing is not None:
        if decision_ids:
            merged = list(dict.fromkeys([*existing.decision_ids, *decision_ids]))
            existing.decision_ids = merged[:500]
        existing.transaction_ids = list(
            dict.fromkeys([*existing.transaction_ids, *campaign.transaction_ids])
        )[:500]
        existing.severity = str(severity_for(campaign.campaign_risk))
        existing.updated_at = datetime.now(UTC)
        return existing, False

    row = RiskCaseRow(
        case_id=new_case_id(),
        campaign_id=campaign.campaign_id,
        status=str(CaseStatus.OPEN),
        severity=str(severity_for(campaign.campaign_risk)),
        summary=(
            f"Coordinated activity cluster: {campaign.size} transactions across "
            f"{campaign.customer_count} accounts, {campaign.device_count} device(s) and "
            f"{campaign.agent_count} agent(s)."
        ),
        decision_ids=list(decision_ids or [])[:500],
        transaction_ids=list(campaign.transaction_ids)[:500],
        evidence=campaign.evidence,
        analyst_notes=[],
    )
    session.add(row)
    await session.flush()
    METRICS.increment(CASES_CREATED_TOTAL)
    return row, True


async def get_campaign(session: AsyncSession, campaign_id: str) -> CampaignRow | None:
    return await session.get(CampaignRow, campaign_id)


async def get_case(session: AsyncSession, case_id: str) -> RiskCaseRow | None:
    return await session.get(RiskCaseRow, case_id)


async def list_campaigns(session: AsyncSession, limit: int = 50) -> list[CampaignRow]:
    stmt = select(CampaignRow).order_by(CampaignRow.detected_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars())


async def list_cases(
    session: AsyncSession, status: str | None = None, limit: int = 50
) -> list[RiskCaseRow]:
    stmt = select(RiskCaseRow)
    if status:
        stmt = stmt.where(RiskCaseRow.status == status)
    stmt = stmt.order_by(RiskCaseRow.created_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars())


def campaign_to_response(row: CampaignRow) -> CampaignResponse:
    return CampaignResponse(
        campaign_id=row.campaign_id,
        detected_at=row.detected_at,
        campaign_risk=row.campaign_risk,
        size=row.size,
        customer_count=row.customer_count,
        agent_count=row.agent_count,
        device_count=row.device_count,
        shared_entities=row.shared_entities or {},
        transaction_ids=list(row.transaction_ids or []),
        evidence=[RiskEvidence.model_validate(e) for e in (row.evidence or [])],
    )


def case_to_response(row: RiskCaseRow) -> RiskCaseResponse:
    return RiskCaseResponse(
        case_id=row.case_id,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        campaign_id=row.campaign_id,
        decision_ids=list(row.decision_ids or []),
        transaction_ids=list(row.transaction_ids or []),
        severity=Severity(row.severity),
        summary=row.summary,
        evidence=[RiskEvidence.model_validate(e) for e in (row.evidence or [])],
        analyst_notes=list(row.analyst_notes or []),
        resolution=row.resolution,
    )
