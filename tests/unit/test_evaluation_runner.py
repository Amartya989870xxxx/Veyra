"""Unit tests for EvaluationRunner and reporting pipeline (Phase 5.1 & 5.2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import pytest

from app.evaluation.report import generate_evaluation_markdown_report
from app.evaluation.runner import EvaluationRunner
from data.generators.pipeline import generate_benchmark_dataset


def test_evaluation_runner_executes_benchmark_pipeline():
    """Verify EvaluationRunner executes on temporal train/val/test splits and generates markdown report."""
    start_ts = datetime(2026, 3, 2, 0, 0, 0, tzinfo=UTC)

    # 2-day micro-benchmark with 2 merchants
    dataset = generate_benchmark_dataset(
        n_merchants=2,
        days=2,
        start_date=start_ts,
        seed=42,
    )

    runner = EvaluationRunner()
    results = runner.run_benchmark(dataset, review_capacity_cap=0.20)

    assert "volume_only" in results.results_by_detector
    assert "contextual_ml" in results.results_by_detector
    assert "veyra_fusion" in results.results_by_detector

    report = generate_evaluation_markdown_report(results)
    assert "# Veyra v2 — Fraud Spike Benchmark Evaluation Report" in report
    assert "Comparative Detector Performance" in report
