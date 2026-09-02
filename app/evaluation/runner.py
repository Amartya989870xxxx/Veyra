"""Comparative evaluation runner across temporal splits (Phase 5.1 & 5.2).

Executes Detectors A, B, and C strictly adhering to the past-only protocol:
- Baselines and models fit ONCE on TRAIN
- Operating thresholds tuned on VALIDATION
- Scored ONCE on frozen TEST
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence
import numpy as np

from app.decision.operating_point import OperatingThresholds, choose_operating_thresholds
from app.decision.policy import DecisionPolicy
from app.evaluation.incidents import (
    FlaggedWindowRecord,
    GroundTruthIncident,
    IncidentMatchingResults,
    assemble_predicted_incidents,
    match_incidents,
)
from app.evaluation.indexing import TransactionWindowIndex
from app.evaluation.metrics import WindowMetrics, compute_window_metrics
from app.features.baselines import fit_baselines_from_window_history
from app.features.engine import FeatureEngine
from app.models_ml.base import BaseDetector
from app.models_ml.contextual import ContextualMLDetector
from app.models_ml.fusion import VeyraFusionDetector
from app.models_ml.volume import VolumeOnlyDetector
from app.schemas.enums import SplitName, WindowLabel
from app.windows import WindowSize
from data.generators.pipeline import SyntheticDataset


@dataclass
class DetectorBenchmarkResult:
    detector_name: str
    window_metrics: WindowMetrics
    incident_metrics: IncidentMatchingResults
    thresholds: OperatingThresholds
    false_alerts_per_merchant_day: float
    hard_negative_fp_counts: dict[str, int]
    expected_financial_loss: float


@dataclass
class BenchmarkSuiteResults:
    results_by_detector: dict[str, DetectorBenchmarkResult]
    test_start: datetime
    test_end: datetime
    n_merchants: int
    n_test_windows: int
    n_ground_truth_attack_incidents: int = 0
    """How many distinct (merchant, attack-scenario) incidents actually landed in the
    TEST split. Recall/precision computed over a handful of incidents is not a
    statistically meaningful rate — the report must show this number next to any
    recall percentage, not just the percentage."""
    hard_negative_population: dict[str, int] = field(default_factory=dict)
    """Count of TEST windows whose dominant scenario is each hard-negative (LEGIT_SPIKE)
    scenario id actually observed in the split. A scenario absent from this dict was not
    exercised in TEST at all — reporting "0 false positives" for it would be reporting
    that nothing happened, not that detection succeeded, and the report must say so."""


class EvaluationRunner:
    """Orchestrates temporal split benchmark evaluation."""

    def __init__(self) -> None:
        pass

    def run_benchmark(
        self,
        dataset: SyntheticDataset,
        review_capacity_cap: float = 0.15,
    ) -> BenchmarkSuiteResults:
        # 1. Split window labels and transactions temporally
        train_labels = [w for w in dataset.window_labels if dataset.split_for_timestamp(w.window_end) == SplitName.TRAIN]
        val_labels = [w for w in dataset.window_labels if dataset.split_for_timestamp(w.window_end) == SplitName.VALIDATION]
        test_labels = [w for w in dataset.window_labels if dataset.split_for_timestamp(w.window_end) == SplitName.TEST]

        # 2. Extract features per window using past-only history.
        #
        # Two passes, and the order is the temporal contract:
        #   pass 1  raw features for TRAIN windows only (no baselines exist yet)
        #   fit     168h median/MAD baselines from those TRAIN features
        #   freeze  the fitted parameters are never recomputed after this point
        #   pass 2  re-extract TRAIN (in-sample transform) and extract VAL/TEST with the
        #           frozen engine, which refuses any baseline reaching past its window
        #
        # Before this, both the evaluation runner and the production ScoringService
        # constructed `FeatureEngine()` with an unfitted `BaselineEngine`, which made
        # every `_dev` twin equal `(value - 0.0) / max(1e-4, 1.0)` — a duplicate column
        # of its raw feature. The MAD baseline was inert everywhere it was claimed to
        # matter.
        feature_engine = FeatureEngine()

        # One index for the whole run. Previously this function re-scanned every
        # transaction in the dataset for every window — O(windows x transactions), which
        # put any dataset large enough to be statistically meaningful out of reach.
        # The index preserves the identical half-open [start, end) semantics; see
        # app/evaluation/indexing.py.
        txn_index = TransactionWindowIndex(dataset.transactions)

        # Build feature maps per window
        def extract_split_features(labels, engine: FeatureEngine | None = None):
            engine = engine or feature_engine
            X, y, records = [], [], []
            for w in labels:
                w_txns = txn_index.slice(
                    merchant_id=w.merchant_id,
                    start=w.window_end - w.window_size.delta,
                    end=w.window_end,
                )
                vec = engine.extract_window_features(
                    merchant_id=w.merchant_id,
                    window_size=w.window_size,
                    window_end=w.window_end,
                    transactions=w_txns,
                )
                X.append(vec.model_features)
                y.append(1 if w.label is WindowLabel.FRAUD_SPIKE else 0)
                records.append({
                    "merchant_id": w.merchant_id,
                    "window_size": w.window_size,
                    "window_end": w.window_end,
                    "label": w.label,
                    "dominant_scenario_id": w.dominant_scenario_id,
                    "gmv": float(vec.evidence.get("D.gmv", 0.0)),
                })
            return X, np.array(y, dtype=int), records

        # Pass 1: raw TRAIN features (unfitted engine) — the only input to baseline fitting.
        X_train_raw, _, _ = extract_split_features(train_labels)

        # Fit on TRAIN history only, then freeze.
        baseline_engine = fit_baselines_from_window_history(
            [
                {
                    "merchant_id": w.merchant_id,
                    "window_size": w.window_size.value,
                    "window_end": w.window_end,
                    # Deviation twins are derived quantities; fitting a baseline on a
                    # previous pass's `_dev` column would be fitting a baseline on a
                    # baseline. Only raw feature values feed the fit.
                    "features": {k: v for k, v in feats.items() if not k.endswith("_dev")},
                }
                for w, feats in zip(train_labels, X_train_raw)
            ]
        )

        # Pass 2. TRAIN is transformed in-sample (standard, and confined to model
        # fitting); VAL/TEST use the strict engine, which raises BaselineLeak if any
        # baseline reaches past the window it is applied to.
        train_engine = FeatureEngine(baseline_engine=baseline_engine.with_in_fit_period_use(True))
        scoring_engine = FeatureEngine(baseline_engine=baseline_engine)

        X_train, y_train, _ = extract_split_features(train_labels, train_engine)
        X_val, y_val, _ = extract_split_features(val_labels, scoring_engine)
        X_test, y_test, test_meta = extract_split_features(test_labels, scoring_engine)

        # 3. Fit 3 Detectors on TRAIN
        detector_a = VolumeOnlyDetector().fit(X_train, y_train)
        detector_b = ContextualMLDetector().fit(X_train, y_train)
        detector_c = VeyraFusionDetector().fit(X_train, y_train)

        detectors: list[BaseDetector] = [detector_a, detector_b, detector_c]
        benchmark_results: dict[str, DetectorBenchmarkResult] = {}

        # Build ground truth incidents in TEST split
        test_duration_days = max(1.0, (dataset.test_split_end - dataset.val_split_end).total_seconds() / 86400.0)
        n_merchants = len(dataset.merchants)

        # Group ground truth incidents from test metadata
        gt_incidents: list[GroundTruthIncident] = []
        # Find contiguous spans of positive test windows
        for m_profile in dataset.merchants:
            m_id = m_profile.merchant.merchant_id
            m_test_w = [t for t in test_meta if t["merchant_id"] == m_id and t["label"] is WindowLabel.FRAUD_SPIKE]
            if m_test_w:
                gt_incidents.append(
                    GroundTruthIncident(
                        scenario_id=m_test_w[0]["dominant_scenario_id"] or "attack",
                        merchant_id=m_id,
                        start_time=m_test_w[0]["window_end"] - m_test_w[0]["window_size"].delta,
                        end_time=m_test_w[-1]["window_end"],
                        is_attack=True,
                        total_gmv=sum(x["gmv"] for x in m_test_w),
                    )
                )

        # 4. Tune thresholds on VAL and evaluate on TEST
        for det in detectors:
            val_probs = det.predict_proba(X_val)
            thresholds = choose_operating_thresholds(
                y_true=y_val,
                y_prob=val_probs,
                review_capacity_cap=review_capacity_cap,
            )

            test_probs = det.predict_proba(X_test)
            w_metrics = compute_window_metrics(y_test, test_probs, threshold=thresholds.theta_review)

            # Assemble flagged windows
            flagged_windows: list[FlaggedWindowRecord] = []
            hard_neg_fps: dict[str, int] = {}

            for idx, (prob, meta) in enumerate(zip(test_probs, test_meta)):
                if prob >= thresholds.theta_review:
                    flagged_windows.append(
                        FlaggedWindowRecord(
                            merchant_id=meta["merchant_id"],
                            window_size=meta["window_size"],
                            window_end=meta["window_end"],
                            risk_score=float(prob),
                            gmv=meta["gmv"],
                        )
                    )
                    # Check if false positive on legitimate scenario
                    if meta["label"] is WindowLabel.LEGIT_SPIKE or meta["label"] is WindowLabel.NORMAL:
                        sc_id = meta["dominant_scenario_id"] or "normal"
                        hard_neg_fps[sc_id] = hard_neg_fps.get(sc_id, 0) + 1

            pred_incidents = assemble_predicted_incidents(flagged_windows)
            inc_metrics = match_incidents(pred_incidents, gt_incidents)

            # False alerts per merchant per day
            total_false_alerts = inc_metrics.false_positive_count
            fa_rate = total_false_alerts / (max(1, n_merchants) * test_duration_days)

            # Expected loss = Missed GMV + (False Alerts * Cost)
            expected_loss = inc_metrics.missed_fraud_gmv + (total_false_alerts * 250.0)

            benchmark_results[det.name] = DetectorBenchmarkResult(
                detector_name=det.name,
                window_metrics=w_metrics,
                incident_metrics=inc_metrics,
                thresholds=thresholds,
                false_alerts_per_merchant_day=fa_rate,
                hard_negative_fp_counts=hard_neg_fps,
                expected_financial_loss=expected_loss,
            )

        hard_negative_population: dict[str, int] = {}
        for meta in test_meta:
            if meta["label"] is WindowLabel.LEGIT_SPIKE:
                sc_id = meta["dominant_scenario_id"] or "unknown"
                hard_negative_population[sc_id] = hard_negative_population.get(sc_id, 0) + 1

        return BenchmarkSuiteResults(
            results_by_detector=benchmark_results,
            test_start=dataset.val_split_end,
            test_end=dataset.test_split_end,
            n_merchants=n_merchants,
            n_test_windows=len(test_labels),
            n_ground_truth_attack_incidents=len(gt_incidents),
            hard_negative_population=hard_negative_population,
        )
