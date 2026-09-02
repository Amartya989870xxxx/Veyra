"""Unified feature engine for Veyra v2 (Phase 3.1 & ADR-004).

Coordinates:
- Window statistical features (Families A through I)
- Relationship graph metrics (Family J)
- Robust baseline deviations (f_dev twins)
- Strict downstream anti-leakage barriers (ADR-004)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence

from app.features.aggregator import WindowAgg, compute_window_features_dict
from app.features.baselines import BaselineEngine
from app.graph.engine import GraphEngine
from app.registry import assert_no_downstream, load_features
from app.schemas.entities import PaymentAttempt
from app.schemas.enums import BaselineConfidence
from app.windows import WindowSize
from data.generators.timeline import AnnotatedTransaction


@dataclass
class WindowFeatureVector:
    merchant_id: str
    window_size: WindowSize
    window_end: datetime
    all_features: dict[str, float]
    model_features: dict[str, float]
    evidence: dict[str, float]
    baseline_confidence: BaselineConfidence


class FeatureEngine:
    """Computes complete feature vector for a merchant detection window."""

    def __init__(
        self,
        baseline_engine: BaselineEngine | None = None,
        graph_engine: GraphEngine | None = None,
    ) -> None:
        self.baseline_engine = baseline_engine or BaselineEngine()
        self.graph_engine = graph_engine or GraphEngine()
        self.registry = load_features()

    def extract_window_features(
        self,
        merchant_id: str,
        window_size: WindowSize,
        window_end: datetime,
        transactions: Sequence[AnnotatedTransaction | PaymentAttempt],
        preceding_rate: float = 0.0,
        cross_merchant_entity_map: dict[str, set[str]] | None = None,
    ) -> WindowFeatureVector:
        # 1. Aggregate statistical features for Families A-I
        agg = WindowAgg(
            merchant_id=merchant_id,
            window_size=window_size,
            window_end=window_end,
            transactions=list(transactions),
            preceding_window_txn_rate=preceding_rate,
        )
        raw_stats = compute_window_features_dict(agg)

        # 2. Extract Family J graph features
        graph_res = self.graph_engine.compute_window_graph_features(
            transactions=transactions,
            cross_merchant_entity_map=cross_merchant_entity_map,
        )
        graph_stats = graph_res.to_dict()

        # Combine all base features
        base_features: dict[str, float] = {**raw_stats, **graph_stats}

        # 3. Compute deviation twins for declared features
        how = window_end.weekday() * 24 + window_end.hour
        deviation_twins: dict[str, float] = {}
        confidences: list[BaselineConfidence] = []

        for fid, val in base_features.items():
            spec = self.registry.get(fid)
            if spec and spec.deviation_twin:
                dev_val, conf = self.baseline_engine.compute_deviation_twin(
                    merchant_id=merchant_id,
                    feature_id=fid,
                    value=val,
                    window_size=window_size,
                    hour_of_week=how,
                    # Arms the temporal guard: a baseline fitted on history that extends
                    # past this window is rejected rather than silently applied.
                    window_end=window_end,
                )
                deviation_twins[f"{fid}_dev"] = dev_val
                confidences.append(conf)

        all_features = {**base_features, **deviation_twins}

        # 4. Filter model inputs vs evidence-only vs downstream-only
        model_features: dict[str, float] = {}
        evidence: dict[str, float] = {}

        for k, v in all_features.items():
            base_k = k[:-4] if k.endswith("_dev") else k
            spec = self.registry.get(base_k)
            if not spec:
                continue

            if spec.evidence_only:
                evidence[k] = v
            elif spec.is_model_input:
                model_features[k] = v

        # 5. Enforce ADR-004 downstream barrier on model feature keys
        assert_no_downstream(list(model_features.keys()))

        # Determine overall baseline confidence (lowest among key features)
        overall_conf = BaselineConfidence.HIGH
        if any(c is BaselineConfidence.LOW for c in confidences):
            overall_conf = BaselineConfidence.LOW
        elif any(c is BaselineConfidence.MEDIUM for c in confidences):
            overall_conf = BaselineConfidence.MEDIUM

        return WindowFeatureVector(
            merchant_id=merchant_id,
            window_size=window_size,
            window_end=window_end,
            all_features=all_features,
            model_features=model_features,
            evidence=evidence,
            baseline_confidence=overall_conf,
        )
