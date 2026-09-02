#!/usr/bin/env python3
"""Multi-seed comparative + ablation experiment for Veyra detectors.

Answers one question honestly: **does each additional component earn its complexity?**

Protocol (unchanged from the existing runner, and deliberately so):
- Chronological TRAIN / VALIDATION / TEST. No shuffling across splits, ever.
- Models fit on TRAIN only.
- Operating thresholds chosen on VALIDATION only.
- TEST scored exactly once per detector per seed.
- Window features come from the same `FeatureEngine` the online path uses, through the
  same half-open [start, end) window index, so nothing here can see its own future.

Reporting rule: a metric is printed for a scenario only if that scenario is present in
the split being reported on. Absent scenarios print NOT PRESENT — NOT EVALUATED, never 0.

Usage:
    PYTHONPATH=. python scripts/run_experiment.py [--seeds 42,43,44] [--merchants 8]
                                                  [--days 10] [--quick]
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from app.decision.operating_point import choose_operating_thresholds
from app.evaluation.coverage import NOT_EVALUATED, compute_dataset_coverage
from app.evaluation.incident_metrics import evaluate_incident_detection
from app.evaluation.incidents import (
    FlaggedWindowRecord,
    GroundTruthIncident,
    assemble_predicted_incidents,
    match_incidents,
)
from app.evaluation.indexing import TransactionWindowIndex
from app.features.baselines import fit_baselines_from_window_history
from app.features.engine import FeatureEngine
from app.models_ml.base import BaseDetector
from app.models_ml.contextual import ContextualMLDetector
from app.models_ml.fusion import VeyraFusionDetector
from app.models_ml.volume import VolumeOnlyDetector
from app.registry import assert_no_downstream
from app.schemas.enums import SplitName, WindowLabel
from data.generators.pipeline import (
    ATTACK_SCENARIOS,
    HARD_NEGATIVE_SCENARIOS,
    generate_benchmark_dataset,
)

# --- Cost assumptions (ASSUMPTIONS, not Razorpay economics; ADR-005) -----------------
# Held fixed across every detector. Tuning these to favour one detector would be exactly
# the kind of result-shaping this experiment exists to avoid.
ASSUMED_FALSE_NEGATIVE_COST_INR = 5_000.0   # merchant loss from a missed fraud incident
ASSUMED_FALSE_POSITIVE_COST_INR = 250.0     # analyst review cost of a false alert


class FeatureSubsetDetector(BaseDetector):
    """Gradient-boosted detector restricted to an explicit feature-prefix allowlist.

    Exists only to isolate components for ablation — same learner and hyper-parameters
    as the shipped detectors so a difference in score is attributable to the feature
    set rather than to a different model.
    """

    def __init__(self, name: str, include_prefixes: tuple[str, ...], exclude_dev: bool = False) -> None:
        super().__init__(name=name)
        self.include_prefixes = include_prefixes
        self.exclude_dev = exclude_dev
        self.model = HistGradientBoostingClassifier(max_iter=100, random_state=42, min_samples_leaf=2)

    def _select(self, feature_names: list[str]) -> list[str]:
        selected = []
        for f in feature_names:
            if self.exclude_dev and f.endswith("_dev"):
                continue
            if any(f.startswith(p) for p in self.include_prefixes):
                selected.append(f)
        assert_no_downstream(selected)
        return selected

    def fit(self, X, y):
        y_arr = np.asarray(y, dtype=int)
        if not X:
            return self
        self.feature_names = self._select(sorted(X[0].keys()))
        min_leaf = max(1, min(10, len(y_arr) // 4))
        self.model = HistGradientBoostingClassifier(
            max_iter=100, random_state=42, min_samples_leaf=min_leaf
        )
        self.model.fit(self._prepare_matrix(X, feature_columns=self.feature_names), y_arr)
        self.is_fitted = True
        return self

    def predict_proba(self, X):
        if not self.is_fitted:
            return np.zeros(len(X), dtype=np.float32)
        probs = self.model.predict_proba(self._prepare_matrix(X, feature_columns=self.feature_names))
        return probs[:, 1] if probs.shape[1] == 2 else probs[:, 0]


@dataclass
class DetectorRunResult:
    name: str
    precision: float
    recall: float
    f1: float
    pr_auc: float
    roc_auc: float
    tn: int
    fp: int
    fn: int
    tp: int
    false_positive_rate: float
    false_negative_rate: float
    incident_recall: float
    incident_tp: int
    incident_fn: int
    incident_detection_rate: float
    """Share of ground-truth incidents with at least one flagged window inside them.

    Reported alongside `incident_recall` because the two answer different questions and
    diverge sharply once a merchant has more than one incident in TEST.
    `match_incidents` does greedy 1-to-1 matching and `assemble_predicted_incidents`
    merges flagged windows separated by <=3 minutes, so a detector that correctly flags
    three separate attacks on one merchant can have all three collapse into a single
    predicted incident that is credited with catching only one of them. That is a
    measurement artifact, not a detection failure, and reporting only the 1-to-1 number
    would understate every detector equally but misleadingly.
    """
    incident_strict_recall: float
    mean_temporal_iou: float
    fragmentation_index: float
    merge_index: float
    incident_precision: float
    hard_negative_fps: dict[str, int]
    fraud_scenario_recall: dict[str, tuple[int, int]]
    expected_loss: float
    threshold: float


@dataclass
class SeedRunResult:
    seed: int
    n_test_windows: int
    test_fraud_episodes: int
    test_hard_negative_episodes: int
    test_fraud_scenarios: dict[str, int]
    test_hard_negative_scenarios: dict[str, int]
    coverage_text: str
    detectors: dict[str, DetectorRunResult] = field(default_factory=dict)
    dev_twins_are_raw_values: bool = False


def _extract_split(labels, txn_index, feature_engine):
    X, y, meta = [], [], []
    for w in labels:
        w_txns = txn_index.slice(
            merchant_id=w.merchant_id,
            start=w.window_end - w.window_size.delta,
            end=w.window_end,
        )
        vec = feature_engine.extract_window_features(
            merchant_id=w.merchant_id,
            window_size=w.window_size,
            window_end=w.window_end,
            transactions=w_txns,
        )
        X.append(vec.model_features)
        y.append(1 if w.label is WindowLabel.FRAUD_SPIKE else 0)
        meta.append(
            {
                "merchant_id": w.merchant_id,
                "window_size": w.window_size,
                "window_end": w.window_end,
                "label": w.label,
                "scenario": w.dominant_scenario_id,
                "gmv": float(vec.evidence.get("D.gmv", 0.0)),
            }
        )
    return X, np.array(y, dtype=int), meta


def _ground_truth_incidents(test_meta) -> list[GroundTruthIncident]:
    """Contiguous runs of FRAUD_SPIKE windows per (merchant, scenario) = one incident.

    Runs are broken on a gap of more than 5 minutes so two separate injections against
    the same merchant are not silently merged into one 'incident' (which would deflate
    the denominator and inflate recall).
    """
    from datetime import timedelta

    positives = [m for m in test_meta if m["label"] is WindowLabel.FRAUD_SPIKE]
    grouped: dict[tuple[str, str], list] = {}
    for m in positives:
        grouped.setdefault((m["merchant_id"], m["scenario"] or "attack"), []).append(m)

    incidents: list[GroundTruthIncident] = []
    for (merchant_id, scenario), rows in grouped.items():
        rows.sort(key=lambda r: r["window_end"])
        run = [rows[0]]
        for prev, cur in zip(rows, rows[1:]):
            if (cur["window_end"] - prev["window_end"]) <= timedelta(minutes=5):
                run.append(cur)
            else:
                incidents.append(_incident_from_run(merchant_id, scenario, run))
                run = [cur]
        incidents.append(_incident_from_run(merchant_id, scenario, run))
    return incidents


def _incident_from_run(merchant_id: str, scenario: str, run: list) -> GroundTruthIncident:
    return GroundTruthIncident(
        scenario_id=scenario,
        merchant_id=merchant_id,
        start_time=run[0]["window_end"] - run[0]["window_size"].delta,
        end_time=run[-1]["window_end"],
        is_attack=True,
        total_gmv=sum(r["gmv"] for r in run),
    )


def _evaluate_detector(det, X_val, y_val, X_test, y_test, test_meta, gt_incidents, review_cap) -> DetectorRunResult:
    val_probs = det.predict_proba(X_val)
    thresholds = choose_operating_thresholds(y_true=y_val, y_prob=val_probs, review_capacity_cap=review_cap)
    theta = thresholds.theta_review

    test_probs = det.predict_proba(X_test)
    y_pred = (test_probs >= theta).astype(int)

    n_pos = int(y_test.sum())
    pr_auc = float(average_precision_score(y_test, test_probs)) if 0 < n_pos < len(y_test) else 0.0
    roc_auc = float(roc_auc_score(y_test, test_probs)) if 0 < n_pos < len(y_test) else 0.5
    tn, fp, fn, tp = confusion_matrix(y_test, y_pred, labels=[0, 1]).ravel()

    flagged: list[FlaggedWindowRecord] = []
    hard_neg_fps: dict[str, int] = {}
    for prob, meta in zip(test_probs, test_meta):
        if prob >= theta:
            flagged.append(
                FlaggedWindowRecord(
                    merchant_id=meta["merchant_id"],
                    window_size=meta["window_size"],
                    window_end=meta["window_end"],
                    risk_score=float(prob),
                    gmv=meta["gmv"],
                )
            )
            if meta["label"] is not WindowLabel.FRAUD_SPIKE and meta["scenario"] in HARD_NEGATIVE_SCENARIOS:
                hard_neg_fps[meta["scenario"]] = hard_neg_fps.get(meta["scenario"], 0) + 1

    predicted_incidents = assemble_predicted_incidents(flagged)
    inc_metrics = match_incidents(predicted_incidents, gt_incidents)
    # Full taxonomy: detection (material overlap) vs strict 1-to-1 separation vs
    # boundary quality. See app/evaluation/incident_metrics.py for why both recalls
    # are reported and neither is presented alone.
    inc_report = evaluate_incident_detection(predicted_incidents, gt_incidents)

    # Per-fraud-scenario incident recall: was at least one window of the incident flagged?
    flagged_keys = {(m["merchant_id"], m["window_end"]) for m, p in zip(test_meta, test_probs) if p >= theta}
    scenario_recall: dict[str, tuple[int, int]] = {}
    for inc in gt_incidents:
        caught = any(
            key[0] == inc.merchant_id and inc.start_time <= key[1] <= inc.end_time for key in flagged_keys
        )
        hit, total = scenario_recall.get(inc.scenario_id, (0, 0))
        scenario_recall[inc.scenario_id] = (hit + (1 if caught else 0), total + 1)

    expected_loss = (
        inc_metrics.false_negative_count * ASSUMED_FALSE_NEGATIVE_COST_INR
        + int(fp) * ASSUMED_FALSE_POSITIVE_COST_INR
    )

    return DetectorRunResult(
        name=det.name,
        precision=float(precision_score(y_test, y_pred, zero_division=0)),
        recall=float(recall_score(y_test, y_pred, zero_division=0)),
        f1=float(f1_score(y_test, y_pred, zero_division=0)),
        pr_auc=pr_auc,
        roc_auc=roc_auc,
        tn=int(tn), fp=int(fp), fn=int(fn), tp=int(tp),
        false_positive_rate=float(fp / max(1, fp + tn)),
        false_negative_rate=float(fn / max(1, fn + tp)),
        incident_recall=inc_metrics.incident_recall,
        incident_tp=inc_metrics.true_positive_count,
        incident_fn=inc_metrics.false_negative_count,
        incident_detection_rate=inc_report.detection_recall,
        incident_strict_recall=inc_report.strict_match_recall,
        mean_temporal_iou=inc_report.mean_temporal_iou,
        fragmentation_index=inc_report.fragmentation_index,
        merge_index=inc_report.merge_index,
        incident_precision=inc_report.incident_precision,
        hard_negative_fps=hard_neg_fps,
        fraud_scenario_recall=scenario_recall,
        expected_loss=expected_loss,
        threshold=float(theta),
    )


def _fit_baseline_engine_on_train(train_labels, train_X, feature_engine):
    """Fit 168h median/MAD baselines from TRAIN windows only.

    The default evaluation path constructs `FeatureEngine()` with an *unfitted*
    `BaselineEngine`, which makes every `_dev` deviation twin equal to its raw feature
    ((value - 0.0) / max(1e-4, 1.0)). That means the robust seasonal baseline — the
    component the architecture docs treat as central — contributes nothing to any
    benchmarked number. This function exists so that claim can be *measured* as an
    ablation arm rather than assumed in either direction.

    Fit on TRAIN only: baselines derived from validation or test windows would be
    exactly the look-ahead this project's ADR-004 barrier exists to prevent.
    """
    history = [
        {
            "merchant_id": w.merchant_id,
            "window_size": w.window_size.value,
            "window_end": w.window_end,
            "features": feats,
        }
        for w, feats in zip(train_labels, train_X)
    ]
    return fit_baselines_from_window_history(history)


def run_single_seed(
    seed: int,
    n_merchants: int,
    days: int,
    injections: int,
    review_cap: float,
    fit_baselines: bool = False,
) -> SeedRunResult:
    print(f"\n--- seed {seed} ---", flush=True)
    t0 = time.time()
    dataset = generate_benchmark_dataset(
        n_merchants=n_merchants,
        days=days,
        start_date=datetime(2026, 3, 1, tzinfo=UTC),
        inject_scenarios=True,
        seed=seed,
        injections_per_split_per_merchant=injections,
        hard_negative_ratio=0.40,
    )
    print(f"  generated {len(dataset.transactions):,} txns / {len(dataset.window_labels):,} windows in {time.time()-t0:.1f}s", flush=True)

    coverage = compute_dataset_coverage(dataset)
    test_cov = coverage.get(SplitName.TEST)

    train_labels = [w for w in dataset.window_labels if dataset.split_for_timestamp(w.window_end) is SplitName.TRAIN]
    val_labels = [w for w in dataset.window_labels if dataset.split_for_timestamp(w.window_end) is SplitName.VALIDATION]
    test_labels = [w for w in dataset.window_labels if dataset.split_for_timestamp(w.window_end) is SplitName.TEST]

    txn_index = TransactionWindowIndex(dataset.transactions)
    feature_engine = FeatureEngine()

    t0 = time.time()
    X_train, y_train, _ = _extract_split(train_labels, txn_index, feature_engine)

    if fit_baselines:
        # Second pass with baselines fitted on TRAIN, so `_dev` features become real
        # MAD deviations instead of duplicates of their raw counterparts.
        baseline_engine = _fit_baseline_engine_on_train(train_labels, X_train, feature_engine)
        # TRAIN is transformed in-sample (standard, and confined to model fitting), so it
        # uses the permissive view. VAL/TEST use the strict engine, which raises
        # BaselineLeak if a baseline ever reaches past the window it scores.
        train_engine = FeatureEngine(baseline_engine=baseline_engine.with_in_fit_period_use(True))
        feature_engine = FeatureEngine(baseline_engine=baseline_engine)
        X_train, y_train, _ = _extract_split(train_labels, txn_index, train_engine)
        print("  refit features with TRAIN-fitted MAD baselines (frozen for VAL/TEST)", flush=True)

    X_val, y_val, _ = _extract_split(val_labels, txn_index, feature_engine)
    X_test, y_test, test_meta = _extract_split(test_labels, txn_index, feature_engine)
    print(f"  extracted features in {time.time()-t0:.1f}s", flush=True)

    # Empirical check: are `_dev` twins actually MAD-normalized deviations, or do they
    # equal the raw feature (which is what happens when no baselines were fit)?
    dev_equals_raw = False
    if X_train:
        sample = X_train[len(X_train) // 2]
        pairs = [(k, k[:-4]) for k in sample if k.endswith("_dev") and k[:-4] in sample]
        if pairs:
            dev_equals_raw = all(abs(sample[d] - sample[r]) < 1e-9 for d, r in pairs)

    gt_incidents = _ground_truth_incidents(test_meta)
    print(f"  TEST: {len(test_labels):,} windows, {int(y_test.sum()):,} positive, {len(gt_incidents)} gt incidents", flush=True)

    detectors: list[BaseDetector] = [
        VolumeOnlyDetector(),
        ContextualMLDetector(),
        VeyraFusionDetector(),
        # --- ablation arms (same learner, different feature subsets) ---
        FeatureSubsetDetector("ablation_graph_only", include_prefixes=("J.",)),
        FeatureSubsetDetector(
            "ablation_contextual_no_dev",
            include_prefixes=("A.", "B.", "C.", "D.", "E.", "F.", "G.", "H.", "I."),
            exclude_dev=True,
        ),
    ]

    results: dict[str, DetectorRunResult] = {}
    for det in detectors:
        t0 = time.time()
        det.fit(X_train, y_train)
        res = _evaluate_detector(det, X_val, y_val, X_test, y_test, test_meta, gt_incidents, review_cap)
        results[det.name] = res
        print(
            f"  {det.name:28s} PR-AUC={res.pr_auc:.3f} P={res.precision:.3f} R={res.recall:.3f} "
            f"F1={res.f1:.3f} det={res.incident_detection_rate:.1%} strict={res.incident_strict_recall:.1%} "
            f"IoU={res.mean_temporal_iou:.2f} merge={res.merge_index:.1f} "
            f"[{time.time()-t0:.1f}s]",
            flush=True,
        )

    return SeedRunResult(
        seed=seed,
        n_test_windows=len(test_labels),
        test_fraud_episodes=test_cov.fraud_episodes,
        test_hard_negative_episodes=test_cov.hard_negative_episodes,
        test_fraud_scenarios=test_cov.fraud_episodes_by_scenario,
        test_hard_negative_scenarios=test_cov.hard_negative_episodes_by_scenario,
        coverage_text="",
        detectors=results,
        dev_twins_are_raw_values=dev_equals_raw,
    )


def _agg(values: Sequence[float]) -> dict[str, float]:
    vals = list(values)
    return {
        "mean": statistics.fmean(vals),
        "std": statistics.pstdev(vals) if len(vals) > 1 else 0.0,
        "min": min(vals),
        "max": max(vals),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", default="42,43,44")
    parser.add_argument("--merchants", type=int, default=8)
    parser.add_argument("--days", type=int, default=10)
    parser.add_argument("--injections", type=int, default=3)
    parser.add_argument("--review-cap", type=float, default=0.15)
    parser.add_argument("--quick", action="store_true", help="small smoke config")
    parser.add_argument("--no-fit-baselines", action="store_true",
                        help="disable TRAIN-fitted MAD baselines (they are on by default, "
                             "matching the integrated evaluation and production paths)")
    parser.add_argument("--out", default="research/experiment_results.json")
    args = parser.parse_args()

    if args.quick:
        args.seeds, args.merchants, args.days, args.injections = "42", 3, 4, 2

    seeds = [int(s) for s in args.seeds.split(",")]
    print("=" * 78)
    print(f"VEYRA COMPARATIVE + ABLATION EXPERIMENT")
    print(f"seeds={seeds} merchants={args.merchants} days={args.days} injections/split/merchant={args.injections}")
    print("=" * 78)

    started = time.time()
    seed_results = [
        run_single_seed(s, args.merchants, args.days, args.injections, args.review_cap, not args.no_fit_baselines)
        for s in seeds
    ]

    payload = {
        "config": {
            "seeds": seeds,
            "merchants": args.merchants,
            "days": args.days,
            "injections_per_split_per_merchant": args.injections,
            "review_capacity_cap": args.review_cap,
            "baselines_fitted": not args.no_fit_baselines,
            "fn_cost_inr": ASSUMED_FALSE_NEGATIVE_COST_INR,
            "fp_cost_inr": ASSUMED_FALSE_POSITIVE_COST_INR,
            "runtime_seconds": round(time.time() - started, 1),
        },
        "seeds": [
            {
                "seed": r.seed,
                "n_test_windows": r.n_test_windows,
                "test_fraud_episodes": r.test_fraud_episodes,
                "test_hard_negative_episodes": r.test_hard_negative_episodes,
                "test_fraud_scenarios": r.test_fraud_scenarios,
                "test_hard_negative_scenarios": r.test_hard_negative_scenarios,
                "dev_twins_are_raw_values": r.dev_twins_are_raw_values,
                "detectors": {
                    name: {
                        "precision": d.precision, "recall": d.recall, "f1": d.f1,
                        "pr_auc": d.pr_auc, "roc_auc": d.roc_auc,
                        "tn": d.tn, "fp": d.fp, "fn": d.fn, "tp": d.tp,
                        "false_positive_rate": d.false_positive_rate,
                        "false_negative_rate": d.false_negative_rate,
                        "incident_recall": d.incident_recall,
                        "incident_tp": d.incident_tp, "incident_fn": d.incident_fn,
                        "incident_detection_rate": d.incident_detection_rate,
                        "incident_strict_recall": d.incident_strict_recall,
                        "mean_temporal_iou": d.mean_temporal_iou,
                        "fragmentation_index": d.fragmentation_index,
                        "merge_index": d.merge_index,
                        "incident_precision": d.incident_precision,
                        "hard_negative_fps": d.hard_negative_fps,
                        "fraud_scenario_recall": {k: list(v) for k, v in d.fraud_scenario_recall.items()},
                        "expected_loss": d.expected_loss,
                        "threshold": d.threshold,
                    }
                    for name, d in r.detectors.items()
                },
            }
            for r in seed_results
        ],
    }

    detector_names = list(seed_results[0].detectors.keys())
    payload["aggregate"] = {
        name: {
            metric: _agg([getattr(r.detectors[name], metric) for r in seed_results])
            for metric in ("precision", "recall", "f1", "pr_auc", "roc_auc", "incident_recall", "incident_detection_rate", "incident_strict_recall",
                              "mean_temporal_iou", "fragmentation_index", "merge_index",
                              "incident_precision", "expected_loss", "false_positive_rate")
        }
        for name in detector_names
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("\n" + "=" * 78)
    print(f"AGGREGATE ACROSS {len(seeds)} SEEDS (mean +/- std)")
    print("=" * 78)
    for name in detector_names:
        a = payload["aggregate"][name]
        print(
            f"{name:28s} PR-AUC {a['pr_auc']['mean']:.3f}+/-{a['pr_auc']['std']:.3f}  "
            f"P {a['precision']['mean']:.3f}  R {a['recall']['mean']:.3f}  F1 {a['f1']['mean']:.3f}  "
            # Both incident numbers printed here come from the SAME family
            # (app/evaluation/incident_metrics.py, material-overlap). The legacy
            # any-overlap `incident_recall` is still recorded in the JSON but is
            # deliberately not shown next to these: mixing the two families invites
            # reading a laxer metric as if it were the stricter one.
            f"det {a['incident_detection_rate']['mean']:.1%}  strict {a['incident_strict_recall']['mean']:.1%}  "
            f"loss Rs{a['expected_loss']['mean']:,.0f}"
        )
    print(f"\nresults written to {out_path}  (total runtime {payload['config']['runtime_seconds']}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
