"""Immutable decision audit store.

A decision row carries everything needed to reconstruct it: the feature snapshot and its
hash, the feature/policy/model versions, the evidence, the component scores, the degraded
state and the timestamp (PRD §7 Principle 7).

Decision idempotency is derived, not client-supplied: the key is
``transaction_id : policy_version : feature_snapshot_hash``. Re-evaluating the same
transaction against the same features and policy therefore returns the *existing* decision
rather than minting a second one — which is what "no duplicate decision" has to mean when
the same event arrives twice. A genuine re-evaluation under a new policy or new evidence
produces a different hash and is correctly recorded as a new decision.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger, request_id_var
from app.core.versions import FEATURE_VERSION
from app.models.risk import RiskDecisionRow, RiskEvidenceRow, SemanticErrorRow
from app.risk.engine import RiskAssessment
from app.schemas.entities import Transaction

log = get_logger(__name__)


def decision_idempotency_key(assessment: RiskAssessment) -> str:
    return (
        f"{assessment.transaction_id}:{assessment.policy.policy_version}:"
        f"{assessment.snapshot.snapshot_hash}"
    )


async def find_existing_decision(
    session: AsyncSession, key: str
) -> RiskDecisionRow | None:
    stmt = select(RiskDecisionRow).where(RiskDecisionRow.idempotency_key == key)
    return (await session.execute(stmt)).scalar_one_or_none()


async def persist_decision(
    session: AsyncSession,
    assessment: RiskAssessment,
    transaction: Transaction,
) -> tuple[RiskDecisionRow, bool]:
    """Persist a decision. Returns ``(row, created)``; ``created=False`` means it existed."""
    key = decision_idempotency_key(assessment)
    existing = await find_existing_decision(session, key)
    if existing is not None:
        return existing, False

    row = RiskDecisionRow(
        decision_id=assessment.decision_id,
        transaction_id=assessment.transaction_id,
        idempotency_key=key,
        merchant_id=transaction.merchant_id,
        customer_id=transaction.customer_id,
        agent_id=transaction.agent_id,
        campaign_id=assessment.campaign_id,
        case_id=assessment.case_id,
        decision=str(assessment.decision),
        status=str(assessment.policy.status),
        reason_code=assessment.policy.reason_code,
        rationale=assessment.policy.rationale,
        risk_score=assessment.risk_score,
        transaction_risk=assessment.scores.transaction_risk,
        behavior_risk=assessment.scores.behavior_risk,
        campaign_risk=assessment.scores.campaign_risk,
        intent_deviation=assessment.scores.intent_deviation,
        rule_violation_score=assessment.scores.rule_violation_score,
        amount=transaction.amount,
        currency=transaction.currency,
        policy_version=assessment.policy.policy_version,
        feature_version=FEATURE_VERSION,
        feature_snapshot_hash=assessment.snapshot.snapshot_hash,
        feature_snapshot={k: round(v, 6) for k, v in assessment.snapshot.values.items()},
        model_versions=assessment.model_versions,
        degraded_components=list(assessment.degraded_components),
        component_health=[h.model_dump(mode="json") for h in assessment.component_health],
        latency_ms=assessment.latency_ms,
        request_id=request_id_var.get(),
        decided_at=assessment.decided_at,
    )
    session.add(row)

    for item in assessment.evidence:
        session.add(
            RiskEvidenceRow(
                decision_id=assessment.decision_id,
                signal=item.signal,
                observed=item.observed,
                observed_value=item.observed_value,
                expected_value=item.expected_value,
                severity=str(item.severity),
                source=str(item.source),
                direction=str(item.direction),
                contribution=item.contribution,
            )
        )

    try:
        await session.flush()
    except IntegrityError:
        # Concurrent evaluation of the same transaction produced the same key first.
        await session.rollback()
        existing = await find_existing_decision(session, key)
        if existing is not None:
            return existing, False
        raise

    if assessment.intent and assessment.intent.semantic and assessment.intent.semantic.error_code:
        await record_semantic_error(session, assessment)

    return row, True


async def record_semantic_error(session: AsyncSession, assessment: RiskAssessment) -> None:
    """Persist rejected or failed semantic output (PRD §25.2). Never silently discarded."""
    semantic = assessment.intent.semantic if assessment.intent else None
    if semantic is None or semantic.error_code in (None, "semantic_disabled"):
        return
    session.add(
        SemanticErrorRow(
            decision_id=assessment.decision_id,
            transaction_id=assessment.transaction_id,
            provider=semantic.provider,
            model=semantic.model,
            error_code=semantic.error_code,
            error_detail=(semantic.error_detail or "")[:2000],
            raw_excerpt=(semantic.raw_excerpt or None),
        )
    )


async def get_decision(session: AsyncSession, decision_id: str) -> RiskDecisionRow | None:
    return await session.get(RiskDecisionRow, decision_id)


async def decisions_for_transaction(
    session: AsyncSession, transaction_id: str, limit: int = 20
) -> list[RiskDecisionRow]:
    stmt = (
        select(RiskDecisionRow)
        .where(RiskDecisionRow.transaction_id == transaction_id)
        .order_by(RiskDecisionRow.decided_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars())
