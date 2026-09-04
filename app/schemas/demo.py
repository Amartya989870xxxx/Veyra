"""Response schemas for the demo scoring path (`/v2/demo/*`).

These exist so a frontend never has to infer meaning from an untyped dict — every shape
returned by the demo endpoints is declared here once, per Part 8. Nothing in this module
is used by production scoring (`app/serving/scoring_service.py`) or the offline
evaluation harness (`app/evaluation/`); it is demo-path only, deliberately kept separate.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Provenance(BaseModel):
    """Stamped on every demo response so the frontend never has to guess where data
    came from. Every field is a fixed literal — there is exactly one honest value for
    each on this code path.

    `not_production_data: true` was renamed to `is_production_data: false` so the field
    reads the same way round as its name; carrying both would have meant two booleans
    that must always disagree, which is a bug waiting to happen.
    """

    model_config = ConfigDict(frozen=True)

    data_source: Literal["synthetic"] = "synthetic"
    generated_for: Literal["demo_run"] = "demo_run"
    is_production_data: Literal[False] = False
    ground_truth_semantics: str = (
        "Ground-truth fields are the synthetic scenario label the generator used to "
        "construct this traffic. They are not a real-world fraud determination, and they "
        "are never read when computing risk_score."
    )


StageStatus = Literal["pending", "running", "completed", "failed", "skipped"]
"""A stage a demo response returns has already finished, so in practice only
`completed` and `failed` appear on `/v2/demo/simulate`. `pending` and `running` exist
because the frontend models the same stage list while it animates a run, and it should
not have to invent status values the backend never names."""


class PipelineStage(BaseModel):
    """One real, server-timed step of a demo run.

    `duration_ms` is always a measured `time.perf_counter()` delta around the actual
    work — never invented, estimated, or padded. `started_at`/`ended_at` are wall-clock
    stamps for the same interval, so a frontend can lay stages on a real timeline instead
    of accumulating durations and hoping they line up.
    """

    sequence: int = Field(..., description="1-based execution order. Stable across runs.")
    id: str
    label: str
    status: StageStatus
    duration_ms: float = Field(
        ..., description="Measured server-side. Excludes any frontend presentation delay."
    )
    started_at: datetime
    ended_at: datetime
    detail: dict[str, Any] | None = None


class DemoModelInfoOut(BaseModel):
    """What the demo scoring model is and whether this call paid its one-time training
    cost. `trained_this_call=False` on every request after the first in the process."""

    model_name: str
    model_version: str
    trained_this_call: bool
    was_cached: bool = Field(
        ...,
        description=(
            "True when this request reused the process-cached fitted model. Exactly the "
            "inverse of trained_this_call, named positively because that is how the UI "
            "reads it: a cold first call pays ~18-20s, every later call does not."
        ),
    )
    trained_at: datetime
    training_seed: int
    training_window_start: datetime
    training_window_end: datetime
    training_transactions: int
    training_windows: int
    train_duration_ms: float


class GroundTruth(BaseModel):
    """The scenario's own synthetic ground truth — which transactions the generator
    actually marked abusive. Display-only: `app/api/v2/demo.py` never reads this to
    compute `risk_score`, and this model exists precisely so a reviewer can check that
    claim against the response shape rather than trust it."""

    scenario_id: str
    scenario_is_labelled_attack: bool
    abusive_transaction_count: int
    total_transaction_count: int
    note: str = (
        "This is the synthetic scenario's own ground-truth label, shown for comparison. "
        "It is not read when computing risk_score above — that comes from "
        "DemoModelService.score() on the extracted feature vector."
    )


class EntityCounts(BaseModel):
    customers: int
    devices: int
    instruments: int
    ip_addresses: int

    @property
    def total(self) -> int:
        return self.customers + self.devices + self.instruments + self.ip_addresses


class ServerTiming(BaseModel):
    """The backend's own measured cost, and nothing else.

    This exists to keep one distinction unambiguous: `server_processing_ms` is real
    computation measured with `time.perf_counter()`. If the Detection UI holds a loading
    animation for several seconds, that is **presentation time the frontend adds** and it
    must never be attributed to the backend or displayed as analysis cost. The backend
    does not sleep, pad, or stretch this number.
    """

    server_processing_ms: float = Field(
        ..., description="Sum of real server-side work for this request."
    )
    stage_count: int
    measurement: Literal["time.perf_counter"] = "time.perf_counter"
    includes_frontend_presentation_time: Literal[False] = False
    note: str = (
        "Server-side processing time only. Any additional delay the UI shows is frontend "
        "presentation time and is not measured here."
    )


class EntitySummary(BaseModel):
    """`GET /v2/demo/runs/{run_id}/entities` — who appeared in the window and how
    concentrated the graph was. Counts come from the run's own evidence features."""

    run_id: str
    counts: EntityCounts
    total_entities: int
    transactions: int
    instruments_per_customer: float | None = Field(
        default=None,
        description="Null when the window had no customers; otherwise instruments / customers.",
    )
    transactions_per_device: float | None = None
    largest_cluster_volume_share: float | None = Field(
        default=None, description="Family J: share of window volume in the largest entity cluster."
    )
    bipartite_gini: float | None = Field(
        default=None,
        description="Family J: concentration of the customer-instrument bipartite graph.",
    )
    provenance: Provenance = Provenance()


class DemoRunMeta(BaseModel):
    """Metadata for one demo run, returned both inline in the simulation response and
    from `GET /v2/demo/runs/{run_id}`."""

    run_id: str
    created_at: datetime
    scenario_id: str
    merchant_category: str
    merchant_id: str
    intensity: float = Field(
        ..., description="Scenario intensity multiplier this run was generated at."
    )
    seed: int
    window_size: str
    window_end: datetime
    total_transactions: int
    time_span_seconds: float
    entity_counts: EntityCounts
    total_entities: int
    feature_count: int
    baseline_confidence: str
    baselines_available: bool
    model: DemoModelInfoOut
    risk_score: float = Field(
        ..., description="Model output. Repeated here so run metadata is self-contained."
    )
    action_tier: str
    total_server_duration_ms: float
    timing: ServerTiming
    provenance: Provenance = Provenance()


class SimulationReportResponse(BaseModel):
    """`POST /v2/demo/simulate` response. Replaces the pre-Part-1 shape whose
    `risk_score` was derived from the scenario's own attack label."""

    run: DemoRunMeta
    scenario_name: str
    risk_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="DemoModelService.score() output: a real fitted-model inference.",
    )
    action_tier: str
    recommended_defensive_control: str | None
    model_matches_ground_truth: bool = Field(
        ...,
        description=(
            "Whether the tier this run reached (REVIEW/RESTRICT vs OBSERVE/ALERT) agrees "
            "with the scenario's ground-truth label. Informational, computed after scoring."
        ),
    )
    ground_truth: GroundTruth
    explanation: str
    financial_exposure: dict[str, Any]
    top_feature_deviations: list[dict[str, Any]]
    entity_graph: dict[str, Any]
    features_summary: dict[str, float]
    stages: list[PipelineStage] = Field(
        ...,
        description=(
            "Real per-stage server timings, in execution order. Every duration is measured; "
            "none is padded to make the UI feel slower."
        ),
    )
    export_formats: dict[str, str]


class TransactionRow(BaseModel):
    """One synthetic transaction, redacted to the same fingerprint-only identifiers the
    rest of Veyra uses. Never a raw card number — `instrument_token` is the generator's
    own `instrument_fp`, which was already a synthetic fingerprint, never a PAN."""

    transaction_id: str
    timestamp: datetime
    merchant_id: str
    customer_id: str | None
    instrument_token: str
    device_id: str | None
    ip_token: str | None
    amount: str
    currency: str
    outcome_status: str | None
    outcome_failure_code: str | None
    ground_truth_is_abusive: bool
    ground_truth_is_spike: bool
    ground_truth_scenario_id: str


class TransactionPage(BaseModel):
    run_id: str
    page: int
    page_size: int
    total_transactions: int
    total_pages: int
    items: list[TransactionRow]
    provenance: Provenance = Provenance()


class FeatureValue(BaseModel):
    feature_id: str
    family: str
    value: float
    deviation_mad: float | None = None
    is_model_input: bool
    is_evidence_only: bool


class FeatureSummary(BaseModel):
    run_id: str
    families: dict[str, list[FeatureValue]]
    model_feature_count: int
    evidence_feature_count: int
    baseline_confidence: str
    provenance: Provenance = Provenance()


class RunSummary(BaseModel):
    run_id: str
    scenario_id: str
    window_size: str
    window_end: datetime
    total_transactions: int
    abusive_transactions: int
    benign_transactions: int
    time_range_start: datetime
    time_range_end: datetime
    entity_counts: EntityCounts
    action_tier: str
    risk_score: float
    provenance: Provenance = Provenance()


class RunRetention(BaseModel):
    """How long this run stays inspectable. Surfaced so the UI can tell a reviewer why a
    bookmarked run_id eventually 404s instead of presenting it as an error."""

    storage: Literal["in-memory, per-process"] = "in-memory, per-process"
    max_runs_retained: int
    ttl_seconds: int


class RunLinks(BaseModel):
    transactions: str
    features: str
    summary: str
    entities: str


class RunDetail(BaseModel):
    """`GET /v2/demo/runs/{run_id}` — everything about one run except its paged data,
    plus the links that reach it. Typed rather than a loose dict so the frontend reads
    fields off a contract instead of inferring them (Part 8)."""

    run_id: str
    created_at: datetime
    scenario_id: str
    merchant_id: str
    merchant_category: str
    window_size: str
    window_end: datetime
    total_transactions: int
    abusive_transactions: int
    scenario_is_labelled_attack: bool = Field(
        ...,
        description=(
            "The scenario's synthetic ground-truth label. Display-only: it played no part "
            "in producing risk_score."
        ),
    )
    risk_score: float
    action_tier: str
    entity_counts: EntityCounts
    time_range_start: datetime
    time_range_end: datetime
    entity_graph: dict[str, Any]
    links: RunLinks
    retention: RunRetention
    provenance: Provenance = Provenance()
