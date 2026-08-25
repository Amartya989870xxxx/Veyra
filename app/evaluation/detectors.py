"""The three detectors compared in the central experiment.

* ``rules``  — Baseline 1, the static rule pack (PRD §22).
* ``txn_ml`` — Baseline 2, the same gradient-boosting estimator on **transaction features
  only**. This is the stand-in for a conventional, agent-unaware payment risk model.
* ``veyra``  — the full system: transaction + behaviour + graph/temporal components fused
  with deterministic intent and rule scores.

``txn_ml`` and ``veyra`` share an estimator, a seed and a training split. The only thing
that differs is the feature information available, which is what makes the comparison an
ablation rather than a model bake-off.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from app.evaluation.scoring import FeatureFrame
from app.features.engine import COMPONENT_FEATURES, TRANSACTION_ONLY_FEATURES
from app.intent.service import VIOLATION_WEIGHTS
from app.risk.fusion import COMPONENT_ORDER, fusion_matrix
from app.risk.models import ComponentModel, FusionModel, ModelBundle
from app.risk.rules import RuleEngine


class Detector(Protocol):
    name: str

    def score(self, frame: FeatureFrame) -> np.ndarray:
        ...


def rule_scores(frame: FeatureFrame, engine: RuleEngine | None = None) -> np.ndarray:
    engine = engine or RuleEngine()
    index = {name: i for i, name in enumerate(frame.feature_names)}
    out = np.zeros(len(frame), dtype=float)
    for row_index in range(len(frame)):
        row = frame.matrix[row_index]
        features = {name: float(row[i]) for name, i in index.items()}
        out[row_index] = engine.evaluate(features).score
    return out


def intent_deviations(frame: FeatureFrame) -> np.ndarray:
    """Deterministic intent deviation per row; ``NaN`` where no authorization context exists.

    NaN rather than 0.0 on purpose: the fusion layer converts it into an availability flag,
    so "no delegation to check" never reads as "checked and compliant".
    """
    index = {name: i for i, name in enumerate(frame.feature_names)}
    present_col = index["auth_present"]
    out = np.full(len(frame), np.nan, dtype=float)
    for row_index, txn_id in enumerate(frame.transaction_ids):
        if frame.matrix[row_index, present_col] < 1.0:
            continue
        violations = frame.violations_by_txn.get(txn_id, [])
        out[row_index] = (
            max(VIOLATION_WEIGHTS.get(v.code, 0.5) for v in violations) if violations else 0.0
        )
    return out


class RulesDetector:
    """Baseline 1. Deterministic; nothing is fitted, so ``fit`` is a no-op by design."""

    name = "rules"

    def __init__(self, engine: RuleEngine | None = None) -> None:
        self.engine = engine or RuleEngine()

    def fit(self, frame: FeatureFrame) -> RulesDetector:
        return self

    def score(self, frame: FeatureFrame) -> np.ndarray:
        return rule_scores(frame, self.engine)


class TransactionMLDetector:
    """Baseline 2: transaction features only, same estimator as Veyra's components."""

    name = "txn_ml"

    def __init__(self, model: ComponentModel | None = None, seed: int = 42) -> None:
        self.model = model or ComponentModel(
            name="baseline_txn_only", feature_names=list(TRANSACTION_ONLY_FEATURES), seed=seed
        )

    def fit(self, frame: FeatureFrame) -> TransactionMLDetector:
        self.model.fit(frame.select(self.model.feature_names), frame.labels)
        return self

    def score(self, frame: FeatureFrame) -> np.ndarray:
        return self.model.score(frame.select(self.model.feature_names))


class VeyraDetector:
    """The full system, scored exactly as the API scores it."""

    name = "veyra"

    def __init__(self, bundle: ModelBundle, rule_engine: RuleEngine | None = None) -> None:
        self.bundle = bundle
        self.rule_engine = rule_engine or RuleEngine()

    def component_scores(self, frame: FeatureFrame) -> dict[str, np.ndarray]:
        scores: dict[str, np.ndarray] = {}
        for name, model in self.bundle.components.items():
            scores[name] = model.score(frame.select(model.feature_names))
        scores["rule_violation_score"] = rule_scores(frame, self.rule_engine)
        scores["intent_deviation"] = intent_deviations(frame)
        return scores

    def score(self, frame: FeatureFrame) -> np.ndarray:
        components = self.component_scores(frame)
        rows = [
            {
                name: (
                    None
                    if np.isnan(components[name][i])
                    else float(components[name][i])
                )
                for name in COMPONENT_ORDER
            }
            for i in range(len(frame))
        ]
        return self.bundle.fusion.predict(fusion_matrix(rows))


def component_matrix(frame: FeatureFrame, components: dict[str, np.ndarray]) -> np.ndarray:
    rows = [
        {
            name: (None if np.isnan(components[name][i]) else float(components[name][i]))
            for name in COMPONENT_ORDER
        }
        for i in range(len(frame))
    ]
    return fusion_matrix(rows)


__all__ = [
    "COMPONENT_FEATURES",
    "Detector",
    "FusionModel",
    "RulesDetector",
    "TransactionMLDetector",
    "VeyraDetector",
    "component_matrix",
    "intent_deviations",
    "rule_scores",
]
