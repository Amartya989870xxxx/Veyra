"""Base detector interface for comparative model evaluation (Phase 4.1)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Sequence

import numpy as np


class BaseDetector(ABC):
    """Abstract protocol for incident / spike detectors."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.feature_names: list[str] = []
        self.is_fitted: bool = False

    @abstractmethod
    def fit(self, X: np.ndarray | Sequence[dict[str, float]], y: Sequence[int] | np.ndarray) -> BaseDetector:
        """Fit model on training feature matrices and binary window labels."""
        pass

    @abstractmethod
    def predict_proba(self, X: np.ndarray | Sequence[dict[str, float]]) -> np.ndarray:
        """Return 1D array of predicted fraud spike probabilities in [0.0, 1.0]."""
        pass

    def predict(self, X: np.ndarray | Sequence[dict[str, float]], threshold: float = 0.5) -> np.ndarray:
        """Return binary predictions given an operating threshold."""
        probs = self.predict_proba(X)
        return (probs >= threshold).astype(int)

    def _prepare_matrix(
        self,
        X: np.ndarray | Sequence[dict[str, float]],
        feature_columns: list[str] | None = None,
    ) -> np.ndarray:
        """Convert input dictionaries or array to a 2D float NumPy matrix."""
        if isinstance(X, np.ndarray):
            return X

        cols = feature_columns or self.feature_names
        if not cols and X and isinstance(X[0], dict):
            cols = sorted(X[0].keys())
            self.feature_names = cols

        matrix = np.zeros((len(X), len(cols)), dtype=np.float32)
        for i, row in enumerate(X):
            if isinstance(row, dict):
                for j, col in enumerate(cols):
                    matrix[i, j] = float(row.get(col, 0.0))
            else:
                matrix[i, :] = row
        return matrix
