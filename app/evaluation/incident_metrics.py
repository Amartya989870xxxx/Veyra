"""Incident-level metric taxonomy.

Investigation result (see the module tests for the adversarial cases): the ~45% "strict
incident recall" versus ~100% "any-overlap recall" gap in the previous benchmark is
**not** an algorithmic bug. `match_incidents` performs greedy 1-to-1 matching, which is
a standard and deliberately harsh choice — it exists so a degenerate "flag everything"
detector cannot claim credit for every incident with one enormous prediction. Combined
with `assemble_predicted_incidents` merging flagged windows separated by <=3 minutes, it
measures whether each real incident got its *own distinct* prediction. That is
separation and localisation quality, not whether the attack was noticed.

Both numbers are real; they answer different questions, and reporting either alone is
misleading. So this module names them precisely instead of picking a winner:

| metric                  | question it answers                                          |
|-------------------------|--------------------------------------------------------------|
| `detection_recall`      | Did we notice this attack at all? (material overlap required) |
| `strict_match_recall`   | Did each attack get its own distinct predicted incident?      |
| `mean_temporal_iou`     | How well do predicted boundaries line up with real ones?      |
| `fragmentation_index`   | How many predictions did one real incident get split across?  |
| `merge_index`           | How many real incidents did one prediction swallow?           |
| `incident_precision`    | What share of predicted incidents correspond to a real one?   |

"Material overlap" matters: without it, a single window brushing the edge of a
four-hour attack counts as a detection, which is how "100% recall" becomes an
unfalsifiable number. An overlap must cover at least `overlap_fraction` of the ground
truth incident (floored at one 60s scoring grid step, and never more than the incident's
own duration) before it counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from app.evaluation.incidents import GroundTruthIncident, PredictedIncident
from app.windows import GRID_SECONDS

DEFAULT_OVERLAP_FRACTION = 0.10


@dataclass(frozen=True, slots=True)
class IncidentDetectionReport:
    n_ground_truth: int
    n_predicted: int

    detected_count: int
    detection_recall: float
    """Share of ground-truth incidents with at least one *materially* overlapping
    prediction. Answers "did we notice it", and says nothing about boundaries."""

    strict_matched_count: int
    strict_match_recall: float
    """Share of ground-truth incidents that received their own distinct predicted
    incident under greedy 1-to-1 matching. Answers "did we separate them", and is
    upper-bounded by `detection_recall` by construction."""

    incident_precision: float
    false_alarm_incidents: int

    mean_temporal_iou: float
    """Mean intersection-over-union of matched (prediction, ground truth) time spans.
    Localisation quality: 1.0 is an exact boundary match, low values mean the incident
    was noticed but its extent was badly estimated."""

    fragmentation_index: float
    """Mean number of distinct predictions overlapping one detected ground-truth
    incident. >1 means single attacks are being reported as several incidents."""

    merge_index: float
    """Mean number of ground-truth incidents materially overlapped by one prediction.
    >1 means distinct attacks are being collapsed into one incident — this is what
    drives strict recall below detection recall."""

    def to_dict(self) -> dict[str, float | int]:
        return {
            "n_ground_truth": self.n_ground_truth,
            "n_predicted": self.n_predicted,
            "detected_count": self.detected_count,
            "detection_recall": self.detection_recall,
            "strict_matched_count": self.strict_matched_count,
            "strict_match_recall": self.strict_match_recall,
            "incident_precision": self.incident_precision,
            "false_alarm_incidents": self.false_alarm_incidents,
            "mean_temporal_iou": self.mean_temporal_iou,
            "fragmentation_index": self.fragmentation_index,
            "merge_index": self.merge_index,
        }


def _overlap_seconds(
    pred_start: datetime, pred_end: datetime, gt_start: datetime, gt_end: datetime
) -> float:
    latest_start = max(pred_start, gt_start)
    earliest_end = min(pred_end, gt_end)
    return max(0.0, (earliest_end - latest_start).total_seconds())


def _required_overlap_seconds(gt: GroundTruthIncident, overlap_fraction: float) -> float:
    """How much overlap counts as noticing this incident.

    A fraction of the incident's own duration, floored at one scoring grid step so a
    single stray window cannot count, and capped at the incident duration so short
    incidents remain detectable at all.
    """
    duration = max(0.0, (gt.end_time - gt.start_time).total_seconds())
    if duration <= 0:
        return 0.0
    return min(duration, max(float(GRID_SECONDS), overlap_fraction * duration))


def evaluate_incident_detection(
    predicted_incidents: Sequence[PredictedIncident],
    ground_truth_incidents: Sequence[GroundTruthIncident],
    overlap_fraction: float = DEFAULT_OVERLAP_FRACTION,
) -> IncidentDetectionReport:
    """Compute the full incident metric taxonomy in one pass.

    Strict matching here reproduces `match_incidents`' greedy 1-to-1 semantics rather
    than replacing them, so the two numbers stay comparable; what changes is that the
    permissive number now requires material overlap and is reported alongside, never
    instead of, the strict one.
    """
    gts = [g for g in ground_truth_incidents if g.is_attack]
    preds = sorted(predicted_incidents, key=lambda p: p.first_flag_time)

    n_gt, n_pred = len(gts), len(preds)
    if n_gt == 0:
        return IncidentDetectionReport(
            n_ground_truth=0,
            n_predicted=n_pred,
            detected_count=0,
            detection_recall=0.0,
            strict_matched_count=0,
            strict_match_recall=0.0,
            incident_precision=0.0,
            false_alarm_incidents=n_pred,
            mean_temporal_iou=0.0,
            fragmentation_index=0.0,
            merge_index=0.0,
        )

    # Material-overlap adjacency between predictions and ground truth.
    overlaps: dict[int, list[int]] = {gi: [] for gi in range(n_gt)}
    pred_hits: dict[int, list[int]] = {pi: [] for pi in range(n_pred)}
    ious: list[float] = []

    for pi, pred in enumerate(preds):
        for gi, gt in enumerate(gts):
            if pred.merchant_id != gt.merchant_id:
                continue
            ov = _overlap_seconds(pred.first_flag_time, pred.last_flag_time, gt.start_time, gt.end_time)
            if ov >= _required_overlap_seconds(gt, overlap_fraction) and ov > 0:
                overlaps[gi].append(pi)
                pred_hits[pi].append(gi)

                union_start = min(pred.first_flag_time, gt.start_time)
                union_end = max(pred.last_flag_time, gt.end_time)
                union = max(1e-9, (union_end - union_start).total_seconds())
                ious.append(ov / union)

    detected = [gi for gi, hits in overlaps.items() if hits]
    detected_count = len(detected)

    # Strict greedy 1-to-1: each prediction may claim at most one ground truth, in time
    # order — the same rule `match_incidents` applies.
    claimed_gt: set[int] = set()
    strict_matched = 0
    for pi in range(n_pred):
        for gi in pred_hits[pi]:
            if gi in claimed_gt:
                continue
            claimed_gt.add(gi)
            strict_matched += 1
            break

    matched_preds = sum(1 for pi in range(n_pred) if pred_hits[pi])
    false_alarms = n_pred - matched_preds

    fragmentation = (
        sum(len(overlaps[gi]) for gi in detected) / detected_count if detected_count else 0.0
    )
    merge = (
        sum(len(pred_hits[pi]) for pi in range(n_pred) if pred_hits[pi]) / matched_preds
        if matched_preds
        else 0.0
    )

    return IncidentDetectionReport(
        n_ground_truth=n_gt,
        n_predicted=n_pred,
        detected_count=detected_count,
        detection_recall=detected_count / n_gt,
        strict_matched_count=strict_matched,
        strict_match_recall=strict_matched / n_gt,
        incident_precision=(matched_preds / n_pred) if n_pred else 0.0,
        false_alarm_incidents=false_alarms,
        mean_temporal_iou=(sum(ious) / len(ious)) if ious else 0.0,
        fragmentation_index=fragmentation,
        merge_index=merge,
    )
