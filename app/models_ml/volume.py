"""Detector A: Volume-only baseline detector (Phase 4.1).

Relies strictly on volume deviations (z-scores / MAD units) against historical baselines.
Treats volume surges as verdicts rather than evidence (§5), which demonstrates the
inevitable high false positive rate on legitimate flash sales and influencer drops.
"""

from __future__ import annotations

from typing import Sequence
import numpy as np
from sklearn.linear_model import LogisticRegression

from app.models_ml.base import BaseDetector


class VolumeOnlyDetector(BaseDetector):
    """Detector A: Scores solely based on volume deviation from baseline."""

    def __init__(self, name: str = "volume_only") -> None:
        super().__init__(name=name)
        self.model = LogisticRegression(C=1.0, solver="lbfgs")
        self.volume_feature = "A.txn_rate_dev"

    def fit(
        self,
        X: np.ndarray | Sequence[dict[str, float]],
        y: Sequence[int] | np.ndarray,
    ) -> VolumeOnlyDetector:
        y_arr = np.asarray(y, dtype=int)
        if isinstance(X, list) and X and isinstance(X[0], dict):
            vol_values = np.array([float(row.get(self.volume_feature, row.get("B.txn_count_dev", 0.0))) for row in X]).reshape(-1, 1)
        else:
            X_mat = self._prepare_matrix(X)
            # Default to first column if raw array passed
            vol_values = X_mat[:, :1]

        # Fit simple 1D logistic curve on volume deviation
        self.model.fit(vol_values, y_arr)
        self.is_fitted = True
        return self

    def predict_proba(self, X: np.ndarray | Sequence[dict[str, float]]) -> np.ndarray:
        if not self.is_fitted:
            # Simple sigmoid heuristic if unfitted
            if isinstance(X, list) and X and isinstance(X[0], dict):
                vol_values = np.array([float(row.get(self.volume_feature, 0.0)) for row in X])
            else:
                X_mat = self._prepare_matrix(X)
                vol_values = X_mat[:, 0]
            # Sigmoid over z-score
            return 1.0 / (1.0 + np.exp(-0.5 * (vol_values - 3.0)))

        if isinstance(X, list) and X and isinstance(X[0], dict):
            vol_values = np.array([float(row.get(self.volume_feature, row.get("B.txn_count_dev", 0.0))) for row in X]).reshape(-1, 1)
        else:
            X_mat = self._prepare_matrix(X)
            vol_values = X_mat[:, :1]

        probs = self.model.predict_proba(vol_values)
        if probs.shape[1] == 2:
            return probs[:, 1]
        return probs[:, 0]
