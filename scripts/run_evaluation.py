#!/usr/bin/env python3
"""Run the full evaluation: baselines, Veyra, threshold sweep, expected loss, report.

    python scripts/run_evaluation.py
    python scripts/run_evaluation.py --dataset artifacts/datasets/ds_xxx --seed 42
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.evaluation.dataset import find_latest_dataset  # noqa: E402
from app.evaluation.runner import run_evaluation, save_run  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Veyra evaluation pipeline")
    parser.add_argument("--dataset", default=None, help="Dataset directory")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--detectors", default="rules,txn_ml,veyra", help="Comma-separated detector names"
    )
    parser.add_argument("--report-dir", default=None)
    parser.add_argument("--model-dir", default=None)
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level, "console")

    dataset_path = args.dataset or find_latest_dataset(Path(settings.artifact_dir) / "datasets")
    if dataset_path is None:
        print(
            "No dataset found. Run `python scripts/generate_dataset.py` first.",
            file=sys.stderr,
        )
        return 1

    response, bundle, _split = run_evaluation(
        dataset_path=dataset_path,
        seed=args.seed,
        detectors=[d.strip() for d in args.detectors.split(",") if d.strip()],
        model_dir=args.model_dir or settings.model_dir,
    )
    json_path, markdown_path = save_run(response, args.report_dir or settings.report_dir)

    print(f"\nRun {response.run_id} complete.")
    print(f"  JSON report:     {json_path}")
    print(f"  Markdown report: {markdown_path}")
    if bundle:
        print(f"  Model bundle:    {args.model_dir or settings.model_dir}")

    print("\nHoldout results:")
    print(f"  {'detector':10} {'precision':>10} {'recall':>8} {'F1':>7} {'PR-AUC':>8} "
          f"{'FP rate':>9} {'expected loss':>15}")
    for result in response.results:
        if str(result.split) != "holdout":
            continue
        m = result.metrics
        print(f"  {result.detector:10} {m.precision:10.4f} {m.recall:8.4f} {m.f1:7.4f} "
              f"{(m.pr_auc or 0):8.4f} {m.false_positive_rate:9.4f} "
              f"{result.loss.expected_loss:15,.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
