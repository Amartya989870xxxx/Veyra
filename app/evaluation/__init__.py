"""Veyra v2 evaluation, incident matching, and reporting package (Phase 5)."""

from app.evaluation.incidents import (
    FlaggedWindowRecord,
    GroundTruthIncident,
    IncidentMatchingResults,
    PredictedIncident,
    assemble_predicted_incidents,
    match_incidents,
)
from app.evaluation.metrics import WindowMetrics, compute_window_metrics
from app.evaluation.report import generate_evaluation_markdown_report
from app.evaluation.runner import (
    BenchmarkSuiteResults,
    DetectorBenchmarkResult,
    EvaluationRunner,
)

__all__ = [
    "WindowMetrics",
    "compute_window_metrics",
    "PredictedIncident",
    "GroundTruthIncident",
    "IncidentMatchingResults",
    "FlaggedWindowRecord",
    "assemble_predicted_incidents",
    "match_incidents",
    "EvaluationRunner",
    "DetectorBenchmarkResult",
    "BenchmarkSuiteResults",
    "generate_evaluation_markdown_report",
]
