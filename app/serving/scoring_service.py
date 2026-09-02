"""End-to-end online scoring service for Veyra v2 (Phase 6.1).

Coordinates:
- Past-only transaction slicing
- Feature extraction & robust baseline deviations
- Veyra Fusion ML model scoring
- 4-Tier decision policy & recommended defensive controls
- Financial exposure calculation
- Natural-language narrative & visual evidence generation
- Atomic persistence to FeatureStore and IncidentStore
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Sequence
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id, scoped_incident_id
from app.decision.exposure import IncidentExposure, compute_incident_exposure
from app.decision.policy import DecisionPolicy, PolicyDecision
from app.explanations.generator import generate_incident_narrative
from app.explanations.visual_evidence import (
    build_entity_graph_payload,
    build_top_feature_deviations,
)
from app.features.baselines import build_baseline_engine_from_rows
from app.features.engine import FeatureEngine
from app.models.entities import FeatureStoreRow, IncidentStoreRow
from app.models.repositories import (
    BaselineStoreRepository,
    FeatureStoreRepository,
    IncidentStoreRepository,
    RawEventsRepository,
)
from app.models_ml.fusion import VeyraFusionDetector
from app.schemas.entities import PaymentAttempt
from app.schemas.enums import ActionTier, IncidentStatus, Severity
from app.windows import WindowSize, align_to_grid


@dataclass
class ScoreWindowResponse:
    merchant_id: str
    window_size: str
    window_end: datetime
    risk_score: float
    action_tier: ActionTier
    recommended_defensive_control: str | None
    incident_id: str | None
    financial_exposure: dict[str, Any]
    explanation: str
    top_feature_deviations: list[dict[str, Any]]
    entity_graph: dict[str, Any]
    baseline_confidence: str
    model_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "merchant_id": self.merchant_id,
            "window_size": self.window_size,
            "window_end": self.window_end.isoformat(),
            "risk_score": round(self.risk_score, 4),
            "action_tier": self.action_tier.value,
            "recommended_defensive_control": self.recommended_defensive_control,
            "incident_id": self.incident_id,
            "financial_exposure": self.financial_exposure,
            "explanation": self.explanation,
            "top_feature_deviations": self.top_feature_deviations,
            "entity_graph": self.entity_graph,
            "baseline_confidence": self.baseline_confidence,
            "model_version": self.model_version,
        }


class ScoringService:
    """Production online scoring pipeline."""

    def __init__(
        self,
        feature_engine: FeatureEngine | None = None,
        detector: VeyraFusionDetector | None = None,
        policy: DecisionPolicy | None = None,
        model_version: str = "v2.0.0-fusion",
        load_persisted_baselines: bool = True,
    ) -> None:
        self.feature_engine = feature_engine
        self.detector = detector or VeyraFusionDetector()
        self.policy = policy or DecisionPolicy()
        self.model_version = model_version
        self.load_persisted_baselines = load_persisted_baselines and feature_engine is None
        """Load this merchant's frozen MAD baselines from `baseline_store` at scoring time.

        Online scoring is the "apply unchanged" end of the contract: parameters are
        fitted offline on training history and written to `baseline_store` (with their
        fit period), and this path only ever reads them. It never recomputes a baseline
        from the traffic it is scoring, so a merchant under attack cannot move its own
        definition of normal. A merchant with no persisted baselines scores against an
        empty engine exactly as before — deviation twins degrade to raw values and
        `baseline_confidence` reports LOW, rather than the request failing.

        Disabled automatically when an explicit `feature_engine` is injected, so callers
        that supply their own baselines (tests, the evaluation runner) keep control.
        """

    async def _resolve_feature_engine(
        self,
        session: AsyncSession,
        merchant_id: str,
    ) -> FeatureEngine:
        """The feature engine for this request, with frozen baselines if any exist."""
        if self.feature_engine is not None:
            return self.feature_engine
        if not self.load_persisted_baselines:
            return FeatureEngine()

        rows = await BaselineStoreRepository.list_for_merchant(session, merchant_id)
        if not rows:
            # No fitted history for this merchant yet (cold start). Scoring proceeds
            # against an empty engine and reports LOW baseline confidence rather than
            # failing the request or inventing a baseline from the current traffic.
            return FeatureEngine()
        return FeatureEngine(baseline_engine=build_baseline_engine_from_rows(rows))

    async def score_window(
        self,
        session: AsyncSession,
        merchant_id: str,
        window_size: WindowSize,
        window_end: datetime | None = None,
        in_memory_transactions: Sequence[PaymentAttempt] | None = None,
    ) -> ScoreWindowResponse:
        # 1. Align window end to 60s scoring grid
        w_end = window_end or datetime.now(UTC)
        w_end = align_to_grid(w_end)
        w_start = w_end - window_size.delta

        # 2. Slices events strictly past-only in [w_start, w_end)
        transactions: list[PaymentAttempt] = []
        if in_memory_transactions is not None:
            transactions = [
                t for t in in_memory_transactions
                if w_start <= t.timestamp < w_end and t.merchant_id == merchant_id
            ]
        else:
            raw_rows = await RawEventsRepository.list_events_for_merchant(
                session=session,
                merchant_id=merchant_id,
                start_ts=w_start,
                end_ts=w_end,
            )
            for row in raw_rows:
                # Reconstruct lightweight attempt representation for scoring
                payload = row.payload
                attempt = PaymentAttempt(
                    transaction_id=payload.get("transaction_id", row.event_id),
                    merchant_id=merchant_id,
                    customer_id=payload.get("customer_id"),
                    order_id=payload.get("order_id"),
                    instrument_fp=payload.get("instrument_fp", "if_unknown"),
                    device_fp=payload.get("device_fp"),
                    ip_fp=payload.get("ip_fp"),
                    amount=Decimal(str(payload.get("amount", 0.0))),
                    currency=payload.get("currency", "INR"),
                    timestamp=row.timestamp,
                )
                transactions.append(attempt)

        # 3. Extract complete feature vector, against this merchant's frozen baselines
        feature_engine = await self._resolve_feature_engine(session, merchant_id)
        vector = feature_engine.extract_window_features(
            merchant_id=merchant_id,
            window_size=window_size,
            window_end=w_end,
            transactions=transactions,
        )

        # 4. Predict risk probability via Veyra Fusion
        if self.detector.is_fitted:
            prob_arr = self.detector.predict_proba([vector.model_features])
            risk_score = float(prob_arr[0])
        else:
            # Calibrated fallback based on volume deviation + cluster concentration
            vol_dev = vector.all_features.get("A.txn_rate_dev", 0.0)
            cluster_vol = vector.all_features.get("J.largest_cluster_vol_share", 0.0)
            base_p = 1.0 / (1.0 + 2.718 ** (-0.5 * (vol_dev - 3.0))) if vol_dev > 0 else 0.05
            risk_score = float(min(1.0, base_p + cluster_vol * 0.4))

        # 5. Evaluate Decision Policy (ADR-006)
        decision = self.policy.evaluate(risk_score)

        # 6. Calculate Financial Exposure
        gmv = vector.evidence.get("D.gmv", 0.0)
        n_txns = len(transactions)
        exposure = compute_incident_exposure(
            at_risk_gmv=gmv,
            n_txns=n_txns,
            p_loss=0.85 if decision.action_tier in (ActionTier.REVIEW, ActionTier.RESTRICT) else 0.20,
        )

        # 7. Generate Explanations and Visual Evidence
        narrative = generate_incident_narrative(
            merchant_id=merchant_id,
            window_size=window_size,
            risk_score=risk_score,
            policy_decision=decision,
            features=vector.all_features,
            exposure=exposure,
        )
        top_deviations = build_top_feature_deviations(vector.all_features)
        graph_payload = build_entity_graph_payload(transactions)

        # 8. Persist to FeatureStoreRow
        await FeatureStoreRepository.save_window_features(
            session=session,
            merchant_id=merchant_id,
            window_size=window_size.value,
            window_end=w_end,
            features=vector.all_features,
            evidence=vector.evidence,
        )

        # 9. Create Incident if ActionTier is REVIEW or RESTRICT
        inc_id: str | None = None
        if decision.action_tier in (ActionTier.REVIEW, ActionTier.RESTRICT):
            inc_id = scoped_incident_id(merchant_id, "spike", w_end)
            sev = Severity.HIGH.value if decision.action_tier is ActionTier.RESTRICT else Severity.MEDIUM.value
            await IncidentStoreRepository.create_or_update_incident(
                session=session,
                row=IncidentStoreRow(
                    incident_id=inc_id,
                    merchant_id=merchant_id,
                    first_flag_time=w_start,
                    last_flag_time=w_end,
                    window_sizes=[window_size.value],
                    severity=sev,
                    status=IncidentStatus.OPEN.value,
                    action_tier=decision.action_tier.value,
                    risk_score=risk_score,
                    exposure_amount=Decimal(str(exposure.total_exposure)),
                    explanation=narrative,
                    evidence={
                        "narrative": narrative,
                        "exposure": exposure.to_dict(),
                        "top_deviations": top_deviations,
                        "entity_graph": graph_payload,
                        "recommended_control": decision.recommended_defensive_control,
                    },
                ),
            )

        return ScoreWindowResponse(
            merchant_id=merchant_id,
            window_size=window_size.value,
            window_end=w_end,
            risk_score=risk_score,
            action_tier=decision.action_tier,
            recommended_defensive_control=decision.recommended_defensive_control,
            incident_id=inc_id,
            financial_exposure=exposure.to_dict(),
            explanation=narrative,
            top_feature_deviations=top_deviations,
            entity_graph=graph_payload,
            baseline_confidence=vector.baseline_confidence.value,
            model_version=self.model_version,
        )
