"""Risk engine: the orchestration seam between features, components, fusion and policy.

Failure handling is the substance of this module. Each component is scored inside its own
try block; a failure marks that component ``UNAVAILABLE`` and removes it from the fusion
input, but never substitutes a value. The decision policy then sees exactly which
components were real and decides accordingly — which is how a degraded system stays safe
without inventing confidence.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

from app.core.ids import decision_id as new_decision_id
from app.core.logging import get_logger
from app.core.metrics import (
    METRICS,
    MODEL_ERRORS_TOTAL,
    RISK_DECISIONS_TOTAL,
    RISK_DEGRADED_TOTAL,
    RISK_LATENCY_MS,
    RISK_REQUESTS_TOTAL,
)
from app.core.versions import FEATURE_VERSION, GRAPH_VERSION, RULES_VERSION
from app.decision.policy import DecisionPolicy, PolicyDecision, default_policy
from app.features.context import RiskContext
from app.features.engine import COMPONENT_FEATURES, FeatureEngine, FeatureSnapshot
from app.intent.service import IntentAssessment, IntentService
from app.risk.evidence import (
    build_snapshot_evidence,
    component_evidence,
    rank_and_trim,
)
from app.risk.fusion import FusionOutput, fuse
from app.risk.models import ModelBundle
from app.risk.rules import RuleEngine, RuleResult
from app.schemas.entities import Transaction
from app.schemas.enums import ComponentStatus, Decision, EvidenceDirection, Severity, SignalSource
from app.schemas.risk import ComponentHealth, ComponentScores, RiskEvidence

log = get_logger(__name__)


@dataclass
class RiskAssessment:
    """Everything produced by one evaluation, ready to persist and to serialise."""

    decision_id: str
    transaction_id: str
    decision: Decision
    policy: PolicyDecision
    risk_score: float
    scores: ComponentScores
    evidence: list[RiskEvidence]
    snapshot: FeatureSnapshot
    rules: RuleResult
    intent: IntentAssessment | None
    fusion: FusionOutput
    component_health: list[ComponentHealth]
    model_versions: dict[str, str]
    decided_at: datetime
    latency_ms: float
    degraded_components: list[str] = field(default_factory=list)
    campaign_id: str | None = None
    case_id: str | None = None


class RiskEngine:
    """Scores a :class:`RiskContext` into a bounded, evidence-backed recommendation."""

    def __init__(
        self,
        feature_engine: FeatureEngine | None = None,
        rule_engine: RuleEngine | None = None,
        intent_service: IntentService | None = None,
        policy: DecisionPolicy | None = None,
        bundle: ModelBundle | None = None,
    ) -> None:
        self.feature_engine = feature_engine or FeatureEngine()
        self.rule_engine = rule_engine or RuleEngine()
        self.intent_service = intent_service or IntentService()
        self.policy = policy or default_policy()
        self.bundle = bundle

    # -- component scoring -------------------------------------------------------------

    def _score_ml_components(
        self, snapshot: FeatureSnapshot, health: list[ComponentHealth]
    ) -> dict[str, float | None]:
        scores: dict[str, float | None] = {
            "transaction_risk": None,
            "behavior_risk": None,
            "campaign_risk": None,
        }
        if self.bundle is None or not self.bundle.components:
            for name in scores:
                health.append(
                    ComponentHealth(
                        component=name,
                        status=ComponentStatus.UNAVAILABLE,
                        detail="no trained model bundle is loaded",
                        error_code="model_not_loaded",
                    )
                )
            return scores

        for name in scores:
            model = self.bundle.components.get(name)
            if model is None or not model.is_fitted:
                health.append(
                    ComponentHealth(
                        component=name, status=ComponentStatus.UNAVAILABLE,
                        detail="component model missing from bundle",
                        error_code="model_not_loaded",
                    )
                )
                continue
            try:
                row = snapshot.vector(model.feature_names or COMPONENT_FEATURES[name])
                value = float(model.score(np.asarray([row], dtype=float))[0])
                if not (0.0 <= value <= 1.0) or value != value:  # NaN-safe range check
                    raise ValueError(f"component produced an out-of-range score: {value}")
                scores[name] = value
                health.append(ComponentHealth(component=name, status=ComponentStatus.OK))
            except Exception as exc:
                METRICS.increment(MODEL_ERRORS_TOTAL, component=name)
                log.warning("component_scoring_failed", extra={"component": name, "error": str(exc)})
                health.append(
                    ComponentHealth(
                        component=name, status=ComponentStatus.UNAVAILABLE,
                        detail=str(exc)[:200], error_code="model_error",
                    )
                )
        return scores

    # -- main entry point --------------------------------------------------------------

    async def evaluate(
        self,
        ctx: RiskContext,
        transaction: Transaction,
        instruction_text: str | None = None,
        use_semantic: bool = True,
        decision_id: str | None = None,
    ) -> RiskAssessment:
        started = time.perf_counter()
        METRICS.increment(RISK_REQUESTS_TOTAL)
        health: list[ComponentHealth] = []

        snapshot = self.feature_engine.extract(ctx)
        for degraded in snapshot.degraded:
            health.append(
                ComponentHealth(
                    component=degraded, status=ComponentStatus.DEGRADED,
                    detail="feature group degraded during extraction",
                )
            )

        rules = self.rule_engine.evaluate(snapshot.values)
        health.append(ComponentHealth(component="rule_engine", status=ComponentStatus.OK))

        intent: IntentAssessment | None = None
        intent_deviation: float | None = None
        try:
            intent = await self.intent_service.assess(
                ctx=ctx,
                transaction=transaction,
                violations=snapshot.violations,
                instruction_text=instruction_text,
                use_semantic=use_semantic,
            )
            intent_deviation = intent.deviation
            health.append(
                ComponentHealth(
                    component="intent_engine",
                    status=intent.status,
                    detail=intent.detail,
                )
            )
        except Exception as exc:
            log.warning("intent_assessment_failed", extra={"error": str(exc)})
            health.append(
                ComponentHealth(
                    component="intent_engine", status=ComponentStatus.UNAVAILABLE,
                    detail=str(exc)[:200], error_code="intent_error",
                )
            )

        ml_scores = self._score_ml_components(snapshot, health)

        scores = ComponentScores(
            transaction_risk=ml_scores["transaction_risk"],
            behavior_risk=ml_scores["behavior_risk"],
            campaign_risk=ml_scores["campaign_risk"],
            intent_deviation=intent_deviation,
            rule_violation_score=rules.score,
        )

        fusion = fuse(scores, self.bundle.fusion if self.bundle else None)
        policy_decision = self.policy.decide(
            fusion.risk_score,
            violations=snapshot.violations,
            scores=scores,
            component_health=health,
        )

        evidence = build_snapshot_evidence(snapshot, rules)
        if intent:
            evidence.extend(intent.evidence)
        evidence.extend(component_evidence(fusion.contributions, scores.model_dump()))
        evidence.extend(self._degradation_evidence(health, fusion))
        evidence = rank_and_trim(evidence)

        degraded = sorted(
            {
                h.component
                for h in health
                if h.status in (ComponentStatus.DEGRADED, ComponentStatus.UNAVAILABLE)
            }
        )
        if degraded:
            METRICS.increment(RISK_DEGRADED_TOTAL)

        latency_ms = (time.perf_counter() - started) * 1000
        METRICS.observe(RISK_LATENCY_MS, latency_ms)
        METRICS.increment(RISK_DECISIONS_TOTAL, decision=str(policy_decision.decision))

        return RiskAssessment(
            decision_id=decision_id or new_decision_id(),
            transaction_id=transaction.transaction_id,
            decision=policy_decision.decision,
            policy=policy_decision,
            risk_score=round(fusion.risk_score, 6),
            scores=scores,
            evidence=evidence,
            snapshot=snapshot,
            rules=rules,
            intent=intent,
            fusion=fusion,
            component_health=health,
            model_versions=self._model_versions(fusion),
            decided_at=datetime.now(timezone.utc),
            latency_ms=round(latency_ms, 3),
            degraded_components=degraded,
        )

    @staticmethod
    def _degradation_evidence(
        health: list[ComponentHealth], fusion: FusionOutput
    ) -> list[RiskEvidence]:
        evidence: list[RiskEvidence] = []
        unavailable = [
            h for h in health
            if h.status in (ComponentStatus.DEGRADED, ComponentStatus.UNAVAILABLE)
        ]
        if unavailable:
            names = ", ".join(sorted(h.component for h in unavailable))
            evidence.append(
                RiskEvidence(
                    signal="degraded_components",
                    observed=(
                        f"the following components did not contribute a score: {names}. "
                        "Their scores were omitted rather than defaulted."
                    ),
                    severity=Severity.INFO,
                    source=SignalSource.POLICY_ENGINE,
                    direction=EvidenceDirection.NEUTRAL,
                )
            )
        if fusion.used_static_fallback:
            evidence.append(
                RiskEvidence(
                    signal="static_fusion_fallback",
                    observed=(
                        "no trained fusion model was loaded; the documented cold-start "
                        "weights were used and this score should be treated as provisional"
                    ),
                    severity=Severity.INFO,
                    source=SignalSource.POLICY_ENGINE,
                    direction=EvidenceDirection.NEUTRAL,
                )
            )
        return evidence

    def _model_versions(self, fusion: FusionOutput) -> dict[str, str]:
        versions = {
            "features": FEATURE_VERSION,
            "rules": RULES_VERSION,
            "graph": GRAPH_VERSION,
            "fusion": fusion.version,
            "semantic": getattr(self.intent_service.verifier, "model", "none"),
            "semantic_provider": getattr(self.intent_service.verifier, "provider", "null"),
        }
        if self.bundle:
            versions.update(self.bundle.versions())
        return versions
