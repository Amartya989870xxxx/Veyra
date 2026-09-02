"""Operating point selection by expected loss minimization (Phase 4.2 & ADR-005).

Thresholds are chosen on validation data to minimize financial expected loss under
a realistic human analyst review capacity cap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
import numpy as np


@dataclass(frozen=True, slots=True)
class OperatingThresholds:
    theta_alert: float = 0.35
    theta_review: float = 0.60
    theta_restrict: float = 0.85
    expected_loss: float = 0.0
    review_rate: float = 0.0


def choose_operating_thresholds(
    y_true: Sequence[int] | np.ndarray,
    y_prob: Sequence[float] | np.ndarray,
    losses_incurred: Sequence[float] | np.ndarray | None = None,
    review_capacity_cap: float = 0.15,
    fp_cost_review: float = 250.0,   # Cost in rupees for an analyst to review a false alert
) -> OperatingThresholds:
    """Select optimal thresholds for ALERT, REVIEW, and RESTRICT by expected loss minimization."""
    y_t = np.asarray(y_true, dtype=int)
    y_p = np.asarray(y_prob, dtype=float)
    n_samples = len(y_t)

    if n_samples == 0:
        return OperatingThresholds()

    losses = np.asarray(losses_incurred, dtype=float) if losses_incurred is not None else np.ones(n_samples) * 5000.0

    # Sweep potential thresholds
    best_review_thresh = 0.50
    min_total_cost = float("inf")
    best_review_rate = 0.0

    threshold_candidates = np.linspace(0.10, 0.90, 81)

    for thresh in threshold_candidates:
        flagged = (y_p >= thresh)
        review_rate = float(np.mean(flagged))

        # Check capacity constraint
        if review_rate > review_capacity_cap:
            continue

        # False Negative Loss: true frauds missed
        fn_mask = (y_t == 1) & (~flagged)
        fn_loss = float(np.sum(losses[fn_mask]))

        # False Positive Review Cost: legitimate traffic incorrectly queued
        fp_mask = (y_t == 0) & flagged
        fp_cost = float(np.sum(fp_mask)) * fp_cost_review

        total_cost = fn_loss + fp_cost

        if total_cost < min_total_cost:
            min_total_cost = total_cost
            best_review_thresh = thresh
            best_review_rate = review_rate

    # Derive alert and restrict thresholds relative to optimal review operating point
    theta_alert = max(0.15, float(best_review_thresh - 0.20))
    theta_review = float(best_review_thresh)
    theta_restrict = min(0.95, float(best_review_thresh + 0.20))

    return OperatingThresholds(
        theta_alert=theta_alert,
        theta_review=theta_review,
        theta_restrict=theta_restrict,
        expected_loss=float(min_total_cost),
        review_rate=best_review_rate,
    )
