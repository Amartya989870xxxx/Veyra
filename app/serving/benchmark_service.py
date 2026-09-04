"""Workload-scaling benchmark runner and job registry (Parts 3, 3A, 3B, 4).

What this measures, and what it deliberately does not
-----------------------------------------------------
Two separate questions, kept separate because they scale differently and answering them
with one number would hide that:

**A. Ingestion / write scale.** How fast can synthetic events be generated, built into
row payloads, and durably written? Measured against the real configured database, in
chunks, with real `INSERT` batches.

**B. Detection / computation scale.** How do feature extraction, entity-graph
construction and model inference behave as the workload grows? Measured by scoring a
*bounded sample* of merchant-windows (`benchmark_max_sample_windows`, default 150) drawn
from generated traffic — not every window a large workload could produce. The sample size
is reported on every result, so the number is never mistaken for an exhaustive pass.

Memory and runtime safety (Part 3B)
-----------------------------------
- Events are generated and persisted **in chunks** (`benchmark_chunk_size`, default
  20,000); a chunk is discarded before the next is built, so a 1M-event run never holds
  1M Python objects.
- `benchmark_hard_cap_events` (default 2,000,000) is an absolute ceiling on what one run
  will actually generate. A larger request is **capped, executed at the ceiling, and
  reported as capped**. Nothing is extrapolated to the requested size — a "100M" request
  returns real numbers for the size that ran plus an explicit limitation saying 100M was
  not attempted.
- `benchmark_max_seconds` (default 120s) is a wall-clock budget. On expiry the run stops
  between chunks and returns a partial result flagged `stopped_early`.
- One job runs at a time (single-worker executor). Additional submissions queue.

Why a synchronous engine in a worker thread
--------------------------------------------
The app's own session is `AsyncSession`, and driving async DB work from an arbitrary
worker thread means owning an event loop per thread — with aiosqlite, connections are
bound to the loop that created them, which is a sharp edge for no benefit here. This
module instead opens its own short-lived **synchronous** engine against the same database
URL and writes through SQLAlchemy Core `insert()` batches. Same database, same table, same
storage engine — just a connection that does not touch the app's async machinery.

Cleanup
-------
Benchmark rows are written under merchant ids namespaced `bench_{run_id}_*` and deleted
in a `finally` block once measurement is complete, so a scale test does not leave a
million synthetic rows behind in the operational database.
"""

from __future__ import annotations

import os
import platform
import random
import sys
import threading
import time
import tracemalloc
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import Table, create_engine, insert, text

from app.core.config import get_settings
from app.core.ids import stable_hash
from app.models.entities import RawEventRow
from app.schemas.benchmark import (
    BenchmarkCreateRequest,
    BenchmarkEnvironment,
    BenchmarkProgress,
    BenchmarkResult,
    BenchmarkRun,
    BenchmarkSamples,
    BenchmarkSampleTransaction,
    BenchmarkStatus,
    ComputationScale,
    IngestionScale,
    MemoryMetrics,
    StopReason,
    StorageMetrics,
    TrafficComposition,
    tier_for,
)
from app.windows import WindowSize
from data.generators.population import MerchantProfile, generate_merchant_population
from data.generators.recipes import SCENARIO_RECIPES
from data.generators.timeline import (
    AnnotatedTransaction,
    generate_organic_timeline,
    hour_of_week_rate_multiplier,
)

BENCH_MERCHANT_PREFIX = "bench"
# `__table__` is typed as the looser `FromClause` on a declarative class; the concrete
# `Table` is what `insert()` actually wants, and what this attribute always holds.
RAW_EVENTS_TABLE: Table = cast(Table, RawEventRow.__table__)
_ATTACK_RECIPES = ("card_testing_burst", "device_farm_ring", "bin_enumeration_attack")


# ----------------------------------------------------------------------------- registry


class BenchmarkJobStore:
    """Bounded, in-process registry of benchmark runs. Same retention shape as the demo
    run store: newest N kept, everything TTL'd."""

    def __init__(self, max_jobs: int | None = None, ttl_seconds: int | None = None) -> None:
        settings = get_settings()
        self.max_jobs = max_jobs if max_jobs is not None else settings.benchmark_max_jobs_retained
        self.ttl_seconds = (
            ttl_seconds if ttl_seconds is not None else settings.benchmark_job_ttl_seconds
        )
        self._lock = threading.Lock()
        self._jobs: OrderedDict[str, BenchmarkRun] = OrderedDict()
        self._stored_at: dict[str, float] = {}

    def _evict_locked(self) -> None:
        now = time.monotonic()
        expired = [rid for rid, ts in self._stored_at.items() if now - ts > self.ttl_seconds]
        for rid in expired:
            self._jobs.pop(rid, None)
            self._stored_at.pop(rid, None)
        while len(self._jobs) > self.max_jobs:
            rid, _ = self._jobs.popitem(last=False)
            self._stored_at.pop(rid, None)

    def put(self, run: BenchmarkRun) -> None:
        with self._lock:
            self._evict_locked()
            self._jobs[run.run_id] = run
            self._stored_at[run.run_id] = time.monotonic()
            self._jobs.move_to_end(run.run_id)

    def get(self, run_id: str) -> BenchmarkRun | None:
        with self._lock:
            self._evict_locked()
            return self._jobs.get(run_id)

    def update(self, run_id: str, **fields) -> BenchmarkRun | None:
        """Mutate a job in place under the lock. Called from the worker thread while an
        HTTP handler may be reading the same object."""
        with self._lock:
            run = self._jobs.get(run_id)
            if run is None:
                return None
            for key, value in fields.items():
                setattr(run, key, value)
            return run

    def __len__(self) -> int:
        with self._lock:
            self._evict_locked()
            return len(self._jobs)


_store: BenchmarkJobStore | None = None
_store_lock = threading.Lock()
_executor: ThreadPoolExecutor | None = None


def get_benchmark_store() -> BenchmarkJobStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = BenchmarkJobStore()
    return _store


def get_executor() -> ThreadPoolExecutor:
    """Single worker: benchmarks are CPU- and IO-heavy, and running two at once would
    make both sets of numbers meaningless as well as doubling peak memory."""
    global _executor
    if _executor is None:
        with _store_lock:
            if _executor is None:
                _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="veyra-bench")
    return _executor


def reset_benchmark_store() -> None:
    """Test-only."""
    global _store
    with _store_lock:
        _store = None


# ------------------------------------------------------------------------ db plumbing


def sync_database_url(async_url: str) -> str | None:
    """Map the configured async URL onto a synchronous driver, or `None` when no sync
    driver is available in this environment."""
    if async_url.startswith("sqlite+aiosqlite://"):
        return async_url.replace("sqlite+aiosqlite://", "sqlite://", 1)
    if async_url.startswith("sqlite://"):
        return async_url
    if async_url.startswith("postgresql+asyncpg://"):
        # psycopg2 is not a declared dependency of this project; rather than fail at
        # write time, the caller reports persistence as unavailable and measures
        # generation only.
        return None
    return None


def _sqlite_file_path(sync_url: str) -> str | None:
    if not sync_url.startswith("sqlite:///"):
        return None
    path = sync_url.replace("sqlite:///", "", 1)
    return path or None


# ------------------------------------------------------------------------- generation


def _mean_rate_multiplier(window_start: datetime, window_span: timedelta) -> float:
    """Average of the generator's own hour-of-week seasonal curve across the window.

    Sampled rather than integrated: the curve is piecewise-constant per hour, and ten
    samples is plenty to divide it back out of a rate. Floored so a dead hour cannot turn
    into a division that explodes the requested rate.
    """
    steps = 10
    total = 0.0
    for i in range(steps):
        at = window_start + window_span * (i / steps)
        total += hour_of_week_rate_multiplier(at)
    return max(0.05, total / steps)


def _chunk_transactions(
    profile: MerchantProfile,
    chunk_index: int,
    chunk_target: int,
    fraud_ratio: float,
    window_start: datetime,
    window_span: timedelta,
    seed: int,
) -> list[AnnotatedTransaction]:
    """Generate about `chunk_target` transactions for one chunk, split to `fraud_ratio`.

    Both generators are stochastic: `generate_organic_timeline` is a non-homogeneous
    Poisson process, and the injection recipes size themselves from their own intensity
    model and emit in whole batches. Left alone, they overshoot badly — a requested
    90/10 mix measured 58/42 in practice, because a recipe asked for 2,000 fraud events
    would emit them ~7,000 at a time.

    So each side is generated until it *reaches* its target and then trimmed back to it.
    Trimming discards surplus transactions that were really generated; it never
    fabricates any, and it never pads a short side to make the ratio look right. When the
    legitimate stream comes up short the chunk is simply smaller, and the shortfall shows
    up in the measured `actual_fraud_ratio` rather than being hidden.
    """
    rng = random.Random(seed + chunk_index)
    fraud_target = round(chunk_target * fraud_ratio)
    legit_target = max(0, chunk_target - fraud_target)

    legit: list[AnnotatedTransaction] = []
    fraud: list[AnnotatedTransaction] = []

    if legit_target > 0:
        hours = max(window_span.total_seconds() / 3600.0, 0.05)
        # `generate_organic_timeline` multiplies its base rate by an hour-of-week seasonal
        # curve, and benchmark chunks start at midnight where that curve bottoms out near
        # 0.2. Setting the base rate from the target alone therefore produced roughly a
        # fifth of it, which is what made a requested 90/10 mix measure 58/42. Dividing
        # the seasonal factor back out is what makes the requested mix achievable at all.
        mean_multiplier = _mean_rate_multiplier(window_start, window_span)
        legit_profile = profile
        legit_profile.hourly_baseline_txns = max(
            1.0, (legit_target * 1.15) / hours / mean_multiplier
        )
        guard = 0
        while len(legit) < legit_target and guard < 6:
            legit.extend(
                generate_organic_timeline(
                    profile=legit_profile,
                    start_time=window_start,
                    duration=window_span,
                    seed=seed + chunk_index * 7919 + guard * 104_729,
                )
            )
            guard += 1
        legit = legit[:legit_target]

    if fraud_target > 0:
        recipe_name = _ATTACK_RECIPES[chunk_index % len(_ATTACK_RECIPES)]
        recipe = SCENARIO_RECIPES[recipe_name]
        # ~150 attempts at intensity 1.0 is the rough centre of the implemented recipes.
        intensity = max(0.2, min(3.0, fraud_target / 150.0))
        guard = 0
        while len(fraud) < fraud_target and guard < 40:
            batch = recipe(
                profile=profile,
                start_time=window_start,
                rng=rng,
                intensity=intensity,
            )
            if not batch:
                break
            fraud.extend(batch)
            guard += 1
        fraud = fraud[:fraud_target]

    txns = legit + fraud
    txns.sort(key=lambda t: t.attempt.timestamp)
    return txns


def _rows_for(txns: list[AnnotatedTransaction], run_id: str, merchant_id: str) -> list[dict]:
    rows: list[dict] = []
    now = datetime.now(UTC)
    for i, t in enumerate(txns):
        payload = {
            "transaction_id": t.attempt.transaction_id,
            "customer_id": t.attempt.customer_id,
            "device_fp": t.attempt.device_fp,
            "instrument_fp": t.attempt.instrument_fp,
            "ip_fp": t.attempt.ip_fp,
            "amount": float(t.attempt.amount),
            "currency": t.attempt.currency,
        }
        unique = f"{run_id}:{merchant_id}:{i}:{t.attempt.transaction_id}"
        rows.append(
            {
                "event_id": f"bev_{stable_hash(unique)[:28]}",
                "event_type": "PAYMENT_ATTEMPT",
                "source": "benchmark",
                "timestamp": t.attempt.timestamp,
                "schema_version": "2.0.0",
                "idempotency_key": f"bench_{stable_hash(unique)[:32]}",
                "merchant_id": merchant_id,
                "payload_hash": stable_hash(str(payload)),
                "payload": payload,
                "ingested_at": now,
            }
        )
    return rows


# ------------------------------------------------------------------ representative samples


class _Reservoir:
    """Uniform random sample of at most `cap` items from a stream of unknown length.

    Algorithm R. Used instead of "keep the first N" because the first N transactions all
    come from chunk 0 — one merchant, one time window — which would make the "samples"
    a picture of the run's opening moments rather than of the workload. Memory is bounded
    by `cap` regardless of how many events stream past.
    """

    __slots__ = ("_rng", "cap", "items", "seen")

    def __init__(self, cap: int, rng: random.Random) -> None:
        self.cap = cap
        self.items: list[AnnotatedTransaction] = []
        self.seen = 0
        self._rng = rng

    def offer(self, item: AnnotatedTransaction) -> None:
        self.seen += 1
        if len(self.items) < self.cap:
            self.items.append(item)
            return
        j = self._rng.randrange(self.seen)
        if j < self.cap:
            self.items[j] = item


def _to_sample(t: AnnotatedTransaction) -> BenchmarkSampleTransaction:
    return BenchmarkSampleTransaction(
        transaction_id=t.attempt.transaction_id,
        timestamp=t.attempt.timestamp,
        merchant_id=t.attempt.merchant_id,
        customer_id=t.attempt.customer_id,
        device_fingerprint=t.attempt.device_fp,
        instrument_fingerprint=t.attempt.instrument_fp,
        ip_fingerprint=t.attempt.ip_fp,
        amount=str(t.attempt.amount),
        currency=t.attempt.currency,
        outcome_status=t.outcome.status.value if t.outcome else None,
        ground_truth_is_abusive=t.is_abusive,
        ground_truth_scenario_id=t.scenario_id,
    )


def resolve_status(
    *, failed: bool, stopped_early: bool, capped: bool
) -> BenchmarkStatus:
    """Collapse the run's facts into one terminal status (Part 9).

    Precedence is failed > stopped_early > capped > completed. `stopped_early` outranks
    `capped` because they answer different questions and only one can be the headline:
    capping says the *target* was lowered, stopping says the *target was not reached*.
    Reporting a run that processed 464,458 of a 2,000,000 target as anything other than
    stopped_early would be the exact overclaim this precedence exists to prevent.
    """
    if failed:
        return "failed"
    if stopped_early:
        return "stopped_early"
    if capped:
        return "capped"
    return "completed"


# ----------------------------------------------------------------------------- runner


def execute_benchmark(run_id: str, request: BenchmarkCreateRequest) -> None:
    """Run one benchmark to completion. Executes on the worker thread; every state
    transition is written back through the job store so pollers see progress."""
    settings = get_settings()
    store = get_benchmark_store()
    started = datetime.now(UTC)
    store.update(run_id, status="running", started_at=started)

    t_start = time.perf_counter()
    limitations: list[str] = []
    tracemalloc.start()

    requested = request.workload_size
    hard_cap = settings.benchmark_hard_cap_events
    executed_target = min(requested, hard_cap)
    capped = executed_target < requested
    if capped:
        limitations.append(
            f"Requested workload of {requested:,} events exceeds this environment's configured "
            f"safety ceiling of {hard_cap:,} (VEYRA_BENCHMARK_HARD_CAP_EVENTS), so the run "
            f"targeted {executed_target:,} instead. See generated_events for how many events "
            f"actually ran — the wall-clock budget can stop a run below its target. Nothing "
            f"here is extrapolated to {requested:,}: that workload was not attempted."
        )

    fraud_ratio = request.effective_fraud_ratio()
    sync_url = sync_database_url(settings.database_url)
    engine = None
    db_path = None
    storage_before = None

    generated = 0
    persisted = 0
    legitimate_events = 0
    fraud_events = 0
    ingestion_ms = 0.0
    ingestion_errors = 0
    stopped_early = False
    stop_reason: StopReason | None = None
    sample_windows: list[list[AnnotatedTransaction]] = []
    max_samples = settings.benchmark_max_sample_windows
    merchant_ids: list[str] = []

    # Bounded representative evidence (Part 6). Three reservoirs, each capped, filled as
    # generation streams past — the full workload is never retained.
    sample_cap = settings.benchmark_sample_rows
    sample_rng = random.Random(90210)
    res_legit = _Reservoir(sample_cap, sample_rng)
    res_fraud = _Reservoir(sample_cap, sample_rng)
    res_random = _Reservoir(sample_cap, sample_rng)

    try:
        if sync_url is None:
            limitations.append(
                f"No synchronous driver is available for '{settings.database_url.split('://')[0]}' "
                "in this environment, so events were generated and validated but not persisted. "
                "ingestion_tps therefore measures generation only and is reported as null."
            )
        else:
            engine = create_engine(sync_url, future=True)
            db_path = _sqlite_file_path(sync_url)
            if db_path and os.path.exists(db_path):
                storage_before = os.path.getsize(db_path)

        window_span = timedelta(minutes=request.duration_minutes)
        base_start = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)
        chunk_size = min(settings.benchmark_chunk_size, max(1, executed_target))
        chunk_index = 0

        while generated < executed_target:
            elapsed = time.perf_counter() - t_start
            if elapsed > settings.benchmark_max_seconds:
                stopped_early = True
                stop_reason = "wall_clock_budget_exceeded"
                limitations.append(
                    f"Stopped after {elapsed:.1f}s, exceeding the configured budget of "
                    f"{settings.benchmark_max_seconds:.0f}s (VEYRA_BENCHMARK_MAX_SECONDS). "
                    f"Reported figures cover the {generated:,} events processed before the stop."
                )
                break

            remaining = executed_target - generated
            chunk_target = min(chunk_size, remaining)

            merchant_id = f"{BENCH_MERCHANT_PREFIX}_{run_id}_{chunk_index}"
            profile = generate_merchant_population(n_merchants=1, seed=1_000 + chunk_index)[0]
            profile.merchant.merchant_id = merchant_id
            merchant_ids.append(merchant_id)

            chunk_start = base_start + timedelta(minutes=request.duration_minutes * chunk_index)
            txns = _chunk_transactions(
                profile=profile,
                chunk_index=chunk_index,
                chunk_target=chunk_target,
                fraud_ratio=fraud_ratio,
                window_start=chunk_start,
                window_span=window_span,
                seed=4242,
            )
            generated += len(txns)

            # Composition is COUNTED from the generator's own ground-truth flags, never
            # inferred from the requested ratio — the recipes size themselves, so what was
            # asked for and what was produced legitimately differ.
            for t in txns:
                if t.is_abusive:
                    fraud_events += 1
                    res_fraud.offer(t)
                else:
                    legitimate_events += 1
                    res_legit.offer(t)
                res_random.offer(t)

            if request.benchmark_mode == "pipeline" and len(sample_windows) < max_samples and txns:
                # Keep a small, bounded slice for the computation-scale pass. Everything
                # else in this chunk is released at the end of the iteration.
                sample_windows.append(txns[: min(len(txns), 2_000)])

            if engine is not None and txns:
                rows = _rows_for(txns, run_id, merchant_id)
                t_write = time.perf_counter()
                try:
                    with engine.begin() as conn:
                        for i in range(0, len(rows), 5_000):
                            conn.execute(insert(RAW_EVENTS_TABLE), rows[i : i + 5_000])
                    persisted += len(rows)
                except Exception as exc:
                    ingestion_errors += len(rows)
                    if len(limitations) < 12:
                        limitations.append(
                            f"Chunk {chunk_index} failed to persist: {type(exc).__name__}: {exc}"
                        )
                ingestion_ms += (time.perf_counter() - t_write) * 1000.0

            chunk_index += 1
            store.update(
                run_id,
                progress=BenchmarkProgress(
                    stage="ingestion",
                    events_processed=generated,
                    events_target=executed_target,
                    percent=round(min(100.0, generated / max(1, executed_target) * 100.0), 2),
                    elapsed_ms=round((time.perf_counter() - t_start) * 1000.0, 1),
                ),
            )
            del txns

        storage_after = os.path.getsize(db_path) if db_path and os.path.exists(db_path) else None
        storage_delta_mb = (
            round((storage_after - storage_before) / (1024 * 1024), 4)
            if storage_after is not None and storage_before is not None
            else None
        )
        if storage_delta_mb is not None and storage_delta_mb <= 0 and persisted > 0:
            # SQLite reuses pages a previous run's cleanup freed, so the file can absorb a
            # whole workload without growing. Reporting a flat 0.0 without saying why would
            # read as "this workload cost no storage", which is not what was measured.
            limitations.append(
                f"storage_delta_mb is {storage_delta_mb} despite {persisted:,} rows written: "
                "SQLite reused free pages left by an earlier benchmark's cleanup, so file "
                "growth understates the space this workload occupied while it was resident."
            )

        # ---- computation scale -------------------------------------------------------
        feature_ms = graph_ms = scoring_ms = None
        sampled = None
        if request.benchmark_mode == "pipeline" and sample_windows:
            store.update(
                run_id,
                progress=BenchmarkProgress(
                    stage="computation",
                    events_processed=generated,
                    events_target=executed_target,
                    percent=100.0,
                    elapsed_ms=round((time.perf_counter() - t_start) * 1000.0, 1),
                ),
            )
            from app.serving.demo_model_service import get_demo_model_service

            # Model warm-up is environment setup, not workload processing, so it is
            # measured separately and excluded from the run's wall-clock budget. Counting
            # a one-time ~20s fit against the budget would make every cold-start pipeline
            # benchmark report zero sampled windows.
            model = get_demo_model_service()
            t_warm = time.perf_counter()
            engine_fe = model.feature_engine_for_scoring()
            warmup_ms = (time.perf_counter() - t_warm) * 1000.0
            if warmup_ms > 1_000.0:
                limitations.append(
                    f"Demo model fit ran during this benchmark ({warmup_ms / 1000.0:.1f}s) "
                    "because it "
                    "was not yet cached in this process. That time is excluded from the wall-clock "
                    "budget and from every computation-scale figure below."
                )
            compute_deadline = time.perf_counter() + max(
                5.0,
                settings.benchmark_max_seconds
                - (time.perf_counter() - t_start - warmup_ms / 1000.0),
            )

            substage: dict[str, float] = {"statistical_features": 0.0, "entity_graph": 0.0}
            total_feature_ms = 0.0
            total_graph_ms = 0.0
            total_score_ms = 0.0
            sampled = 0

            for window in sample_windows[:max_samples]:
                # Always measure at least one window, so a pipeline run never reports
                # "0 sampled windows" while claiming to have measured computation scale.
                if sampled > 0 and time.perf_counter() > compute_deadline:
                    # Same budget, different phase. The reason stays the typed
                    # wall_clock_budget_exceeded; which phase ran out is recorded in
                    # limitations, where a free-text explanation belongs.
                    stopped_early = True
                    if stop_reason is None:
                        stop_reason = "wall_clock_budget_exceeded"
                        limitations.append(
                            "The wall-clock budget expired during the computation phase, "
                            f"after {sampled} of {len(sample_windows)} sampled window(s) were "
                            "scored. "
                            "Ingestion figures above are complete for the events that ran; "
                            "computation figures cover only those scored windows."
                        )
                    break
                substage["statistical_features"] = 0.0
                substage["entity_graph"] = 0.0
                vec = engine_fe.extract_window_features(
                    merchant_id=window[0].attempt.merchant_id,
                    window_size=WindowSize.M5,
                    window_end=max(t.attempt.timestamp for t in window) + timedelta(seconds=1),
                    transactions=window,
                    on_stage=lambda name, ms: substage.__setitem__(name, ms),
                )
                total_feature_ms += substage["statistical_features"]
                total_graph_ms += substage["entity_graph"]
                t_score = time.perf_counter()
                model.score([vec.model_features])
                total_score_ms += (time.perf_counter() - t_score) * 1000.0
                sampled += 1

            feature_ms = round(total_feature_ms, 3)
            graph_ms = round(total_graph_ms, 3)
            scoring_ms = round(total_score_ms, 3)
            limitations.append(
                f"Computation-scale figures were measured on {sampled} sampled merchant-window(s) "
                f"(cap: {max_samples}), not on every window {generated:,} events would produce. "
                "They characterise per-window cost; they are not a full-workload detection pass."
            )
        elif request.benchmark_mode == "pipeline":
            limitations.append("Pipeline mode requested but no sample windows were generated.")

        peak_mb = round(tracemalloc.get_traced_memory()[1] / (1024 * 1024), 3)
        total_ms = (time.perf_counter() - t_start) * 1000.0

        # ---- cleanup first, so its row count can be reported on the result ------------
        deleted = 0
        if engine is not None and merchant_ids:
            try:
                with engine.begin() as conn:
                    for mid in merchant_ids:
                        res = conn.execute(
                            text("DELETE FROM raw_events WHERE merchant_id = :mid"), {"mid": mid}
                        )
                        deleted += res.rowcount or 0
            except Exception as exc:
                limitations.append(f"Cleanup failed: {type(exc).__name__}: {exc}")

        # ---- status: what actually happened, not what was hoped for (Part 9) ----------
        status = resolve_status(failed=False, stopped_early=stopped_early, capped=capped)
        if status == "stopped_early":
            limitations.append(
                f"STATUS stopped_early: {generated:,} of the {executed_target:,}-event target were "
                "processed before the run stopped. This run did NOT complete its workload, and no "
                "figure below is scaled up to the target."
            )

        # The generators are stochastic and the attack recipes have a per-chunk ceiling, so
        # a requested mix is not always reachable. Say so on the result rather than leaving
        # a reader to notice that two numbers disagree.
        actual_ratio = (fraud_events / generated) if generated else None
        if actual_ratio is not None and abs(actual_ratio - fraud_ratio) > 0.02:
            limitations.append(
                f"Requested fraud ratio {fraud_ratio:.2f}, measured {actual_ratio:.3f} over "
                f"{generated:,} generated events ({fraud_events:,} fraud / "
                f"{legitimate_events:,} legitimate). The synthetic generators are stochastic "
                "and the attack recipes have a per-chunk ceiling, so the mix is an outcome of "
                "generation. The measured split is what these figures describe."
            )

        computed_tps = (
            round(persisted / (ingestion_ms / 1000.0), 1)
            if engine is not None and ingestion_ms > 0 and persisted
            else None
        )

        computation = None
        if sampled:
            computation = ComputationScale(
                sampled_windows=sampled,
                sample_cap=max_samples,
                feature_extraction_total_ms=feature_ms or 0.0,
                feature_extraction_per_window_ms=round((feature_ms or 0.0) / sampled, 3),
                entity_graph_total_ms=graph_ms or 0.0,
                entity_graph_per_window_ms=round((graph_ms or 0.0) / sampled, 3),
                model_inference_total_ms=scoring_ms or 0.0,
                model_inference_per_window_ms=round((scoring_ms or 0.0) / sampled, 3),
                total_computation_ms=round(
                    (feature_ms or 0.0) + (graph_ms or 0.0) + (scoring_ms or 0.0), 3
                ),
                per_window_latency_ms=round(
                    ((feature_ms or 0.0) + (graph_ms or 0.0) + (scoring_ms or 0.0)) / sampled, 3
                ),
            )

        result = BenchmarkResult(
            status=status,
            stop_reason=stop_reason,
            requested_workload_size=requested,
            capped_workload_size=executed_target,
            capped=capped,
            workload_tier=tier_for(requested),
            scenario_mix=request.scenario_mix,
            benchmark_mode=request.benchmark_mode,
            duration_minutes=request.duration_minutes,
            traffic=TrafficComposition(
                requested_events=requested,
                generated_events=generated,
                processed_events=persisted if engine is not None else generated,
                legitimate_events=legitimate_events,
                fraud_events=fraud_events,
                requested_fraud_ratio=fraud_ratio,
                actual_fraud_ratio=(round(fraud_events / generated, 6) if generated else None),
            ),
            ingestion=IngestionScale(
                events_generated=generated,
                events_persisted=persisted,
                write_duration_ms=round(ingestion_ms, 3) if engine is not None else None,
                events_per_second=computed_tps,
                persistence_errors=ingestion_errors,
            ),
            computation=computation,
            memory=MemoryMetrics(peak_traced_python_heap_mb=peak_mb),
            storage=StorageMetrics(
                storage_delta_mb=storage_delta_mb,
                rows_deleted_on_cleanup=deleted if engine is not None else None,
            ),
            total_ms=round(total_ms, 3),
            samples=BenchmarkSamples(
                legitimate=[_to_sample(t) for t in res_legit.items],
                fraud=[_to_sample(t) for t in res_fraud.items],
                random=[_to_sample(t) for t in res_random.items],
                per_bucket_cap=sample_cap,
            ),
            environment=BenchmarkEnvironment(
                database=settings.database_url.split("://")[0].split("+")[0],
                database_url_scheme=settings.database_url.split("://")[0],
                python=sys.version.split()[0],
                platform=f"{platform.system()} {platform.release()} ({platform.machine()})",
                cpu_count=os.cpu_count(),
            ),
            limitations=limitations,
        )

        store.update(
            run_id,
            status=status,
            result=result,
            finished_at=datetime.now(UTC),
            progress=None,
        )

    except Exception as exc:
        store.update(
            run_id,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
            finished_at=datetime.now(UTC),
        )
    finally:
        tracemalloc.stop()
        if engine is not None:
            engine.dispose()


def submit_benchmark(run_id: str, request: BenchmarkCreateRequest) -> BenchmarkRun:
    run = BenchmarkRun(
        run_id=run_id,
        status="queued",
        created_at=datetime.now(UTC),
        request=request,
    )
    get_benchmark_store().put(run)
    get_executor().submit(execute_benchmark, run_id, request)
    return run
