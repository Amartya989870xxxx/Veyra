"""ML risk components and the artifact registry.

Design decisions worth stating plainly:

* **Three components on disjoint feature slices.** ``transaction_risk`` sees only
  transaction features, ``behavior_risk`` only agent behaviour, ``campaign_risk`` only
  graph + temporal. Persisting three scores from one model over all features would give
  three views of the same number and make the audit trail misleading.
* **One model family throughout** (``HistGradientBoostingClassifier``). The transaction-only
  baseline uses the identical estimator on the transaction slice, so any difference in the
  final comparison comes from the *features*, not from a stronger learner.
* **No calibration stage.** Operating points are chosen by expected loss on validation,
  which is what actually drives the decision; calibration error is reported as a metric
  rather than optimised behind the scenes.
"""

from __future__ import annotations

import json
import pickle
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import GroupKFold

from app.core.logging import get_logger

log = get_logger(__name__)

MODEL_FAMILY = "hist_gradient_boosting"
MODEL_VERSION = "hgb-v1"


def _new_estimator(seed: int = 42) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        max_iter=200,
        learning_rate=0.08,
        max_depth=6,
        min_samples_leaf=25,
        l2_regularization=1.0,
        early_stopping=False,
        random_state=seed,
        class_weight="balanced",
    )


@dataclass
class ComponentModel:
    """A single scored component: an estimator bound to a named feature slice."""

    name: str
    feature_names: list[str]
    estimator: object | None = None
    version: str = MODEL_VERSION
    trained_on: int = 0
    positive_rate: float = 0.0
    seed: int = 42

    @property
    def is_fitted(self) -> bool:
        return self.estimator is not None

    def fit(self, features: np.ndarray, labels: np.ndarray) -> ComponentModel:
        if len(set(labels.tolist())) < 2:
            raise ValueError(f"component '{self.name}' needs both classes to train")
        estimator = _new_estimator(self.seed)
        estimator.fit(features, labels)
        self.estimator = estimator
        self.trained_on = int(len(labels))
        self.positive_rate = float(labels.mean())
        return self

    def score(self, features: np.ndarray) -> np.ndarray:
        """Probability of the abusive class. Raises if unfitted — never returns a guess."""
        if not self.is_fitted:
            raise RuntimeError(f"component '{self.name}' is not fitted")
        return self.estimator.predict_proba(features)[:, 1]

    def score_one(self, row: list[float]) -> float:
        return float(self.score(np.asarray([row], dtype=float))[0])


@dataclass
class FusionModel:
    """Logistic regression over the component scores.

    Weights are *learned* from out-of-fold component predictions on the training split,
    not asserted. ``weights()`` exposes them so the report can state exactly how much each
    component contributed — the alternative, hand-picked constants presented as a model, is
    what the PRD explicitly rules out.
    """

    component_names: list[str] = field(default_factory=list)
    coefficients: list[float] = field(default_factory=list)
    intercept: float = 0.0
    version: str = "fusion-lr-v1"
    trained_on: int = 0

    @property
    def is_fitted(self) -> bool:
        return bool(self.coefficients)

    def fit(self, component_scores: np.ndarray, labels: np.ndarray,
            component_names: list[str]) -> FusionModel:
        from sklearn.linear_model import LogisticRegression

        model = LogisticRegression(max_iter=2000, C=1.0, class_weight="balanced")
        model.fit(component_scores, labels)
        self.component_names = list(component_names)
        self.coefficients = [float(c) for c in model.coef_[0]]
        self.intercept = float(model.intercept_[0])
        self.trained_on = int(len(labels))
        return self

    def predict(self, component_scores: np.ndarray) -> np.ndarray:
        if not self.is_fitted:
            raise RuntimeError("fusion model is not fitted")
        logits = component_scores @ np.asarray(self.coefficients) + self.intercept
        return 1.0 / (1.0 + np.exp(-logits))

    def predict_one(self, scores: dict[str, float]) -> float:
        row = np.asarray([[scores[name] for name in self.component_names]], dtype=float)
        return float(self.predict(row)[0])

    def contributions(self, scores: dict[str, float]) -> dict[str, float]:
        """Per-component contribution to the logit, for evidence attribution."""
        return {
            name: float(scores.get(name, 0.0) * coefficient)
            for name, coefficient in zip(self.component_names, self.coefficients, strict=True)
        }

    def weights(self) -> dict[str, float]:
        return dict(zip(self.component_names, self.coefficients, strict=True))


def out_of_fold_scores(
    features: np.ndarray,
    labels: np.ndarray,
    groups: list[str],
    seed: int = 42,
    n_splits: int = 5,
) -> np.ndarray:
    """Out-of-fold predictions using **grouped** folds.

    Grouping matters as much here as in the train/test split: a device farm split across
    folds would let the model recognise its own cluster and hand the fusion layer
    over-confident inputs.
    """
    predictions = np.zeros(len(labels), dtype=float)
    unique_groups = len(set(groups))
    splits = min(n_splits, max(2, unique_groups))
    splitter = GroupKFold(n_splits=splits)
    for train_idx, test_idx in splitter.split(features, labels, groups=groups):
        if len(set(labels[train_idx].tolist())) < 2:
            predictions[test_idx] = float(labels[train_idx].mean())
            continue
        estimator = _new_estimator(seed)
        estimator.fit(features[train_idx], labels[train_idx])
        predictions[test_idx] = estimator.predict_proba(features[test_idx])[:, 1]
    return predictions


@dataclass
class ModelBundle:
    """Everything needed to reproduce a Veyra score: components, fusion, baselines, versions."""

    components: dict[str, ComponentModel] = field(default_factory=dict)
    fusion: FusionModel | None = None
    baseline_txn_only: ComponentModel | None = None
    baselines_path: str | None = None
    dataset_id: str | None = None
    seed: int = 42
    thresholds: dict[str, float] = field(default_factory=dict)

    def versions(self) -> dict[str, str]:
        versions = {
            f"component.{name}": model.version for name, model in self.components.items()
        }
        if self.fusion:
            versions["fusion"] = self.fusion.version
        if self.baseline_txn_only:
            versions["baseline_txn_only"] = self.baseline_txn_only.version
        versions["model_family"] = MODEL_FAMILY
        return versions

    def save(self, directory: str | Path) -> Path:
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        with (root / "bundle.pkl").open("wb") as fh:
            pickle.dump(self, fh)
        metadata = {
            "versions": self.versions(),
            "dataset_id": self.dataset_id,
            "seed": self.seed,
            "thresholds": self.thresholds,
            "components": {
                name: {
                    "features": len(model.feature_names),
                    "trained_on": model.trained_on,
                    "positive_rate": model.positive_rate,
                }
                for name, model in self.components.items()
            },
            "fusion_weights": self.fusion.weights() if self.fusion else {},
            "fusion_intercept": self.fusion.intercept if self.fusion else None,
        }
        (root / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return root

    @classmethod
    def load(cls, directory: str | Path) -> ModelBundle:
        path = Path(directory) / "bundle.pkl"
        if not path.exists():
            raise FileNotFoundError(f"no model bundle at {path}")
        with path.open("rb") as fh:
            return pickle.load(fh)

    @classmethod
    def try_load(cls, directory: str | Path) -> ModelBundle | None:
        """Load if present. A missing bundle is a normal state, not an error.

        The API must start and serve deterministic decisions before any model is trained.
        """
        try:
            return cls.load(directory)
        except Exception as exc:
            log.info("model_bundle_unavailable", extra={"path": str(directory), "reason": str(exc)})
            return None
