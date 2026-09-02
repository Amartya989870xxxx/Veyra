"""Window-level statistical evaluation metrics (Phase 5.2).

Focuses on PR-AUC as the primary metric (accuracy is meaningless at extreme base rates §24),
along with ROC-AUC, Brier score calibration, precision, recall, and F1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
import numpy as np
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


@dataclass(frozen=True, slots=True)
class WindowMetrics:
    pr_auc: float
    roc_auc: float
    brier_score: float
    precision: float
    recall: float
    f1: float
    base_rate: float
    sample_count: int
    positive_count: int

    def to_dict(self) -> dict[str, float]:
        return {
            "pr_auc": self.pr_auc,
            "roc_auc": self.roc_auc,
            "brier_score": self.brier_score,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "base_rate": self.base_rate,
        }


def compute_window_metrics(
    y_true: Sequence[int] | np.ndarray,
    y_prob: Sequence[float] | np.ndarray,
    threshold: float = 0.50,
) -> WindowMetrics:
    """Compute comprehensive window-level classification and calibration metrics."""
    y_t = np.asarray(y_true, dtype=int)
    y_p = np.asarray(y_prob, dtype=float)

    n_samples = len(y_t)
    if n_samples == 0:
        return WindowMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0)

    n_pos = int(np.sum(y_t))
    base_rate = float(n_pos / max(1, n_samples))

    # Guard against single-class evaluation splits
    if n_pos == 0 or n_pos == n_samples:
        pr_auc = base_rate
        roc_auc = 0.50
    else:
        pr_auc = float(average_precision_score(y_t, y_p))
        roc_auc = float(roc_auc_score(y_t, y_p))

    brier = float(brier_score_loss(y_t, y_p))

    y_pred = (y_p >= threshold).astype(int)
    prec = float(precision_score(y_t, y_pred, zero_division=0))
    rec = float(recall_score(y_t, y_pred, zero_division=0))
    f1 = float(f1_score(y_t, y_pred, zero_division=0))

    return WindowMetrics(
        pr_auc=pr_auc,
        roc_auc=roc_auc,
        brier_score=brier,
        precision=prec,
        recall=rec,
        f1=f1,
        base_rate=base_rate,
        sample_count=n_samples,
        positive_count=n_pos,
    )
