"""Workload-scaling benchmark API (Part 7, G/H/I).

Everything here runs at a deliberately tiny workload with a tiny ceiling: the point is to
pin the guardrails and the state machine, not to measure throughput inside a test suite.
"""

from __future__ import annotations

import asyncio
import re
import tempfile
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import create_engine

from app.core.config import get_settings
from app.main import app
from app.models.base import Base
from app.schemas.benchmark import TERMINAL_STATUSES, BenchmarkCreateRequest, tier_for
from app.serving.benchmark_service import (
    reset_benchmark_store,
    resolve_status,
    sync_database_url,
)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://benchtest", timeout=300.0
    ) as c:
        yield c


@pytest.fixture
def bench_db(monkeypatch):
    """Point the benchmark's synchronous writer at a throwaway database, so a test never
    writes into (or cleans up out of) the developer's real veyra.db."""
    tmpdir = tempfile.mkdtemp(prefix="veyra-bench-test-")
    db_path = Path(tmpdir) / "bench.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    engine.dispose()

    settings = get_settings()
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setattr(settings, "benchmark_hard_cap_events", 3_000)
    monkeypatch.setattr(settings, "benchmark_chunk_size", 1_000)
    monkeypatch.setattr(settings, "benchmark_max_seconds", 60.0)
    reset_benchmark_store()
    yield db_path
    reset_benchmark_store()


async def _await_completion(client, run_id: str, timeout_s: float = 180.0) -> dict:
    waited = 0.0
    while waited < timeout_s:
        resp = await client.get(f"/v2/demo/benchmarks/{run_id}/progress")
        assert resp.status_code == 200
        body = resp.json()
        if body["finished"]:
            final = await client.get(f"/v2/demo/benchmarks/{run_id}")
            return final.json()
        await asyncio.sleep(0.25)
        waited += 0.25
    raise AssertionError(f"benchmark {run_id} did not finish within {timeout_s}s")


# ------------------------------------------------------------------- request validation


def test_workload_tiers_are_classified() -> None:
    """G: presets map onto documented tiers."""
    assert tier_for(100_000) == "safe"
    assert tier_for(1_000_000) == "safe"
    assert tier_for(10_000_000) == "extended"
    assert tier_for(100_000_000) == "experimental"


def test_scenario_mix_drives_the_fraud_ratio() -> None:
    assert BenchmarkCreateRequest(scenario_mix="all_legit").effective_fraud_ratio() == 0.0
    assert BenchmarkCreateRequest(scenario_mix="all_fraud").effective_fraud_ratio() == 1.0
    assert BenchmarkCreateRequest(scenario_mix="mixed_50_50").effective_fraud_ratio() == 0.5
    custom = BenchmarkCreateRequest(scenario_mix="custom", fraud_ratio=0.33)
    assert custom.effective_fraud_ratio() == 0.33


@pytest.mark.asyncio
async def test_invalid_workload_is_rejected(client):
    """G: out-of-range sizes never reach the runner."""
    resp = await client.post("/v2/demo/benchmarks", json={"workload_size": 10})
    assert resp.status_code == 422
    resp = await client.post("/v2/demo/benchmarks", json={"workload_size": 500_000_000})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_presets_endpoint_declares_guardrails(client):
    resp = await client.get("/v2/demo/benchmarks/presets")
    assert resp.status_code == 200
    body = resp.json()
    sizes = [p["workload_size"] for p in body["presets"]]
    assert sizes == [100_000, 500_000, 1_000_000, 10_000_000, 100_000_000]
    assert body["guardrails"]["concurrent_jobs"] == 1
    assert body["guardrails"]["hard_cap_events"] > 0
    assert any(p["will_be_capped"] for p in body["presets"]), "100M must be flagged as capped"


# ------------------------------------------------------------------------- guardrails


@pytest.mark.asyncio
async def test_experimental_workload_is_capped_never_materialized(client, bench_db):
    """H: a 100M request cannot cause 100M events to be generated.

    The ceiling is monkeypatched down to 3,000 for the test; the assertion is that what
    actually ran is the ceiling, that it is reported as capped, and that no field
    extrapolates back up to the requested size.
    """
    resp = await client.post(
        "/v2/demo/benchmarks",
        json={
            "workload_size": 100_000_000,
            "benchmark_mode": "ingestion",
            "scenario_mix": "all_legit",
        },
    )
    assert resp.status_code == 202
    created = resp.json()
    assert created["capped"] is True
    assert created["planned_executed_size"] == 3_000
    assert created["workload_tier"] == "experimental"

    run = await _await_completion(client, created["run_id"])
    # Capped, and it reached its (tiny) capped target, so the honest status is "capped" —
    # never "completed", which would read as "the 100,000,000 you asked for is done".
    assert run["status"] == "capped", run.get("error")
    result = run["result"]

    assert result["status"] == "capped"
    assert result["requested_workload_size"] == 100_000_000
    assert result["capped_workload_size"] == 3_000
    assert result["capped"] is True
    assert result["traffic"]["requested_events"] == 100_000_000
    assert result["traffic"]["generated_events"] <= 3_000 * 2, "generation respects the ceiling"
    assert any("not attempted" in lim for lim in result["limitations"])
    # The capped target is a target, not a claim about what ran. Nothing may say
    # the ceiling was executed when the budget could have stopped the run below it.
    assert not any("executed 3,000 events" in lim for lim in result["limitations"])


@pytest.mark.asyncio
async def test_ingestion_benchmark_measures_and_cleans_up(client, bench_db):
    """A: real writes, real throughput, and no leftover rows in the database."""
    resp = await client.post(
        "/v2/demo/benchmarks",
        json={
            "workload_size": 2_000,
            "benchmark_mode": "ingestion",
            "scenario_mix": "legit_90_fraud_10",
        },
    )
    assert resp.status_code == 202
    run = await _await_completion(client, resp.json()["run_id"])

    assert run["status"] == "completed", run.get("error")
    result = run["result"]
    assert result["traffic"]["generated_events"] > 0
    assert result["ingestion"]["events_persisted"] > 0
    assert result["ingestion"]["write_duration_ms"] > 0
    assert result["ingestion"]["events_per_second"] > 0
    assert result["ingestion"]["unit"] == "events_per_second"
    assert result["total_ms"] > 0
    assert result["memory"]["peak_traced_python_heap_mb"] is not None
    assert result["memory"]["metric"] == "tracemalloc_traced_python_heap"
    assert result["memory"]["includes_process_rss"] is False
    assert result["environment"]["database"] == "sqlite"
    assert (
        result["storage"]["rows_deleted_on_cleanup"]
        == result["ingestion"]["events_persisted"]
    )

    # Nothing left behind in the benchmark database.
    engine = create_engine(sync_database_url(get_settings().database_url), future=True)
    with engine.connect() as conn:
        from sqlalchemy import text

        remaining = conn.execute(
            text("SELECT COUNT(*) FROM raw_events WHERE source = 'benchmark'")
        ).scalar_one()
    engine.dispose()
    assert remaining == 0, "benchmark rows must not persist after the run"


@pytest.mark.asyncio
async def test_ingestion_mode_reports_no_computation_metrics(client, bench_db):
    resp = await client.post(
        "/v2/demo/benchmarks",
        json={"workload_size": 1_000, "benchmark_mode": "ingestion", "scenario_mix": "all_legit"},
    )
    run = await _await_completion(client, resp.json()["run_id"])
    result = run["result"]
    assert result["computation"] is None, "ingestion mode performs no detection work"


@pytest.mark.asyncio
async def test_pipeline_mode_reports_sampled_window_count(client, bench_db):
    """B (Part 3A): computation-scale numbers always disclose their sample size."""
    resp = await client.post(
        "/v2/demo/benchmarks",
        json={"workload_size": 1_000, "benchmark_mode": "pipeline", "scenario_mix": "mixed_50_50"},
    )
    run = await _await_completion(client, resp.json()["run_id"])
    assert run["status"] == "completed", run.get("error")
    result = run["result"]

    comp = result["computation"]
    assert comp is not None and comp["sampled_windows"] > 0
    assert comp["feature_extraction_total_ms"] >= 0
    assert comp["entity_graph_total_ms"] >= 0
    assert comp["model_inference_total_ms"] >= 0
    # Units are per merchant-window, never per transaction (Part 14).
    assert comp["unit"] == "milliseconds_per_merchant_window"
    assert comp["is_full_workload_pass"] is False
    assert any("sampled merchant-window" in lim for lim in result["limitations"]), (
        "a sampled measurement must say so in limitations"
    )


# --------------------------------------------------------------------- job lifecycle


@pytest.mark.asyncio
async def test_progress_and_status_transitions(client, bench_db):
    """I: queued -> running -> completed, with progress readable throughout."""
    resp = await client.post(
        "/v2/demo/benchmarks",
        json={"workload_size": 2_000, "benchmark_mode": "ingestion", "scenario_mix": "all_legit"},
    )
    run_id = resp.json()["run_id"]
    assert resp.json()["status"] == "queued"

    seen: set[str] = set()
    for _ in range(400):
        body = (await client.get(f"/v2/demo/benchmarks/{run_id}/progress")).json()
        seen.add(body["status"])
        if body["progress"] is not None:
            assert 0.0 <= body["progress"]["percent"] <= 100.0
            assert body["progress"]["events_target"] > 0
        if body["finished"]:
            break
        await asyncio.sleep(0.05)

    final = (await client.get(f"/v2/demo/benchmarks/{run_id}")).json()
    assert final["status"] in ("completed", "capped", "stopped_early"), final.get("error")
    assert final["started_at"] is not None
    assert final["finished_at"] is not None
    assert seen <= {"queued", "running", "completed"}


@pytest.mark.asyncio
async def test_unknown_benchmark_run_is_404(client):
    assert (await client.get("/v2/demo/benchmarks/run_nope")).status_code == 404
    assert (await client.get("/v2/demo/benchmarks/run_nope/progress")).status_code == 404


def test_sync_url_mapping_is_explicit() -> None:
    assert sync_database_url("sqlite+aiosqlite:///./veyra.db") == "sqlite:///./veyra.db"
    assert sync_database_url("postgresql+asyncpg://u:p@h/db") is None


# ------------------------------------------------------- completion semantics (Part 9)


def test_status_precedence_never_reports_a_short_run_as_completed() -> None:
    """Part 9's example, as a unit assertion.

    Requested 100M, ceiling 2M, generated 464,458 -> the run was both capped and cut
    short. Only one of those can be the headline, and reporting `capped` (let alone
    `completed`) would let a UI print "100M benchmark completed" over a run that
    processed 0.46% of it.
    """
    assert resolve_status(failed=False, stopped_early=True, capped=True) == "stopped_early"
    assert resolve_status(failed=False, stopped_early=False, capped=True) == "capped"
    assert resolve_status(failed=False, stopped_early=False, capped=False) == "completed"
    assert resolve_status(failed=True, stopped_early=True, capped=True) == "failed"


@pytest.mark.asyncio
async def test_budget_stop_is_reported_as_stopped_early(client, bench_db, monkeypatch):
    """A run cut off by the wall-clock budget must never come back `completed`."""
    settings = get_settings()
    # A budget this small guarantees the stop happens between the first chunks.
    monkeypatch.setattr(settings, "benchmark_max_seconds", 0.05)
    monkeypatch.setattr(settings, "benchmark_hard_cap_events", 200_000)
    monkeypatch.setattr(settings, "benchmark_chunk_size", 1_000)

    resp = await client.post(
        "/v2/demo/benchmarks",
        json={
            "workload_size": 200_000,
            "benchmark_mode": "ingestion",
            "scenario_mix": "all_legit",
        },
    )
    run = await _await_completion(client, resp.json()["run_id"])
    result = run["result"]

    assert run["status"] == "stopped_early", result["limitations"]
    assert result["status"] == "stopped_early"
    assert result["stop_reason"] == "wall_clock_budget_exceeded"
    assert result["traffic"]["generated_events"] < result["capped_workload_size"]
    assert any("stopped_early" in lim for lim in result["limitations"])


@pytest.mark.asyncio
async def test_progress_reports_finished_for_every_terminal_status(client, bench_db, monkeypatch):
    """`finished` drives the frontend's polling loop. If a terminal status is missing
    from that set the UI polls forever, so it is derived from TERMINAL_STATUSES rather
    than a hardcoded pair."""
    settings = get_settings()
    monkeypatch.setattr(settings, "benchmark_max_seconds", 0.05)

    resp = await client.post(
        "/v2/demo/benchmarks",
        json={
            "workload_size": 100_000,
            "benchmark_mode": "ingestion",
            "scenario_mix": "all_legit",
        },
    )
    run_id = resp.json()["run_id"]
    await _await_completion(client, run_id)

    progress = (await client.get(f"/v2/demo/benchmarks/{run_id}/progress")).json()
    assert progress["finished"] is True
    assert progress["status"] in TERMINAL_STATUSES
    assert progress["status"] == "stopped_early"


# ------------------------------------------------------ traffic composition (Part 8)


@pytest.mark.asyncio
async def test_traffic_composition_is_counted_not_inferred(client, bench_db):
    """Legit/fraud counts must come from the generated transactions' own labels and add
    up to what was generated — never be derived from the requested ratio."""
    resp = await client.post(
        "/v2/demo/benchmarks",
        json={
            "workload_size": 2_000,
            "benchmark_mode": "ingestion",
            "scenario_mix": "mixed_50_50",
        },
    )
    run = await _await_completion(client, resp.json()["run_id"])
    traffic = run["result"]["traffic"]

    generated = traffic["generated_events"]
    assert generated > 0
    assert traffic["legitimate_events"] + traffic["fraud_events"] == generated
    assert traffic["requested_fraud_ratio"] == 0.50
    # The actual ratio is a measurement, not an echo of the request.
    assert traffic["actual_fraud_ratio"] == pytest.approx(
        traffic["fraud_events"] / generated, rel=1e-6
    )
    assert traffic["requested_events"] == 2_000


@pytest.mark.asyncio
async def test_all_legit_mix_generates_no_fraud(client, bench_db):
    """A 100%-legitimate mix must actually contain zero labelled-abusive events."""
    resp = await client.post(
        "/v2/demo/benchmarks",
        json={
            "workload_size": 2_000,
            "benchmark_mode": "ingestion",
            "scenario_mix": "all_legit",
        },
    )
    run = await _await_completion(client, resp.json()["run_id"])
    traffic = run["result"]["traffic"]
    assert traffic["fraud_events"] == 0
    assert traffic["actual_fraud_ratio"] == 0.0
    assert traffic["legitimate_events"] == traffic["generated_events"]


# --------------------------------------------------- representative samples (Part 6)


@pytest.mark.asyncio
async def test_samples_are_bounded_and_never_the_full_workload(client, bench_db):
    resp = await client.post(
        "/v2/demo/benchmarks",
        json={
            "workload_size": 3_000,
            "benchmark_mode": "ingestion",
            "scenario_mix": "mixed_50_50",
        },
    )
    run = await _await_completion(client, resp.json()["run_id"])
    result = run["result"]
    samples = result["samples"]
    cap = samples["per_bucket_cap"]

    assert samples["is_full_workload"] is False
    for bucket in ("legitimate", "fraud", "random"):
        assert len(samples[bucket]) <= cap, f"{bucket} exceeded its cap"
    # Far smaller than the workload it represents.
    assert sum(len(samples[b]) for b in ("legitimate", "fraud", "random")) < result["traffic"][
        "generated_events"
    ]
    assert all(r["ground_truth_is_abusive"] is True for r in samples["fraud"])
    assert all(r["ground_truth_is_abusive"] is False for r in samples["legitimate"])


@pytest.mark.asyncio
async def test_samples_expose_no_pan_shaped_identifiers(client, bench_db):
    resp = await client.post(
        "/v2/demo/benchmarks",
        json={
            "workload_size": 2_000,
            "benchmark_mode": "ingestion",
            "scenario_mix": "mixed_50_50",
        },
    )
    run = await _await_completion(client, resp.json()["run_id"])
    samples = run["result"]["samples"]

    pan = re.compile(r"^\d{12,19}$")
    for bucket in ("legitimate", "fraud", "random"):
        for row in samples[bucket]:
            for field in ("instrument_fingerprint", "device_fingerprint", "ip_fingerprint"):
                value = row[field]
                assert value is None or not pan.match(str(value)), f"PAN-shaped {field}"


# ----------------------------------------------------- memory semantics (Part 13)


@pytest.mark.asyncio
async def test_memory_metric_names_its_own_method(client, bench_db):
    """The field must not be readable as a generic "peak memory": it is traced Python
    heap only, and the response has to say so itself."""
    resp = await client.post(
        "/v2/demo/benchmarks",
        json={
            "workload_size": 1_000,
            "benchmark_mode": "ingestion",
            "scenario_mix": "all_legit",
        },
    )
    run = await _await_completion(client, resp.json()["run_id"])
    memory = run["result"]["memory"]

    assert memory["metric"] == "tracemalloc_traced_python_heap"
    assert memory["includes_process_rss"] is False
    assert memory["includes_native_allocations"] is False
    assert "tracemalloc" in memory["description"]
    assert memory["peak_traced_python_heap_mb"] > 0


# ------------------------------------------------------- rejection path (Part 9)


@pytest.mark.asyncio
async def test_experimental_workload_can_be_rejected_before_execution(client, monkeypatch):
    """With experimental workloads disabled, a 100M request is refused outright — no run
    record, nothing generated."""
    settings = get_settings()
    monkeypatch.setattr(settings, "benchmark_allow_experimental", False)

    resp = await client.post(
        "/v2/demo/benchmarks",
        json={"workload_size": 100_000_000, "benchmark_mode": "ingestion"},
    )
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert detail["status"] == "rejected"
    assert detail["reason"] == "experimental_workloads_disabled"
    assert detail["workload_tier"] == "experimental"


@pytest.mark.asyncio
async def test_safe_workload_still_allowed_when_experimental_disabled(
    client, bench_db, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "benchmark_allow_experimental", False)
    resp = await client.post(
        "/v2/demo/benchmarks",
        json={"workload_size": 1_000, "benchmark_mode": "ingestion"},
    )
    assert resp.status_code == 202
