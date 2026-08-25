"""End-to-end evaluation runner.

Protocol, and the discipline behind it:

1. Load (or generate) a benchmark and split it **by group**, stratified by scenario.
2. Fit population baselines on **train only**.
3. Extract features in one chronological, past-only pass.
4. Train the model bundle on **train only**.
5. Choose each detector's operating point on **validation**, by minimum expected loss under
   a review-capacity cap.
6. Apply those frozen thresholds to the **holdout**, once, and report.

The holdout is passed to a tuner at no point in this file. Every detector — including both
baselines — gets its own tuned operating point, so the comparison is between well-configured
systems rather than between Veyra and a strawman.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.core.config import get_settings
from app.core.ids import run_id as new_run_id
from app.core.logging import get_logger
from app.evaluation.dataset import Dataset, SplitResult, load_dataset, split_dataset
from app.evaluation.detectors import RulesDetector, TransactionMLDetector, VeyraDetector
from app.evaluation.metrics import (
    calibration_error,
    choose_operating_point,
    classification_metrics,
    cost_model_from_settings,
    decisions_from_scores,
    expected_loss,
    threshold_sweep,
)
from app.evaluation.scoring import FeatureFrame, extract_features, split_frame
from app.evaluation.trainer import train_bundle
from app.features.baselines import Baselines
from app.risk.models import ModelBundle
from app.schemas.enums import Decision, SplitName
from app.schemas.evaluation import (
    CostModel,
    DetectorResult,
    EvaluationRunResponse,
    SliceMetrics,
    ThresholdPoint,
)

log = get_logger(__name__)

MAX_REVIEW_RATE = 0.25
"""Review-capacity cap used when choosing an operating point. Reviews are cheap per unit in
this cost model and prevent all loss, so an unconstrained optimiser would simply review
everything — an operating point no risk team could actually staff."""


def _slice_metrics(
    frame: FeatureFrame, scores: np.ndarray, decisions: list[str]
) -> list[SliceMetrics]:
    """Per-population breakdowns. Hard negatives and legitimate automation come first,
    because those are where this system is most likely to be quietly harmful."""
    flagged = np.asarray([0 if d == Decision.ALLOW else 1 for d in decisions])
    slices: list[SliceMetrics] = []

    def add(name: str, mask: np.ndarray, note: str | None = None) -> None:
        if not mask.any():
            return
        slices.append(
            SliceMetrics(
                slice_name=name,
                count=int(mask.sum()),
                metrics=classification_metrics(
                    frame.labels[mask], flagged[mask],
                    scores[mask] if len(set(frame.labels[mask].tolist())) == 2 else None,
                ),
                note=note,
            )
        )

    if frame.hard_negatives is not None:
        add(
            "hard_negatives",
            frame.hard_negatives.astype(bool) & (frame.labels == 0),
            "Legitimate traffic engineered to look suspicious. Any flag here is a false positive.",
        )

    classes = np.asarray(frame.label_classes)
    add("legit_agent", classes == "LEGIT_AGENT",
        "Legitimate automation. Flags here are the Kill Test 2 failure mode.")
    add("legit_human", classes == "LEGIT_HUMAN")
    add("coordinated_abuse", classes == "COORDINATED_ABUSE",
        "The target loss class. Recall here is the headline detection number.")
    add("suspicious_automation", classes == "SUSPICIOUS_AUTOMATION")

    scenarios = np.asarray(frame.scenarios)
    for scenario in sorted(set(frame.scenarios)):
        add(f"scenario:{scenario}", scenarios == scenario)

    return slices


def _detection_lead_time(frame: FeatureFrame, decisions: list[str]) -> dict:
    """How far into a campaign the first flag lands.

    Because the context window is past-only, the first transaction of a campaign has no
    campaign context by construction. This measures the cost of that honesty.
    """
    per_campaign: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for i, campaign_id in enumerate(frame.campaign_ids):
        if campaign_id:
            per_campaign[campaign_id].append((i, decisions[i]))

    positions: list[int] = []
    undetected = 0
    for members in per_campaign.values():
        flagged_at = next(
            (rank for rank, (_, decision) in enumerate(members) if decision != Decision.ALLOW),
            None,
        )
        if flagged_at is None:
            undetected += 1
        else:
            positions.append(flagged_at)

    return {
        "campaigns_evaluated": len(per_campaign),
        "campaigns_detected": len(positions),
        "campaigns_undetected": undetected,
        "median_transactions_before_first_flag": (
            float(np.median(positions)) if positions else None
        ),
        "mean_transactions_before_first_flag": (
            round(float(np.mean(positions)), 3) if positions else None
        ),
        "note": (
            "Past-only context means the first transaction of a campaign has no cluster to "
            "observe yet. A value of 0 means the campaign was flagged on its first event."
        ),
    }


def _evaluate_detector(
    name: str,
    validation: FeatureFrame,
    holdout: FeatureFrame,
    val_scores: np.ndarray,
    holdout_scores: np.ndarray,
    cost_model: CostModel,
    latency_p50: float | None = None,
    latency_p95: float | None = None,
) -> tuple[DetectorResult, DetectorResult, list[ThresholdPoint], dict]:
    sweep = threshold_sweep(val_scores, validation.labels, validation.amounts, cost_model)
    operating = choose_operating_point(sweep, max_review_rate=MAX_REVIEW_RATE)

    results: dict[str, DetectorResult] = {}
    for split_name, frame, scores in (
        ("validation", validation, val_scores),
        ("holdout", holdout, holdout_scores),
    ):
        decisions = decisions_from_scores(
            scores, operating.review_threshold, operating.block_threshold
        )
        flagged = [0 if d == Decision.ALLOW else 1 for d in decisions]
        results[split_name] = DetectorResult(
            detector=name,
            split=SplitName(split_name),
            metrics=classification_metrics(frame.labels, flagged, scores),
            loss=expected_loss(decisions, frame.labels, frame.amounts, cost_model),
            thresholds={
                "review": operating.review_threshold,
                "block": operating.block_threshold,
                "max_review_rate": MAX_REVIEW_RATE,
            },
            latency_ms_p50=latency_p50,
            latency_ms_p95=latency_p95,
            slices=_slice_metrics(frame, scores, decisions),
        )

    holdout_decisions = decisions_from_scores(
        holdout_scores, operating.review_threshold, operating.block_threshold
    )
    extra = {
        "calibration_error_holdout": calibration_error(holdout_scores, holdout.labels),
        "lead_time_holdout": _detection_lead_time(holdout, holdout_decisions),
    }
    return results["validation"], results["holdout"], sweep, extra


def run_evaluation(
    dataset: Dataset | None = None,
    dataset_path: str | Path | None = None,
    seed: int = 42,
    detectors: list[str] | None = None,
    cost_model: CostModel | None = None,
    model_dir: str | Path | None = None,
    notes: str | None = None,
) -> tuple[EvaluationRunResponse, ModelBundle | None, SplitResult]:
    settings = get_settings()
    detectors = detectors or ["rules", "txn_ml", "veyra"]
    cost_model = cost_model or cost_model_from_settings(settings)
    run_id = new_run_id()
    started_at = datetime.now(timezone.utc)
    clock = time.perf_counter()

    if dataset is None:
        if dataset_path is None:
            raise ValueError("either a dataset or a dataset_path is required")
        dataset = load_dataset(dataset_path)

    split = split_dataset(dataset, seed=seed)
    log.info("dataset_split", extra=split.summary())

    baselines = Baselines.fit(split.train.transactions)
    frame = extract_features(dataset, baselines=baselines)
    parts = split_frame(frame, split.assignment)
    train, validation, holdout = parts["train"], parts["validation"], parts["holdout"]

    bundle: ModelBundle | None = None
    if "veyra" in detectors or "txn_ml" in detectors:
        bundle = train_bundle(train, seed=seed, dataset_id=dataset.dataset_id)

    latency_p50 = float(np.percentile(frame.latency_ms, 50)) if frame.latency_ms else None
    latency_p95 = float(np.percentile(frame.latency_ms, 95)) if frame.latency_ms else None

    scorers = {}
    if "rules" in detectors:
        scorers["rules"] = RulesDetector()
    if "txn_ml" in detectors and bundle is not None:
        scorers["txn_ml"] = TransactionMLDetector(model=bundle.baseline_txn_only)
    if "veyra" in detectors and bundle is not None:
        scorers["veyra"] = VeyraDetector(bundle)

    results: list[DetectorResult] = []
    sweeps: dict[str, list[ThresholdPoint]] = {}
    diagnostics: dict[str, dict] = {}
    chosen_thresholds: dict[str, dict] = {}

    for name, detector in scorers.items():
        val_scores = detector.score(validation)
        holdout_scores = detector.score(holdout)
        val_result, holdout_result, sweep, extra = _evaluate_detector(
            name, validation, holdout, val_scores, holdout_scores, cost_model,
            latency_p50 if name == "veyra" else None,
            latency_p95 if name == "veyra" else None,
        )
        results.extend([val_result, holdout_result])
        sweeps[name] = sweep
        diagnostics[name] = extra
        chosen_thresholds[name] = holdout_result.thresholds
        log.info(
            "detector_evaluated",
            extra={
                "detector": name,
                "holdout_precision": holdout_result.metrics.precision,
                "holdout_recall": holdout_result.metrics.recall,
                "holdout_expected_loss": holdout_result.loss.expected_loss,
            },
        )

    if bundle is not None:
        bundle.thresholds = {
            "review": chosen_thresholds.get("veyra", {}).get("review", 0.45),
            "block": chosen_thresholds.get("veyra", {}).get("block", 0.75),
        }
        bundle.save(model_dir or settings.model_dir)
        baselines.save(Path(model_dir or settings.model_dir) / "baselines.json")

    response = EvaluationRunResponse(
        run_id=run_id,
        status="completed",
        created_at=started_at,
        completed_at=datetime.now(timezone.utc),
        dataset_id=dataset.dataset_id,
        dataset_summary={
            **dataset.manifest.get("counts", {}),
            "by_class": dataset.manifest.get("by_class", {}),
            "by_scenario": dataset.manifest.get("by_scenario", {}),
            "hard_negatives": dataset.manifest.get("hard_negatives", {}),
            "label_balance": dataset.manifest.get("label_balance", {}),
            "split_sizes": split.summary(),
            "elapsed_seconds": round(time.perf_counter() - clock, 2),
            "diagnostics": diagnostics,
            "fusion_weights": bundle.fusion.weights() if bundle and bundle.fusion else {},
            "fusion_intercept": bundle.fusion.intercept if bundle and bundle.fusion else None,
        },
        cost_model=cost_model,
        results=results,
        threshold_sweep=sweeps,
        leakage_check=split.leakage,
    )
    return response, bundle, split


def save_run(response: EvaluationRunResponse, report_dir: str | Path) -> tuple[Path, Path]:
    """Write the machine-readable run and the human-readable report side by side."""
    from app.evaluation.report import render_markdown

    root = Path(report_dir)
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / f"evaluation_{response.run_id}.json"
    json_path.write_text(response.model_dump_json(indent=2), encoding="utf-8")

    markdown_path = root / "evaluation_report.md"
    markdown_path.write_text(render_markdown(response), encoding="utf-8")

    latest = root / "latest_run.json"
    latest.write_text(json.dumps({"run_id": response.run_id, "path": str(json_path)}), "utf-8")
    return json_path, markdown_path
