"""Classification metrics, the expected-loss model, and threshold sweeps.

Two conventions, stated up front because they change how every number below reads:

* **"Detected" means BLOCK or REVIEW.** ``ClassificationMetrics`` treats either as a
  positive prediction, because both stop the loss. The very different *costs* of the two
  are captured in :class:`LossMetrics`, not smuggled into precision.
* **A review catches the abuse but costs analyst time.** Reviewed abuse counts as prevented
  loss plus a review cost; reviewed legitimate traffic costs only the review. This is an
  assumption about analyst effectiveness, and an optimistic one — it is stated in the report
  rather than buried here.

All cost constants are synthetic, configurable, and explicitly not sourced industry
benchmarks (PRD §20.1).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.schemas.enums import Decision
from app.schemas.evaluation import (
    ClassificationMetrics,
    CostModel,
    LossMetrics,
    ThresholdPoint,
)


def classification_metrics(
    y_true: list[int] | np.ndarray, y_pred: list[int] | np.ndarray,
    scores: list[float] | np.ndarray | None = None,
) -> ClassificationMetrics:
    y_true = np.asarray(y_true, dtype=int)
    y_pred = np.asarray(y_pred, dtype=int)

    tp = int(((y_true == 1) & (y_pred == 1)).sum())
    fp = int(((y_true == 0) & (y_pred == 1)).sum())
    tn = int(((y_true == 0) & (y_pred == 0)).sum())
    fn = int(((y_true == 1) & (y_pred == 0)).sum())

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    pr_auc = roc_auc = None
    if scores is not None and len(set(y_true.tolist())) == 2:
        from sklearn.metrics import average_precision_score, roc_auc_score

        pr_auc = float(average_precision_score(y_true, np.asarray(scores)))
        roc_auc = float(roc_auc_score(y_true, np.asarray(scores)))

    return ClassificationMetrics(
        true_positives=tp,
        false_positives=fp,
        true_negatives=tn,
        false_negatives=fn,
        precision=round(precision, 6),
        recall=round(recall, 6),
        f1=round(f1, 6),
        false_positive_rate=round(fp / (fp + tn), 6) if (fp + tn) else 0.0,
        false_negative_rate=round(fn / (fn + tp), 6) if (fn + tp) else 0.0,
        accuracy=round((tp + tn) / len(y_true), 6) if len(y_true) else 0.0,
        support_positive=int((y_true == 1).sum()),
        support_negative=int((y_true == 0).sum()),
        pr_auc=round(pr_auc, 6) if pr_auc is not None else None,
        roc_auc=round(roc_auc, 6) if roc_auc is not None else None,
    )


def expected_loss(
    decisions: list[Decision] | list[str],
    labels: list[int] | np.ndarray,
    amounts: list[float] | np.ndarray,
    cost_model: CostModel,
) -> LossMetrics:
    """Merchant expected loss under a given set of decisions.

    ``Expected Loss = FN_count x FN_cost + FP_count x FP_cost + Review_count x Review_cost``
    with FN and FP costs scaled by transaction value, because blocking a Rs 200 purchase
    and blocking a Rs 90,000 one are not the same mistake.
    """
    labels = np.asarray(labels, dtype=int)
    amounts = np.asarray(amounts, dtype=float)
    decisions = [str(d) for d in decisions]

    fn_loss = fp_loss = review_loss = 0.0
    prevented = 0.0
    blocked_legit_gmv = 0.0
    allowed_abusive_gmv = 0.0
    reviews = blocks = allows = 0

    for decision, label, amount in zip(decisions, labels, amounts, strict=True):
        if decision == Decision.REVIEW:
            reviews += 1
            review_loss += cost_model.review_cost_flat
        elif decision == Decision.BLOCK:
            blocks += 1
        else:
            allows += 1

        abuse_cost = amount * cost_model.fn_cost_multiplier + cost_model.chargeback_fee_flat

        if label == 1:
            if decision == Decision.ALLOW:
                fn_loss += abuse_cost
                allowed_abusive_gmv += amount
            else:
                # Blocked or routed to review: the loss did not land.
                prevented += abuse_cost
        elif decision == Decision.BLOCK:
            fp_loss += amount * cost_model.fp_cost_multiplier
            blocked_legit_gmv += amount

    total = len(decisions) or 1
    return LossMetrics(
        expected_loss=round(fn_loss + fp_loss + review_loss, 2),
        fn_loss=round(fn_loss, 2),
        fp_loss=round(fp_loss, 2),
        review_loss=round(review_loss, 2),
        prevented_loss=round(prevented, 2),
        blocked_legitimate_gmv=round(blocked_legit_gmv, 2),
        allowed_abusive_gmv=round(allowed_abusive_gmv, 2),
        review_count=reviews,
        review_rate=round(reviews / total, 6),
        block_rate=round(blocks / total, 6),
        allow_rate=round(allows / total, 6),
    )


def decisions_from_scores(
    scores: list[float] | np.ndarray, review_threshold: float, block_threshold: float
) -> list[str]:
    return [
        Decision.BLOCK if s >= block_threshold
        else Decision.REVIEW if s >= review_threshold
        else Decision.ALLOW
        for s in scores
    ]


@dataclass
class OperatingPoint:
    review_threshold: float
    block_threshold: float
    expected_loss: float
    point: ThresholdPoint


def threshold_sweep(
    scores: list[float] | np.ndarray,
    labels: list[int] | np.ndarray,
    amounts: list[float] | np.ndarray,
    cost_model: CostModel,
    grid: np.ndarray | None = None,
) -> list[ThresholdPoint]:
    """Sweep the (review, block) threshold pair and report the full cost curve."""
    grid = np.arange(0.05, 1.0, 0.05) if grid is None else grid
    labels_array = np.asarray(labels, dtype=int)
    points: list[ThresholdPoint] = []

    for review_threshold in grid:
        for block_threshold in grid:
            if block_threshold < review_threshold:
                continue
            decisions = decisions_from_scores(scores, review_threshold, block_threshold)
            flagged = np.asarray([1 if d != Decision.ALLOW else 0 for d in decisions])
            metrics = classification_metrics(labels_array, flagged)
            loss = expected_loss(decisions, labels_array, amounts, cost_model)
            points.append(
                ThresholdPoint(
                    review_threshold=round(float(review_threshold), 4),
                    block_threshold=round(float(block_threshold), 4),
                    precision=metrics.precision,
                    recall=metrics.recall,
                    f1=metrics.f1,
                    false_positive_rate=metrics.false_positive_rate,
                    false_negative_rate=metrics.false_negative_rate,
                    expected_loss=loss.expected_loss,
                    blocked_legitimate_gmv=loss.blocked_legitimate_gmv,
                    prevented_loss=loss.prevented_loss,
                    review_rate=loss.review_rate,
                )
            )
    return points


def choose_operating_point(
    points: list[ThresholdPoint], max_review_rate: float = 0.25
) -> OperatingPoint:
    """Pick thresholds by minimum expected loss, subject to a review-capacity constraint.

    Without the constraint the optimiser reviews everything: reviews are cheap per unit and
    prevent all loss in this cost model, which is not an operating point any real risk team
    could staff. The cap makes the recommendation implementable.
    """
    feasible = [p for p in points if p.review_rate <= max_review_rate] or points
    best = min(feasible, key=lambda p: (p.expected_loss, p.review_rate, -p.f1))
    return OperatingPoint(
        review_threshold=best.review_threshold,
        block_threshold=best.block_threshold,
        expected_loss=best.expected_loss,
        point=best,
    )


def cost_model_from_settings(settings) -> CostModel:
    return CostModel(
        fn_cost_multiplier=settings.fn_cost_multiplier,
        fp_cost_multiplier=settings.fp_cost_multiplier,
        review_cost_flat=settings.review_cost_flat,
        chargeback_fee_flat=settings.chargeback_fee_flat,
    )


def calibration_error(scores: list[float] | np.ndarray, labels: list[int] | np.ndarray,
                      bins: int = 10) -> float:
    """Expected calibration error: mean |confidence - accuracy| weighted by bin size."""
    scores = np.asarray(scores, dtype=float)
    labels = np.asarray(labels, dtype=int)
    if not len(scores):
        return 0.0
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = 0.0
    for i in range(bins):
        mask = (scores >= edges[i]) & (scores < edges[i + 1] if i < bins - 1 else scores <= 1.0)
        if not mask.any():
            continue
        total += mask.mean() * abs(scores[mask].mean() - labels[mask].mean())
    return round(float(total), 6)
