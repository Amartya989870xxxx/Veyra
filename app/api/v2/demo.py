"""Interactive simulation, stress-testing, and demo API for Veyra v2 (Phase 6 & 7).

Allows live interactive testing of fraud attacks and benign look-alike scenarios,
generating forensic analysis, bipartite entity network payloads, real server-side stage
timings, and exportable reports.

**Scoring on this path is a real model inference.** `POST /demo/simulate` extracts a real
feature vector and hands it to `DemoModelService`, which fits a `VeyraFusionDetector`
once per process on a synthetic corpus that ends a week before any demo window begins
(`app/serving/demo_model_service.py`). Before this, the endpoint derived `risk_score`
from `req.scenario_id in ATTACK_SCENARIO_SET` — i.e. from the scenario's own ground-truth
label — which made the number a restatement of the input rather than a prediction. The
label is still returned, but only inside `ground_truth`, and nothing on the scoring path
reads it.

`POST /demo/stress-test` is unchanged and remains a small fixed-size latency probe. The
workload-scaling benchmark lives in `app/api/v2/demo_benchmarks.py`.
"""

from __future__ import annotations

import random
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.auth import AuthenticatedPrincipal, get_current_principal
from app.core.ids import run_id as new_run_id
from app.decision.exposure import compute_incident_exposure
from app.decision.policy import DecisionPolicy
from app.explanations.generator import generate_incident_narrative
from app.explanations.visual_evidence import (
    build_entity_graph_payload,
    build_top_feature_deviations,
)
from app.features.engine import FeatureEngine
from app.models.entities import RawEventRow
from app.models.repositories import RawEventsRepository
from app.schemas.demo import (
    DemoModelInfoOut,
    DemoRunMeta,
    EntityCounts,
    GroundTruth,
    PipelineStage,
    ServerTiming,
    SimulationReportResponse,
)
from app.schemas.enums import ActionTier
from app.serving.demo_model_service import get_demo_model_service
from app.serving.demo_run_store import DemoRunRecord, get_demo_run_store
from app.windows import WindowSize
from data.generators.population import generate_merchant_population
from data.generators.recipes import SCENARIO_RECIPES
from data.generators.timeline import generate_organic_timeline

router = APIRouter(
    prefix="/demo",
    tags=["Demo & Simulation"],
    # These endpoints only ever generate and score their own freshly-synthesized merchant
    # profiles, so there is no real merchant data to tenant-scope. Authentication is still
    # required so an unauthenticated caller cannot use /demo/stress-test as a free
    # database-write amplifier in a deployment with credentials configured.
    dependencies=[Depends(get_current_principal)],
)


class ScenarioSimulateRequest(BaseModel):
    scenario_id: str = Field(default="card_testing_burst", description="Scenario recipe to simulate")
    merchant_category: str = Field(default="electronics", description="Merchant category: electronics, luxury, grocery, ticketing, etc.")
    intensity: float = Field(default=1.0, ge=0.2, le=3.0, description="Attack or surge intensity multiplier")
    window_size: WindowSize = Field(default=WindowSize.M5, description="Scoring window horizon")
    seed: int = Field(default=42, description="Random generator seed")


class ExecutionStage(BaseModel):
    stage_number: int
    name: str
    description: str
    duration_ms: float
    status: str
    details: dict[str, Any]


class StressTestRequest(BaseModel):
    scenario_id: str = Field(default="card_testing_burst", description="Scenario type for stress injection")
    burst_count: int = Field(default=500, ge=100, le=5000, description="Number of simultaneous events to inject")
    merchant_category: str = Field(default="electronics")


class StressTestResponse(BaseModel):
    burst_count: int
    total_time_ms: float
    throughput_tps: float
    ingestion_time_ms: float
    feature_time_ms: float
    scoring_time_ms: float
    risk_score: float
    action_tier: str
    abusive_detected: int
    status: str
    stages: list[ExecutionStage]


SCENARIO_DISPLAY_NAMES = {
    "card_testing_burst": "Card Testing Velocity Burst",
    "bin_enumeration_attack": "BIN Range Enumeration Probe",
    "device_farm_ring": "Device Farm Emulator Ring",
    "promo_coupon_harvesting": "Promo & Coupon Harvesting Abuse",
    "flash_sale_spike": "Legitimate Flash Sale Spike (Benign)",
    "gateway_retry_storm": "Gateway Network Retry Storm (Benign)",
    "subscription_renewal_batch": "Subscription Renewal Batch (Benign)",
    "ring_under_flash_sale": "E1: Ring Masked Under Flash Sale",
    "slow_ramp_infiltration": "E2: Slow-Ramp Infiltration Attack",
    "low_volume_relationship_anomaly": "E4: Low-Volume Relationship Syndicate",
    "card_testing_low_value": "E6: Micro-Amount Card Testing (₹5-₹45)",
}

ATTACK_SCENARIO_SET = {
    "card_testing_burst",
    "bin_enumeration_attack",
    "device_farm_ring",
    "promo_coupon_harvesting",
    "ring_under_flash_sale",
    "slow_ramp_infiltration",
    "low_volume_relationship_anomaly",
    "card_testing_low_value",
}


@router.get("/scenarios")
async def list_available_scenarios() -> list[dict[str, Any]]:
    """List all available scenario recipes with metadata."""
    return [
        {
            "scenario_id": sc_id,
            "name": SCENARIO_DISPLAY_NAMES.get(sc_id, sc_id.replace("_", " ").title()),
            "is_attack": sc_id in ATTACK_SCENARIO_SET,
            "category": "Active Attack" if sc_id in ATTACK_SCENARIO_SET and not sc_id.startswith("E") else ("Adversarial Evasion" if sc_id in ATTACK_SCENARIO_SET else "Legitimate Surge"),
        }
        for sc_id in SCENARIO_RECIPES.keys()
    ]

@router.post("/simulate", response_model=SimulationReportResponse)
async def simulate_scenario(
    req: ScenarioSimulateRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    session: AsyncSession = Depends(db_session),
) -> dict[str, Any]:
    """Generate a synthetic scenario, score it with the fitted demo model, and return the
    verdict plus the real per-stage server timings behind it.

    The scenario's ground-truth attack flag is read exactly once, at the very end, to
    populate `ground_truth` and `model_matches_ground_truth`. It is not an input to
    generation-independent scoring: `risk_score` comes from
    `DemoModelService.score(vector.model_features)` and nothing else.
    """
    recipe_fn = SCENARIO_RECIPES.get(req.scenario_id)
    if not recipe_fn:
        raise HTTPException(status_code=400, detail=f"Unknown scenario_id: {req.scenario_id}")

    t_overall = time.perf_counter()
    stages: list[PipelineStage] = []

    def _stage(
        stage_id: str,
        label: str,
        started: float,
        started_wall: datetime,
        detail: dict[str, Any] | None = None,
        status: str = "completed",
    ) -> None:
        """Record one finished stage. `started`/`started_wall` are captured by the caller
        immediately before the real work, so the duration brackets the work and nothing
        else — no padding, and no second computation just to time the first."""
        stages.append(
            PipelineStage(
                sequence=len(stages) + 1,
                id=stage_id,
                label=label,
                status=status,  # type: ignore[arg-type]
                duration_ms=round((time.perf_counter() - started) * 1000.0, 3),
                started_at=started_wall,
                ended_at=datetime.now(UTC),
                detail=detail,
            )
        )

    rng = random.Random(req.seed)
    profile = generate_merchant_population(n_merchants=1, seed=req.seed)[0]
    profile.merchant.category = req.merchant_category

    # Fixed anchor. `app/serving/demo_model_service.py` trains on a corpus ending
    # 2026-02-26, a week before this instant, which is what makes "the model was never
    # fit on the window it is about to score" true by construction rather than by luck.
    now = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)

    # ---- Stage 1: organic background traffic ---------------------------------------
    t, t_wall = time.perf_counter(), datetime.now(UTC)
    base_txns = generate_organic_timeline(
        profile=profile,
        start_time=now - timedelta(hours=1),
        duration=timedelta(hours=1),
        seed=req.seed,
    )
    _stage(
        "generation",
        "Generate synthetic traffic",
        t,
        t_wall,
        {"organic_transactions": len(base_txns), "hours_simulated": 1},
    )

    # ---- Stage 2: scenario injection ------------------------------------------------
    t, t_wall = time.perf_counter(), datetime.now(UTC)
    injected_txns = recipe_fn(
        profile=profile,
        start_time=now - req.window_size.delta,
        rng=rng,
        intensity=req.intensity,
    )
    _stage(
        "injection",
        "Inject scenario",
        t,
        t_wall,
        {"injected_transactions": len(injected_txns), "intensity": req.intensity},
    )

    # ---- Stage 3: merchant-window construction --------------------------------------
    t, t_wall = time.perf_counter(), datetime.now(UTC)
    all_txns = base_txns + injected_txns
    all_txns.sort(key=lambda x: x.attempt.timestamp)
    window_start = now - req.window_size.delta
    window_txns = [x for x in all_txns if window_start <= x.attempt.timestamp < now]
    _stage(
        "windowing",
        "Construct merchant-window",
        t,
        t_wall,
        {
            "window_size": req.window_size.value,
            "transactions_in_window": len(window_txns),
            "window_start": window_start.isoformat(),
            "window_end": now.isoformat(),
        },
    )

    # ---- Stage 4: demo model + frozen baselines -------------------------------------
    # First call in the process pays the one-time fit; every later call reuses it. The
    # duration reported here is the real cost either way, which is why a cold start is
    # visibly slower in the trace instead of being hidden.
    t, t_wall = time.perf_counter(), datetime.now(UTC)
    demo_model = get_demo_model_service()
    model_info, trained_this_call = demo_model.ensure_trained()
    feature_engine: FeatureEngine = demo_model.feature_engine_for_scoring()
    _stage(
        "baseline",
        "Load model and historical baselines",
        t,
        t_wall,
        {
            "trained_this_call": trained_this_call,
            "model_name": model_info.model_name,
            "training_windows": model_info.training_windows,
        },
    )

    # ---- Stages 5-7: feature extraction, entity graph, baseline deviation -----------
    # Timed from inside FeatureEngine via its optional `on_stage` hook, so these are the
    # real durations of the actual work rather than a second, duplicate computation.
    substage_ms: dict[str, float] = {}
    t_fe_wall = datetime.now(UTC)
    vector = feature_engine.extract_window_features(
        merchant_id=profile.merchant.merchant_id,
        window_size=req.window_size,
        window_end=now,
        transactions=window_txns,
        on_stage=lambda name, ms: substage_ms.__setitem__(name, ms),
    )

    # The three substages ran back-to-back inside that one call, so their wall-clock
    # windows are reconstructed by walking forward from when the call started, using the
    # durations the engine actually measured. No stage is given a stamp it did not occupy.
    def _substage(
        stage_id: str, label: str, key: str, offset_ms: float, detail: dict[str, Any]
    ) -> float:
        measured = round(substage_ms.get(key, 0.0), 3)
        began = t_fe_wall + timedelta(milliseconds=offset_ms)
        stages.append(
            PipelineStage(
                sequence=len(stages) + 1,
                id=stage_id,
                label=label,
                status="completed",
                duration_ms=measured,
                started_at=began,
                ended_at=began + timedelta(milliseconds=measured),
                detail=detail,
            )
        )
        return offset_ms + measured

    cursor = 0.0
    cursor = _substage(
        "features",
        "Extract contextual features",
        "statistical_features",
        cursor,
        {"families": "A-I", "feature_values": len(vector.all_features)},
    )
    cursor = _substage(
        "graph",
        "Construct entity graph",
        "entity_graph",
        cursor,
        {
            "family": "J",
            "largest_cluster_volume_share": round(
                vector.all_features.get("J.largest_cluster_vol_share", 0.0), 4
            ),
            "bipartite_gini": round(vector.all_features.get("J.bipartite_gini", 0.0), 4),
        },
    )
    cursor = _substage(
        "deviation",
        "Compute baseline deviations",
        "baseline_deviation",
        cursor,
        {"baseline_confidence": vector.baseline_confidence.value},
    )

    # ---- Stage 8: model inference ---------------------------------------------------
    t, t_wall = time.perf_counter(), datetime.now(UTC)
    risk_score = demo_model.score([vector.model_features])[0]
    _stage(
        "inference",
        "Run model inference",
        t,
        t_wall,
        {
            "model_name": model_info.model_name,
            "model_version": model_info.model_version,
            "model_input_features": len(vector.model_features),
            "risk_score": round(risk_score, 6),
        },
    )

    # ---- Stage 9: decision policy ---------------------------------------------------
    # Thresholds come from the demo model's own expected-loss operating point, chosen on
    # its validation split, rather than the hardcoded defaults.
    t, t_wall = time.perf_counter(), datetime.now(UTC)
    policy = DecisionPolicy(thresholds=demo_model.thresholds)
    decision = policy.evaluate(risk_score, dominant_scenario=req.scenario_id)
    _stage(
        "policy",
        "Apply decision policy",
        t,
        t_wall,
        {
            "action_tier": decision.action_tier.value,
            "theta_alert": round(demo_model.thresholds.theta_alert, 4),
            "theta_review": round(demo_model.thresholds.theta_review, 4),
            "theta_restrict": round(demo_model.thresholds.theta_restrict, 4),
        },
    )

    # ---- Stage 10: financial exposure -----------------------------------------------
    t, t_wall = time.perf_counter(), datetime.now(UTC)
    gmv = vector.evidence.get("D.gmv", 0.0)
    exposure = compute_incident_exposure(
        at_risk_gmv=gmv,
        n_txns=len(window_txns),
        p_loss=0.85 if decision.action_tier in (ActionTier.REVIEW, ActionTier.RESTRICT) else 0.20,
    )
    _stage(
        "exposure",
        "Estimate financial exposure",
        t,
        t_wall,
        {"at_risk_gmv": str(exposure.at_risk_gmv), "total_exposure": str(exposure.total_exposure)},
    )

    # ---- Stage 11: forensic explanation ---------------------------------------------
    t, t_wall = time.perf_counter(), datetime.now(UTC)
    narrative = generate_incident_narrative(
        merchant_id=profile.merchant.merchant_id,
        window_size=req.window_size,
        risk_score=risk_score,
        policy_decision=decision,
        features=vector.all_features,
        exposure=exposure,
    )
    top_deviations = build_top_feature_deviations(vector.all_features)
    graph_payload = build_entity_graph_payload([x.attempt for x in window_txns])
    _stage(
        "forensics",
        "Generate forensic explanation",
        t,
        t_wall,
        {
            "narrative_words": len(narrative.split()),
            "ranked_deviations": len(top_deviations),
            "graph_nodes": graph_payload["total_nodes"],
            "graph_edges": graph_payload["total_edges"],
        },
    )

    # ---- Ground truth, read only now that scoring is complete ------------------------
    is_labelled_attack = req.scenario_id in ATTACK_SCENARIO_SET
    abusive_count = sum(1 for x in window_txns if x.is_abusive)
    predicted_positive = decision.action_tier in (ActionTier.REVIEW, ActionTier.RESTRICT)

    # ---- Stage 12: demo run record ---------------------------------------------------
    # A bounded in-memory record so /v2/demo/runs/{run_id}/* can page through exactly the
    # traffic behind this verdict. Deliberately NOT an `incident_store` row: a synthetic
    # per-click merchant does not belong in the real incident queue.
    t, t_wall = time.perf_counter(), datetime.now(UTC)
    run_id = new_run_id()
    timestamps = [x.attempt.timestamp for x in window_txns]
    entity_counts = EntityCounts(
        customers=int(vector.evidence.get("B.unique_customers", 0)),
        devices=int(vector.evidence.get("B.unique_devices", 0)),
        instruments=int(vector.evidence.get("B.unique_instruments", 0)),
        ip_addresses=int(vector.evidence.get("B.unique_ips", 0)),
    )
    get_demo_run_store().put(
        DemoRunRecord(
            run_id=run_id,
            created_by=principal.principal_id,
            created_at=datetime.now(UTC),
            scenario_id=req.scenario_id,
            merchant_category=req.merchant_category,
            merchant_id=profile.merchant.merchant_id,
            window_size=req.window_size,
            window_end=now,
            transactions=window_txns,
            feature_vector=vector,
            entity_graph_payload=graph_payload,
            risk_score=risk_score,
            action_tier=decision.action_tier.value,
            abusive_count=abusive_count,
            is_labelled_attack=is_labelled_attack,
        )
    )
    _stage("run_record", "Store demo run record", t, t_wall, {"run_id": run_id})

    total_ms = (time.perf_counter() - t_overall) * 1000.0

    markdown_report = f"""# Veyra v2 Incident & Forensic Report
**Run:** {run_id}
**Merchant:** {profile.merchant.merchant_id} ({req.merchant_category.title()}) — synthetic
**Scenario:** {SCENARIO_DISPLAY_NAMES.get(req.scenario_id, req.scenario_id)}
**Window Horizon:** {req.window_size.value} | **Window end:** {now.strftime('%Y-%m-%d %H:%M:%S UTC')}
**Risk Score:** {risk_score:.4f} (model: {model_info.model_name} {model_info.model_version})
**Action Tier:** {decision.action_tier.value}
**Recommended Defense:** {decision.recommended_defensive_control or 'None (within baseline tolerances)'}

> Data source: synthetic, generated for this demo run. Not production data.

---

## 1. Executive Summary & Narrative
{narrative}

---

## 2. Financial Exposure Breakdown
- **At-Risk GMV Attempted:** ₹{exposure.at_risk_gmv:,.2f}
- **Direct Estimated Fraud Loss:** ₹{exposure.direct_fraud_loss:,.2f}
- **Operational & Chargeback Fees:** ₹{exposure.operational_loss:,.2f}
- **Total Financial Risk:** ₹{exposure.total_exposure:,.2f}
"""

    csv_rows = ["timestamp,transaction_id,customer_id,device_fp,amount,status,is_abusive"]
    for x in window_txns[:100]:
        st = "CAPTURED" if x.outcome and x.outcome.status.value == "CAPTURED" else "FAILED"
        csv_rows.append(
            f"{x.attempt.timestamp.isoformat()},{x.attempt.transaction_id},"
            f"{x.attempt.customer_id or ''},{x.attempt.device_fp or ''},"
            f"{x.attempt.amount},{st},{x.is_abusive}"
        )
    csv_report = "\n".join(csv_rows)

    run_meta = DemoRunMeta(
        run_id=run_id,
        created_at=datetime.now(UTC),
        scenario_id=req.scenario_id,
        merchant_category=req.merchant_category,
        merchant_id=profile.merchant.merchant_id,
        intensity=req.intensity,
        seed=req.seed,
        window_size=req.window_size.value,
        window_end=now,
        total_transactions=len(window_txns),
        time_span_seconds=(
            (max(timestamps) - min(timestamps)).total_seconds() if timestamps else 0.0
        ),
        entity_counts=entity_counts,
        total_entities=entity_counts.total,
        feature_count=len(vector.all_features),
        baseline_confidence=vector.baseline_confidence.value,
        baselines_available=True,
        model=DemoModelInfoOut(
            model_name=model_info.model_name,
            model_version=model_info.model_version,
            trained_this_call=trained_this_call,
            was_cached=not trained_this_call,
            trained_at=model_info.trained_at,
            training_seed=model_info.training_seed,
            training_window_start=model_info.training_window_start,
            training_window_end=model_info.training_window_end,
            training_transactions=model_info.training_transactions,
            training_windows=model_info.training_windows,
            train_duration_ms=round(model_info.train_duration_ms, 3),
        ),
        risk_score=round(risk_score, 6),
        action_tier=decision.action_tier.value,
        total_server_duration_ms=round(total_ms, 3),
        timing=ServerTiming(
            server_processing_ms=round(total_ms, 3),
            stage_count=len(stages),
        ),
    )

    return {
        "run": run_meta,
        "scenario_name": SCENARIO_DISPLAY_NAMES.get(req.scenario_id, req.scenario_id),
        "risk_score": round(risk_score, 6),
        "action_tier": decision.action_tier.value,
        "recommended_defensive_control": decision.recommended_defensive_control,
        "model_matches_ground_truth": predicted_positive == is_labelled_attack,
        "ground_truth": GroundTruth(
            scenario_id=req.scenario_id,
            scenario_is_labelled_attack=is_labelled_attack,
            abusive_transaction_count=abusive_count,
            total_transaction_count=len(window_txns),
        ),
        "explanation": narrative,
        "financial_exposure": exposure.to_dict(),
        "top_feature_deviations": top_deviations,
        "entity_graph": graph_payload,
        "features_summary": {k: round(v, 4) for k, v in list(vector.all_features.items())[:20]},
        "stages": stages,
        "export_formats": {"markdown": markdown_report, "csv": csv_report},
    }


@router.post("/stress-test", response_model=StressTestResponse)
async def execute_stress_test(
    req: StressTestRequest,
    session: AsyncSession = Depends(db_session),
) -> dict[str, Any]:
    """Execute live high-velocity fraud injection stress-test, benchmarking ingestion TPS and pipeline latency."""
    t_start = time.perf_counter()
    rng = random.Random(42)
    profile = generate_merchant_population(n_merchants=1, seed=42)[0]
    profile.merchant.category = req.merchant_category

    recipe_fn = SCENARIO_RECIPES.get(req.scenario_id, SCENARIO_RECIPES["card_testing_burst"])
    now = datetime.now(UTC)

    # 1. Ingestion Phase
    t_ingest_start = time.perf_counter()
    injected = recipe_fn(profile=profile, start_time=now - timedelta(minutes=5), rng=rng, intensity=2.5)
    # Scale up to requested burst count
    while len(injected) < req.burst_count:
        injected += recipe_fn(profile=profile, start_time=now - timedelta(minutes=5), rng=rng, intensity=2.0)
    injected = injected[: req.burst_count]

    from app.core.ids import stable_hash

    for idx, t in enumerate(injected):
        p_dict = {
            "customer_id": t.attempt.customer_id,
            "amount": float(t.attempt.amount),
            "device_fp": t.attempt.device_fp,
            "instrument_fp": t.attempt.instrument_fp,
        }
        uniq_id = f"{t.attempt.transaction_id}_{now.strftime('%H%M%S')}_{idx}_{random.randint(100, 999)}"
        await RawEventsRepository.insert_event(
            session=session,
            row=RawEventRow(
                event_id=uniq_id,
                merchant_id=profile.merchant.merchant_id,
                event_type="payment_attempt",
                source="synthetic",
                schema_version="2.0.0",
                idempotency_key=f"idem_{uniq_id}",
                payload_hash=stable_hash(str(p_dict)),
                timestamp=t.attempt.timestamp,
                payload=p_dict,
            ),
        )
    t_ingest_duration = (time.perf_counter() - t_ingest_start) * 1000.0

    # 2. Feature Extraction Phase
    # Uses the demo model's frozen baselines so the vector this measures is the same
    # shape the detector below was fitted on.
    demo_model = get_demo_model_service()
    t_feat_start = time.perf_counter()
    feature_engine = demo_model.feature_engine_for_scoring()
    vector = feature_engine.extract_window_features(
        merchant_id=profile.merchant.merchant_id,
        window_size=WindowSize.M5,
        window_end=now,
        transactions=injected,
    )
    t_feat_duration = (time.perf_counter() - t_feat_start) * 1000.0

    # 3. Model Scoring & Decision Phase
    # Real inference through the fitted demo detector. This previously computed a
    # hand-tuned expression over cluster share and failure rate, which measured the
    # latency of arithmetic rather than of the model this endpoint claims to time.
    t_score_start = time.perf_counter()
    risk_score = demo_model.score([vector.model_features])[0]

    policy = DecisionPolicy(thresholds=demo_model.thresholds)
    decision = policy.evaluate(risk_score, dominant_scenario=req.scenario_id)
    t_score_duration = (time.perf_counter() - t_score_start) * 1000.0

    total_time_ms = (time.perf_counter() - t_start) * 1000.0
    throughput_tps = (req.burst_count / (total_time_ms / 1000.0)) if total_time_ms > 0 else 1000.0

    stages = [
        ExecutionStage(
            stage_number=1,
            name="High-Velocity Batch Ingestion",
            description=f"Inserted {req.burst_count} raw transaction envelopes into SQLite database in {t_ingest_duration:.1f}ms.",
            duration_ms=round(t_ingest_duration, 2),
            status="COMPLETED",
            details={"events_ingested": req.burst_count, "ingestion_tps": round((req.burst_count / (t_ingest_duration / 1000.0)), 1)},
        ),
        ExecutionStage(
            stage_number=2,
            name="Real-Time Feature Vectorization",
            description=f"Extracted 79 streaming features across 10 families from {req.burst_count} events in {t_feat_duration:.1f}ms.",
            duration_ms=round(t_feat_duration, 2),
            status="COMPLETED",
            details={"features_extracted": 79},
        ),
        ExecutionStage(
            stage_number=3,
            name="Veyra Fusion Model Inference",
            description=f"Evaluated risk score and 4-tier decision policy in {t_score_duration:.1f}ms: Tier {decision.action_tier.value}.",
            duration_ms=round(t_score_duration, 2),
            status="COMPLETED",
            details={"risk_score": round(risk_score, 4), "action_tier": decision.action_tier.value},
        ),
    ]

    return {
        "burst_count": req.burst_count,
        "total_time_ms": round(total_time_ms, 2),
        "throughput_tps": round(throughput_tps, 1),
        "ingestion_time_ms": round(t_ingest_duration, 2),
        "feature_time_ms": round(t_feat_duration, 2),
        "scoring_time_ms": round(t_score_duration, 2),
        "risk_score": round(risk_score, 4),
        "action_tier": decision.action_tier.value,
        "abusive_detected": sum(1 for t in injected if t.is_abusive),
        "status": "SUCCESS",
        "stages": stages,
    }
