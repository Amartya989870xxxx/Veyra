"""Application service for the risk endpoint.

Sequences context building, campaign detection, scoring, persistence and case creation, and
owns the rule that the API must never claim a decision was stored when it was not (PRD §25.3).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import store as audit
from app.cases import service as cases
from app.core.logging import decision_id_var, get_logger
from app.features.online import OnlineContextBuilder
from app.graph.networkx_engine import NetworkXGraphEngine
from app.risk.engine import RiskAssessment, RiskEngine
from app.schemas.enums import ComponentStatus, Decision
from app.schemas.risk import (
    ComponentHealth,
    RiskDecisionResponse,
    RiskEvaluateRequest,
)
from app.transactions import repository as repo

log = get_logger(__name__)

CAMPAIGN_ATTACH_SCORE = 0.5
"""Minimum cluster concentration score before a campaign record is created. Below this the
cluster is ordinary co-occurrence — a busy merchant, a shared household — and creating a
campaign for it would bury analysts in noise."""

CASE_DECISIONS = {Decision.BLOCK, Decision.REVIEW}


@dataclass
class RiskEvaluation:
    assessment: RiskAssessment
    response: RiskDecisionResponse
    persisted: bool


class RiskService:
    def __init__(
        self,
        engine: RiskEngine,
        context_builder: OnlineContextBuilder | None = None,
        graph_engine: NetworkXGraphEngine | None = None,
    ) -> None:
        self.engine = engine
        self.context_builder = context_builder or OnlineContextBuilder()
        self.graph_engine = graph_engine or NetworkXGraphEngine()

    async def evaluate(
        self, session: AsyncSession, request: RiskEvaluateRequest
    ) -> RiskEvaluation:
        transaction = request.transaction
        authorization = request.authorization
        delegation = authorization.delegation if authorization else None
        instruction = authorization.instruction_text if authorization else None

        ctx = await self.context_builder.build(
            session=session,
            transaction=transaction,
            supplied_actions=request.event_trace or None,
            supplied_delegation=delegation,
            instruction_text=instruction,
        )

        assessment = await self.engine.evaluate(
            ctx=ctx, transaction=transaction, instruction_text=instruction
        )
        decision_id_var.set(assessment.decision_id)

        campaign_id: str | None = None
        case_id: str | None = None
        persisted = False

        if request.persist:
            try:
                await repo.save_transaction(session, transaction)
                campaign_id, case_id = await self._attach_campaign(session, ctx, assessment)
                assessment.campaign_id = campaign_id
                assessment.case_id = case_id
                row, created = await audit.persist_decision(session, assessment, transaction)
                if not created:
                    # An identical evaluation already exists. Return that decision rather
                    # than a second one carrying the same content under a new ID.
                    assessment.decision_id = row.decision_id
                    assessment.campaign_id = row.campaign_id
                    assessment.case_id = row.case_id
                persisted = True
            except Exception as exc:
                # The decision itself is still valid and is returned; what we must not do is
                # report it as durably stored.
                log.error("decision_persistence_failed", extra={"error": str(exc)})
                await session.rollback()
                assessment.component_health.append(
                    ComponentHealth(
                        component="decision_store",
                        status=ComponentStatus.UNAVAILABLE,
                        detail=str(exc)[:200],
                        error_code="persistence_unavailable",
                    )
                )
                if "decision_store" not in assessment.degraded_components:
                    assessment.degraded_components.append("decision_store")
                persisted = False

        return RiskEvaluation(
            assessment=assessment,
            response=self.to_response(assessment, persisted=persisted),
            persisted=persisted,
        )

    async def _attach_campaign(
        self, session: AsyncSession, ctx, assessment: RiskAssessment
    ) -> tuple[str | None, str | None]:
        """Detect and persist a campaign around this transaction, if one is present."""
        members = [*ctx.neighbourhood, ctx.transaction]
        if len(members) < self.graph_engine.min_cluster_size:
            return None, None

        candidates = self.graph_engine.find_campaigns(
            members, ctx.session_actions_by_session, min_size=self.graph_engine.min_cluster_size
        )
        target = ctx.transaction.transaction_id
        candidate = next(
            (c for c in candidates if target in c.cluster.transaction_ids), None
        )
        if candidate is None or candidate.score < CAMPAIGN_ATTACH_SCORE:
            return None, None

        campaign, _ = await cases.upsert_campaign(
            session, candidate, self.graph_engine.version
        )
        case_id = None
        if assessment.decision in CASE_DECISIONS:
            case, _ = await cases.open_case_for_campaign(
                session, campaign, decision_ids=[assessment.decision_id]
            )
            case_id = case.case_id
        return campaign.campaign_id, case_id

    @staticmethod
    def to_response(assessment: RiskAssessment, persisted: bool) -> RiskDecisionResponse:
        return RiskDecisionResponse(
            decision_id=assessment.decision_id,
            transaction_id=assessment.transaction_id,
            decision=assessment.decision,
            status=assessment.policy.status,
            risk_score=assessment.risk_score,
            transaction_risk=assessment.scores.transaction_risk,
            behavior_risk=assessment.scores.behavior_risk,
            campaign_risk=assessment.scores.campaign_risk,
            intent_deviation=assessment.scores.intent_deviation,
            rule_violation_score=assessment.scores.rule_violation_score,
            campaign_id=assessment.campaign_id,
            case_id=assessment.case_id,
            reason_code=assessment.policy.reason_code,
            rationale=assessment.policy.rationale,
            evidence=assessment.evidence,
            policy_version=assessment.policy.policy_version,
            feature_snapshot_hash=assessment.snapshot.snapshot_hash,
            model_versions=assessment.model_versions,
            degraded_components=assessment.degraded_components,
            component_health=assessment.component_health,
            persisted=persisted,
            decided_at=assessment.decided_at,
            latency_ms=assessment.latency_ms,
        )
