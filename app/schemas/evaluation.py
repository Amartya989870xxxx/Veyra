"""Evaluation contracts: run requests, metric blocks, threshold sweeps, comparisons."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import SplitName


class CostModel(BaseModel):
    """Explicit, synthetic cost assumptions. Documented, never presented as industry data."""

    model_config = ConfigDict(extra="forbid")

    fn_cost_multiplier: float = Field(default=1.0, ge=0)
    fp_cost_multiplier: float = Field(default=0.25, ge=0)
    review_cost_flat: float = Field(default=40.0, ge=0)
    chargeback_fee_flat: float = Field(default=750.0, ge=0)
    currency: str = "INR"
    note: str = (
        "Synthetic assumptions chosen for this prototype and configurable via environment. "
        "They are not sourced industry benchmarks."
    )


class ClassificationMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    false_positive_rate: float
    false_negative_rate: float
    accuracy: float
    support_positive: int
    support_negative: int
    pr_auc: float | None = None
    roc_auc: float | None = None


class LossMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_loss: float
    fn_loss: float
    fp_loss: float
    review_loss: float
    prevented_loss: float
    blocked_legitimate_gmv: float
    allowed_abusive_gmv: float
    review_count: int
    review_rate: float
    block_rate: float
    allow_rate: float


class ThresholdPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_threshold: float
    block_threshold: float
    precision: float
    recall: float
    f1: float
    false_positive_rate: float
    false_negative_rate: float
    expected_loss: float
    blocked_legitimate_gmv: float
    prevented_loss: float
    review_rate: float


class SliceMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slice_name: str
    count: int
    metrics: ClassificationMetrics
    note: str | None = None


class DetectorResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    detector: str
    split: SplitName
    metrics: ClassificationMetrics
    loss: LossMetrics
    thresholds: dict[str, float] = Field(default_factory=dict)
    latency_ms_p50: float | None = None
    latency_ms_p95: float | None = None
    slices: list[SliceMetrics] = Field(default_factory=list)


class EvaluationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_path: str | None = Field(
        default=None, description="Defaults to the newest dataset in the artifact directory"
    )
    seed: int = 42
    detectors: list[str] = Field(default_factory=lambda: ["rules", "txn_ml", "veyra"])
    cost_model: CostModel | None = None
    notes: str | None = Field(default=None, max_length=500)


class EvaluationRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    dataset_id: str | None = None
    dataset_summary: dict[str, Any] = Field(default_factory=dict)
    cost_model: CostModel | None = None
    results: list[DetectorResult] = Field(default_factory=list)
    threshold_sweep: dict[str, list[ThresholdPoint]] = Field(default_factory=dict)
    leakage_check: dict[str, Any] = Field(default_factory=dict)
    report_path: str | None = None
    error: str | None = None
