"""Workload-scaling benchmark API (Parts 3 & 4).

Run-based rather than one long synchronous request: `POST` returns a `run_id` and the
work proceeds on a single background worker, so a 1,000,000-event run does not depend on
a browser holding a connection open for its whole duration. The frontend polls.

    POST /v2/demo/benchmarks              -> { run_id, status, planned_executed_size, capped, ... }
    GET  /v2/demo/benchmarks/{run_id}     -> full run: status + result when finished
    GET  /v2/demo/benchmarks/{run_id}/progress -> latest stage/percent only
    GET  /v2/demo/benchmarks              -> recent runs held in the bounded registry

The heavy lifting, the guardrails and the honest-reporting rules live in
`app/serving/benchmark_service.py`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import AuthenticatedPrincipal, get_current_principal
from app.core.config import get_settings
from app.core.ids import run_id as new_run_id
from app.schemas.benchmark import (
    TERMINAL_STATUSES,
    WORKLOAD_PRESETS,
    BenchmarkCreateRequest,
    BenchmarkCreateResponse,
    BenchmarkGuardrails,
    BenchmarkListResponse,
    BenchmarkModeOption,
    BenchmarkPresetsResponse,
    BenchmarkProgressResponse,
    BenchmarkRun,
    BenchmarkStatus,
    ScenarioMixOption,
    WorkloadPreset,
    tier_for,
)
from app.serving.benchmark_service import get_benchmark_store, submit_benchmark

router = APIRouter(
    prefix="/demo/benchmarks",
    tags=["Demo Benchmarks"],
    dependencies=[Depends(get_current_principal)],
)


@router.get("/presets", response_model=BenchmarkPresetsResponse)
async def list_workload_presets() -> BenchmarkPresetsResponse:
    """The workload sizes the UI offers, their tier, and this server's actual ceiling."""
    settings = get_settings()
    return BenchmarkPresetsResponse(
        presets=[
            WorkloadPreset(
                workload_size=size,
                label=f"{size // 1_000}K" if size < 1_000_000 else f"{size // 1_000_000}M",
                tier=tier_for(size),
                will_be_capped=size > settings.benchmark_hard_cap_events,
                executed_size_if_requested=min(size, settings.benchmark_hard_cap_events),
            )
            for size in WORKLOAD_PRESETS
        ],
        scenario_mixes=[
            ScenarioMixOption(id="all_legit", label="100% legitimate", fraud_ratio=0.0),
            ScenarioMixOption(
                id="legit_90_fraud_10", label="90% legit / 10% fraud", fraud_ratio=0.10
            ),
            ScenarioMixOption(id="mixed_50_50", label="50% / 50%", fraud_ratio=0.50),
            ScenarioMixOption(
                id="fraud_90_legit_10", label="10% legit / 90% fraud", fraud_ratio=0.90
            ),
            ScenarioMixOption(id="all_fraud", label="100% fraud", fraud_ratio=1.0),
            ScenarioMixOption(id="custom", label="Custom ratio", fraud_ratio=None),
        ],
        modes=[
            BenchmarkModeOption(id="ingestion", label="Ingestion / write scale"),
            BenchmarkModeOption(
                id="pipeline", label="Ingestion + detection / computation scale"
            ),
        ],
        guardrails=BenchmarkGuardrails(
            hard_cap_events=settings.benchmark_hard_cap_events,
            max_seconds=settings.benchmark_max_seconds,
            chunk_size=settings.benchmark_chunk_size,
            max_sample_windows=settings.benchmark_max_sample_windows,
            concurrent_jobs=1,
            sample_rows_per_bucket=settings.benchmark_sample_rows,
            allow_experimental=settings.benchmark_allow_experimental,
        ),
        notice=(
            "Workloads above the hard cap are executed at the cap and reported as capped. "
            "No result is extrapolated to a size that was not actually run."
        ),
    )


@router.post("", response_model=BenchmarkCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_benchmark(
    req: BenchmarkCreateRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> BenchmarkCreateResponse:
    """Queue a benchmark run and return immediately with its id."""
    settings = get_settings()
    tier = tier_for(req.workload_size)

    if tier == "experimental" and not settings.benchmark_allow_experimental:
        # Refused before any work starts, so nothing is generated and no run record is
        # created. This is the one path that produces status "rejected".
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "status": "rejected",
                "reason": "experimental_workloads_disabled",
                "message": (
                    f"Workload of {req.workload_size:,} events is experimental tier, and this "
                    "server has experimental workloads disabled "
                    "(VEYRA_BENCHMARK_ALLOW_EXPERIMENTAL=false). Nothing was executed."
                ),
                "requested_workload_size": req.workload_size,
                "workload_tier": tier,
            },
        )

    planned = min(req.workload_size, settings.benchmark_hard_cap_events)
    capped = planned < req.workload_size

    run_id = new_run_id()
    submit_benchmark(run_id, req)

    notice = (
        f"Requested {req.workload_size:,} events; this environment's ceiling is "
        f"{settings.benchmark_hard_cap_events:,}, so {planned:,} will actually be executed and the "
        "result will be marked capped. Nothing is extrapolated to the requested size."
        if capped
        else (
            f"Executing {planned:,} events. Results are measured server-side and are not "
            "production capacity figures."
        )
    )

    return BenchmarkCreateResponse(
        run_id=run_id,
        status="queued",
        workload_tier=tier,
        requested_workload_size=req.workload_size,
        planned_executed_size=planned,
        capped=capped,
        poll={
            "run": f"/v2/demo/benchmarks/{run_id}",
            "progress": f"/v2/demo/benchmarks/{run_id}/progress",
        },
        notice=notice,
    )


@router.get("/{run_id}/progress", response_model=BenchmarkProgressResponse)
async def get_benchmark_progress(run_id: str) -> BenchmarkProgressResponse:
    """Latest progress snapshot only — cheap enough to poll on a short interval."""
    run = get_benchmark_store().get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Benchmark run '{run_id}' not found")
    run_status: BenchmarkStatus = run.status
    return BenchmarkProgressResponse(
        run_id=run.run_id,
        status=run_status,
        progress=run.progress,
        finished=run_status in TERMINAL_STATUSES,
        error=run.error,
    )


@router.get("/{run_id}", response_model=BenchmarkRun)
async def get_benchmark(run_id: str) -> BenchmarkRun:
    run = get_benchmark_store().get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Benchmark run '{run_id}' not found")
    return run


@router.get("", response_model=BenchmarkListResponse)
async def list_benchmarks() -> BenchmarkListResponse:
    store = get_benchmark_store()
    return BenchmarkListResponse(
        retained_runs=len(store),
        max_runs_retained=store.max_jobs,
        ttl_seconds=store.ttl_seconds,
    )
