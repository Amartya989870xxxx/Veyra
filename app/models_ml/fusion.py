"""Detector C: Veyra Graph & Multi-Window Fusion Detector (Phase 4.1).

The full thesis model combining:
- Statistical, ratio, and outcome features (Families A–I)
- Deviation twins from robust MAD baselines
- Relationship graph metrics (Family J: bipartite Gini, cluster volume shares, cross-merchant fan-out)
- Multi-window fusion
"""

from __future__ import annotations

from typing import Sequence
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

from app.models_ml.base import BaseDetector
from app.registry import assert_no_downstream, load_features


class VeyraFusionDetector(BaseDetector):
    """Detector C: Full Veyra Graph & Multi-Window Fusion Model."""

    def __init__(self, name: str = "veyra_fusion", max_iter: int = 150, random_state: int = 42) -> None:
        super().__init__(name=name)
        self.max_iter = max_iter
        self.random_state = random_state
        self.model = HistGradientBoostingClassifier(
            max_iter=max_iter,
            random_state=random_state,
            min_samples_leaf=2,
            learning_rate=0.08,
        )

    def _filter_model_features(self, feature_names: list[str]) -> list[str]:
        registry = load_features()
        filtered = []
        for f in feature_names:
            base_f = f[:-4] if f.endswith("_dev") else f
            spec = registry.get(base_f)
            if spec and spec.is_model_input:
                filtered.append(f)
            elif not spec and not f.startswith("I.dispute") and not f.startswith("I.chargeback") and not f.startswith("I.rto"):
                # Permit engineered multi-window combinations
                filtered.append(f)

        assert_no_downstream(filtered)
        return filtered

    def fit(
        self,
        X: Sequence[dict[str, float]],
        y: Sequence[int] | np.ndarray,
    ) -> VeyraFusionDetector:
        y_arr = np.asarray(y, dtype=int)
        if not X:
            return self

        all_keys = sorted(X[0].keys())
        self.feature_names = self._filter_model_features(all_keys)

        min_leaf = max(1, min(10, len(y_arr) // 4))
        self.model = HistGradientBoostingClassifier(
            max_iter=self.max_iter,
            random_state=self.random_state,
            min_samples_leaf=min_leaf,
            learning_rate=0.08,
        )

        X_mat = self._prepare_matrix(X, feature_columns=self.feature_names)
        self.model.fit(X_mat, y_arr)
        self.is_fitted = True
        return self

    def predict_proba(self, X: Sequence[dict[str, float]] | np.ndarray) -> np.ndarray:
        if not self.is_fitted:
            return np.zeros(len(X), dtype=np.float32)

        X_mat = self._prepare_matrix(X, feature_columns=self.feature_names)
        probs = self.model.predict_proba(X_mat)
        if probs.shape[1] == 2:
            return probs[:, 1]
        return probs[:, 0]
