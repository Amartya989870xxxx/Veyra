"""Request/response schemas for the workload-scaling benchmark (`/v2/demo/benchmarks`).

Every numeric field in `BenchmarkResult` is either measured or `None`. There is no
field on this model whose value is estimated, extrapolated or projected from a smaller
run — when a requested workload exceeds this environment's ceiling, the result reports
the size that was *actually executed* and says so in `limitations`, rather than scaling a
smaller measurement up to the number that was asked for.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

WorkloadTier = Literal["safe", "extended", "experimental"]
BenchmarkMode = Literal["ingestion", "pipeline"]
BenchmarkStatus = Literal[
    "queued", "running", "completed", "stopped_early", "capped", "failed", "rejected"
]
"""Terminal status is one value, resolved by this precedence:

    failed > stopped_early > capped > completed

`capped` and `stopped_early` are not mutually exclusive facts — a 100M request is capped
to the ceiling AND can then run out of wall-clock budget — so the boolean `capped` on the
result stays independently readable. The precedence exists so `status` answers one
question honestly: *did the run process everything it set out to?* A run that stopped at
464,458 of a 2,000,000 target is `stopped_early`, never `completed`, whatever else is
also true about it."""

StopReason = Literal[
    "wall_clock_budget_exceeded",
    "safety_ceiling_reached",
    "persistence_unavailable",
    "internal_error",
]

TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"completed", "stopped_early", "capped", "failed", "rejected"}
)
ScenarioMix = Literal[
    "all_legit",
    "legit_90_fraud_10",
    "mixed_50_50",
    "fraud_90_legit_10",
    "all_fraud",
    "custom",
]

WORKLOAD_PRESETS: tuple[int, ...] = (100_000, 500_000, 1_000_000, 10_000_000, 100_000_000)
"""The presets the UI offers. `workload_size` is not restricted to these — any size in
range is accepted — but these are the ones with a documented tier."""

SCENARIO_MIX_FRAUD_RATIO: dict[str, float] = {
    "all_legit": 0.0,
    "legit_90_fraud_10": 0.10,
    "mixed_50_50": 0.50,
    "fraud_90_legit_10": 0.90,
    "all_fraud": 1.0,
}
"""`custom` is the one value that defers to the request's own `fraud_ratio`."""


def tier_for(workload_size: int) -> WorkloadTier:
    """Classify a requested workload. Reported back on every result so a reader knows
    which class of run produced the numbers."""
    if workload_size <= 1_000_000:
        return "safe"
    if workload_size <= 10_000_000:
        return "extended"
    return "experimental"


class BenchmarkCreateRequest(BaseModel):
    workload_size: int = Field(
        default=100_000,
        ge=1_000,
        le=100_000_000,
        description=(
            "Events the benchmark is asked to process. Sizes above the server's configured "
            "ceiling are capped and reported as capped, never extrapolated."
        ),
    )
    duration_minutes: float = Field(
        default=5.0, ge=0.5, le=60.0,
        description=(
            "Simulated time span the synthetic traffic is spread across. Affects generation "
            "shape, not wall-clock runtime."
        ),
    )
    fraud_ratio: float = Field(
        default=0.10, ge=0.0, le=1.0,
        description=(
            "Share of generated events that come from an attack scenario. Only read when "
            "scenario_mix is 'custom'."
        ),
    )
    scenario_mix: ScenarioMix = "legit_90_fraud_10"
    benchmark_mode: BenchmarkMode = Field(
        default="pipeline",
        description=(
            "'ingestion' measures generate+validate+persist only. 'pipeline' additionally "
            "measures feature extraction, graph construction and model inference on a "
            "bounded sample of merchant-windows."
        ),
    )

    def effective_fraud_ratio(self) -> float:
        if self.scenario_mix == "custom":
            return self.fraud_ratio
        return SCENARIO_MIX_FRAUD_RATIO[self.scenario_mix]


class BenchmarkProgress(BaseModel):
    stage: str
    events_processed: int
    events_target: int
    percent: float
    elapsed_ms: float


class BenchmarkEnvironment(BaseModel):
    database: str = Field(..., description="Dialect actually written to, e.g. 'sqlite'.")
    database_url_scheme: str
    python: str
    platform: str
    cpu_count: int | None


class TrafficComposition(BaseModel):
    """What the workload actually contained, counted from the generated transactions'
    own ground-truth flags — never inferred from the requested size.

    When a run stops early, `generated_events` is what the generator actually produced and
    the legitimate/fraud split is counted over exactly those events. `actual_fraud_ratio`
    is therefore a measurement, and it routinely differs from `requested_fraud_ratio`:
    the injection recipes size themselves from their own intensity model, so the mix is an
    outcome of generation, not a dial that is set exactly.
    """

    requested_events: int
    generated_events: int
    processed_events: int = Field(
        ...,
        description=(
            "Events that completed the run's work path — persisted, in ingestion mode. "
            "Equal to generated_events only when nothing failed to write."
        ),
    )
    legitimate_events: int
    fraud_events: int
    requested_fraud_ratio: float
    actual_fraud_ratio: float | None = Field(
        default=None,
        description="fraud_events / generated_events. Null when nothing was generated.",
    )
    ground_truth_semantics: str = (
        "Counts come from the synthetic generator's own is_abusive flag, which is the label "
        "used to construct the workload. This is not a real-world fraud determination."
    )


class IngestionScale(BaseModel):
    """Write-path scale (Part 10A): generate -> build row payloads -> durably persist."""

    events_generated: int
    events_persisted: int
    write_duration_ms: float | None = Field(
        default=None,
        description="Time inside persistence calls only. Null when no writer was available.",
    )
    events_per_second: float | None = Field(
        default=None,
        description=(
            "events_persisted / write_duration_ms. UNIT: events per second of write time. "
            "This is a throughput figure for bulk chunked inserts, NOT a per-request latency."
        ),
    )
    persistence_errors: int
    unit: Literal["events_per_second"] = "events_per_second"


class ComputationScale(BaseModel):
    """Detection-path scale (Part 10B), measured per merchant-window.

    UNITS MATTER HERE. Every `*_per_window_ms` figure is the cost of analysing one
    merchant-window — a batch of transactions scored together. It is **not** a per-transaction
    latency, and dividing it by a transaction count produces a number that means nothing.
    The frontend must label these as per-window.
    """

    sampled_windows: int
    sample_cap: int
    feature_extraction_total_ms: float
    feature_extraction_per_window_ms: float
    entity_graph_total_ms: float
    entity_graph_per_window_ms: float
    model_inference_total_ms: float
    model_inference_per_window_ms: float
    total_computation_ms: float
    per_window_latency_ms: float = Field(
        ...,
        description=(
            "Mean end-to-end analysis cost for ONE merchant-window: features + graph + "
            "inference."
        ),
    )
    unit: Literal["milliseconds_per_merchant_window"] = "milliseconds_per_merchant_window"
    is_full_workload_pass: Literal[False] = False
    note: str = (
        "Measured on a bounded sample of merchant-windows, not on every window the workload "
        "would produce. Characterises per-window cost; not an exhaustive detection pass."
    )


class MemoryMetrics(BaseModel):
    """Exactly one memory number is measured, and this names it precisely (Part 13).

    `tracemalloc` reports Python heap allocation that the interpreter itself tracks. It
    does NOT include process RSS, interpreter overhead, native allocations inside numpy or
    scikit-learn, or SQLite's own page cache. A UI that labels this "peak memory" overstates
    what was measured, which is why the field carries its method in its name.
    """

    metric: Literal["tracemalloc_traced_python_heap"] = "tracemalloc_traced_python_heap"
    peak_traced_python_heap_mb: float | None
    includes_process_rss: Literal[False] = False
    includes_native_allocations: Literal[False] = False
    description: str = (
        "Peak Python heap allocation tracked by tracemalloc during the run. Excludes process "
        "RSS and native allocations made inside numpy/scikit-learn/SQLite."
    )


class StorageMetrics(BaseModel):
    """Database file growth attributable to the run, measured before cleanup."""

    metric: Literal["sqlite_file_size_delta"] = "sqlite_file_size_delta"
    storage_delta_mb: float | None
    measured_before_cleanup: Literal[True] = True
    rows_deleted_on_cleanup: int | None = None
    description: str = (
        "Database file growth between the start and end of the run. Only available on "
        "file-backed SQLite. Can read as zero when the engine reuses pages an earlier "
        "benchmark's cleanup freed."
    )


class BenchmarkSampleTransaction(BaseModel):
    """One representative synthetic transaction from a benchmark workload (Part 6).

    Identifiers are the generator's own synthetic fingerprints. Veyra never holds a PAN,
    so there is no card number here to redact.
    """

    transaction_id: str
    timestamp: datetime
    merchant_id: str
    customer_id: str | None
    device_fingerprint: str | None
    instrument_fingerprint: str
    ip_fingerprint: str | None
    amount: str
    currency: str
    outcome_status: str | None
    ground_truth_is_abusive: bool
    ground_truth_scenario_id: str


class BenchmarkSamples(BaseModel):
    """Bounded, readable evidence from a workload that is far too large to return.

    The full workload is never returned — these are at most `per_bucket_cap` rows each,
    collected while generation ran.
    """

    legitimate: list[BenchmarkSampleTransaction]
    fraud: list[BenchmarkSampleTransaction]
    random: list[BenchmarkSampleTransaction]
    per_bucket_cap: int
    is_full_workload: Literal[False] = False
    ground_truth_semantics: str = (
        "ground_truth_is_abusive is the synthetic label the generator used to build this "
        "workload, not a real-world fraud determination."
    )


class BenchmarkResult(BaseModel):
    """Machine-readable result. Every numeric field here was measured or is null — nothing
    is extrapolated from a smaller run to a size that was not executed."""

    # --- what was asked for, what was allowed, what happened -------------------------
    status: BenchmarkStatus = Field(
        ...,
        description=(
            "Terminal outcome. `completed` means the (possibly capped) target was fully "
            "processed. A run that hit the wall-clock budget is `stopped_early`, never "
            "`completed`."
        ),
    )
    stop_reason: StopReason | None = None
    requested_workload_size: int
    capped_workload_size: int = Field(
        ...,
        description=(
            "The workload the run actually aimed at, after the safety ceiling was applied. "
            "This is a TARGET, not an outcome — a run that hits the wall-clock budget stops "
            "below it. traffic.generated_events is the only field that says what actually ran."
        ),
    )
    capped: bool = Field(
        ...,
        description=(
            "True when capped_workload_size < requested_workload_size because of the "
            "safety ceiling. Independent of status: a run can be both capped and stopped_early."
        ),
    )
    workload_tier: WorkloadTier
    scenario_mix: str
    benchmark_mode: str
    duration_minutes: float

    # --- composition (Part 8) ---------------------------------------------------------
    traffic: TrafficComposition

    # --- the two scale questions, kept separate (Part 10) -----------------------------
    ingestion: IngestionScale
    computation: ComputationScale | None = Field(
        default=None, description="Null in ingestion mode, where no detection work is performed."
    )

    # --- resources, each naming its own measurement method (Part 13) -------------------
    memory: MemoryMetrics
    storage: StorageMetrics
    total_ms: float = Field(..., description="Wall-clock duration of the whole run, server-side.")

    # --- readable evidence (Part 6) ----------------------------------------------------
    samples: BenchmarkSamples

    environment: BenchmarkEnvironment
    limitations: list[str]


class BenchmarkRun(BaseModel):
    run_id: str
    status: BenchmarkStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    request: BenchmarkCreateRequest
    progress: BenchmarkProgress | None = None
    result: BenchmarkResult | None = None
    error: str | None = None


class BenchmarkCreateResponse(BaseModel):
    run_id: str
    status: BenchmarkStatus
    workload_tier: WorkloadTier
    requested_workload_size: int
    planned_executed_size: int
    capped: bool
    poll: dict[str, str]
    notice: str


class BenchmarkProgressResponse(BaseModel):
    """`GET /v2/demo/benchmarks/{run_id}/progress` — the cheap polling endpoint.

    `progress` is null before the worker starts and again once it finishes; poll until
    `finished` is true, then read the full result from `GET /v2/demo/benchmarks/{run_id}`.
    """

    run_id: str
    status: BenchmarkStatus
    progress: BenchmarkProgress | None
    finished: bool
    error: str | None = None


class WorkloadPreset(BaseModel):
    workload_size: int
    label: str
    tier: WorkloadTier
    will_be_capped: bool = Field(
        ...,
        description="True when this server's ceiling is below workload_size.",
    )
    executed_size_if_requested: int


class ScenarioMixOption(BaseModel):
    id: str
    label: str
    fraud_ratio: float | None = Field(
        ..., description="Null for 'custom', which defers to the request's own fraud_ratio."
    )


class BenchmarkModeOption(BaseModel):
    id: BenchmarkMode
    label: str


class BenchmarkGuardrails(BaseModel):
    hard_cap_events: int
    max_seconds: float
    chunk_size: int
    max_sample_windows: int
    concurrent_jobs: int
    sample_rows_per_bucket: int
    allow_experimental: bool = Field(
        ...,
        description=(
            "When false, an experimental-tier request is refused with HTTP 403 and status "
            "'rejected' before anything is generated. The UI should disable those presets."
        ),
    )


class BenchmarkPresetsResponse(BaseModel):
    """`GET /v2/demo/benchmarks/presets` — everything the UI needs to build the workload
    picker, including this server's real ceilings, so the UI never offers a size it would
    silently cap."""

    presets: list[WorkloadPreset]
    scenario_mixes: list[ScenarioMixOption]
    modes: list[BenchmarkModeOption]
    guardrails: BenchmarkGuardrails
    notice: str


class BenchmarkListResponse(BaseModel):
    retained_runs: int
    max_runs_retained: int
    ttl_seconds: int
