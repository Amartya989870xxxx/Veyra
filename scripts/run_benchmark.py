"""Veyra v2 Benchmark Runner (Phase 7).

Executes the full comparative evaluation suite across Detectors A, B, and C:
- Detector A: Volume-only deviation baseline
- Detector B: Contextual ML strong baseline (Families A–I)
- Detector C: Veyra Graph & Multi-Window Fusion (Families A–J)

Generates the research thesis benchmark report at research/BENCHMARK_RESULTS.md.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.evaluation.report import generate_evaluation_markdown_report
from app.evaluation.runner import EvaluationRunner
from data.generators.pipeline import generate_benchmark_dataset


def main() -> None:
    print("=" * 70)
    print(" Veyra v2 — Comprehensive Fraud Spike Detection Benchmark")
    print("=" * 70)

    start_date = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)
    n_merchants = 3
    days = 4

    print(f"\n[1/3] Generating synthetic benchmark dataset ({n_merchants} merchants, {days} days)...")
    dataset = generate_benchmark_dataset(
        n_merchants=n_merchants,
        days=days,
        start_date=start_date,
        inject_scenarios=True,
        seed=42,
    )
    print(f"      Total transactions: {len(dataset.transactions):,}")
    print(f"      Total scored windows: {len(dataset.window_labels):,}")

    print("\n[2/3] Executing comparative evaluation runner...")
    runner = EvaluationRunner()
    results = runner.run_benchmark(dataset=dataset, review_capacity_cap=0.15)

    print("\n[3/3] Generating research evaluation report...")
    report_md = generate_evaluation_markdown_report(results)

    # NOT research/BENCHMARK_RESULTS.md: that file is the multi-seed experiment's output
    # (scripts/run_experiment.py + scripts/generate_experiment_report.py) and this
    # single-seed 3-merchant/4-day run must not overwrite it with a statistically
    # underpowered result.
    output_path = Path("research/BENCHMARK_SMOKE_RUN.md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_md, encoding="utf-8")
    print(f"      Report saved to: {output_path.resolve()}")

    print("\n" + "=" * 70)
    print(" BENCHMARK COMPLETE — SUMMARY")
    print("=" * 70)
    for name, r in results.results_by_detector.items():
        print(
            f"  {name:15s} | PR-AUC: {r.window_metrics.pr_auc:.3f} "
            f"| Recall: {r.incident_metrics.incident_recall:.1%} "
            f"| Latency p50: {r.incident_metrics.latency_p50_minutes:.1f}m "
            f"| False Alerts/Day: {r.false_alerts_per_merchant_day:.2f} "
            f"| Exp. Loss: ₹{r.expected_financial_loss:,.2f}"
        )
    print("=" * 70)


if __name__ == "__main__":
    main()
