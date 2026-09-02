"""Incident-level assembly, overlap matching, and detection latency metrics (Phase 5.2).

Assembles flagged discrete windows into continuous predicted incidents (gap tolerance <= 2),
performs greedy 1-to-1 temporal overlap matching against ground truth, and reports:
- Incident-level Recall, Precision, and F1
- Detection Latency: (first_flag_time - true_incident_start) at p50 and p90
- Missed-Incident GMV (money-weighted recall)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Sequence
import numpy as np

from app.core.ids import new_id
from app.windows import WindowSize


@dataclass
class FlaggedWindowRecord:
    merchant_id: str
    window_size: WindowSize
    window_end: datetime
    risk_score: float
    gmv: float = 0.0


@dataclass
class PredictedIncident:
    incident_id: str
    merchant_id: str
    first_flag_time: datetime
    last_flag_time: datetime
    window_count: int
    max_risk_score: float
    total_gmv: float = 0.0


@dataclass
class GroundTruthIncident:
    scenario_id: str
    merchant_id: str
    start_time: datetime
    end_time: datetime
    is_attack: bool
    total_gmv: float = 0.0


@dataclass(frozen=True, slots=True)
class IncidentMatchingResults:
    true_positive_count: int
    false_positive_count: int
    false_negative_count: int
    incident_recall: float
    incident_precision: float
    incident_f1: float
    latency_p50_minutes: float
    latency_p90_minutes: float
    caught_fraud_gmv: float
    missed_fraud_gmv: float
    gmv_recall: float

    def to_dict(self) -> dict[str, float | int]:
        return {
            "incident_recall": self.incident_recall,
            "incident_precision": self.incident_precision,
            "incident_f1": self.incident_f1,
            "latency_p50_minutes": self.latency_p50_minutes,
            "latency_p90_minutes": self.latency_p90_minutes,
            "gmv_recall": self.gmv_recall,
            "caught_fraud_gmv": self.caught_fraud_gmv,
            "missed_fraud_gmv": self.missed_fraud_gmv,
        }


def assemble_predicted_incidents(
    flagged_windows: Sequence[FlaggedWindowRecord],
    gap_tolerance_seconds: int = 180,  # 3 minutes tolerance
) -> list[PredictedIncident]:
    """Group flagged windows by merchant and merge consecutive runs into predicted incidents."""
    if not flagged_windows:
        return []

    # Sort windows chronologically per merchant
    by_merchant: dict[str, list[FlaggedWindowRecord]] = {}
    for w in flagged_windows:
        by_merchant.setdefault(w.merchant_id, []).append(w)

    predicted_incidents: list[PredictedIncident] = []

    for m_id, windows in by_merchant.items():
        windows.sort(key=lambda w: w.window_end)
        current_cluster: list[FlaggedWindowRecord] = [windows[0]]

        for w in windows[1:]:
            last_w = current_cluster[-1]
            gap = (w.window_end - last_w.window_end).total_seconds()
            if gap <= gap_tolerance_seconds:
                current_cluster.append(w)
            else:
                # Close current cluster into an incident
                first_ts = current_cluster[0].window_end - current_cluster[0].window_size.delta
                last_ts = current_cluster[-1].window_end
                max_score = max(x.risk_score for x in current_cluster)
                tot_gmv = sum(x.gmv for x in current_cluster)
                predicted_incidents.append(
                    PredictedIncident(
                        incident_id=new_id("pred_inc"),
                        merchant_id=m_id,
                        first_flag_time=first_ts,
                        last_flag_time=last_ts,
                        window_count=len(current_cluster),
                        max_risk_score=max_score,
                        total_gmv=tot_gmv,
                    )
                )
                current_cluster = [w]

        if current_cluster:
            first_ts = current_cluster[0].window_end - current_cluster[0].window_size.delta
            last_ts = current_cluster[-1].window_end
            max_score = max(x.risk_score for x in current_cluster)
            tot_gmv = sum(x.gmv for x in current_cluster)
            predicted_incidents.append(
                PredictedIncident(
                    incident_id=new_id("pred_inc"),
                    merchant_id=m_id,
                    first_flag_time=first_ts,
                    last_flag_time=last_ts,
                    window_count=len(current_cluster),
                    max_risk_score=max_score,
                    total_gmv=tot_gmv,
                )
            )

    return predicted_incidents


def match_incidents(
    predicted_incidents: Sequence[PredictedIncident],
    ground_truth_incidents: Sequence[GroundTruthIncident],
) -> IncidentMatchingResults:
    """Perform greedy 1-to-1 temporal overlap matching and compute detection latency."""
    true_attacks = [gt for gt in ground_truth_incidents if gt.is_attack]
    total_true_attacks = len(true_attacks)

    if total_true_attacks == 0 and len(predicted_incidents) == 0:
        return IncidentMatchingResults(0, 0, 0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)

    matched_gt: set[int] = set()
    matched_preds: set[int] = set()
    latencies_sec: list[float] = []

    sorted_preds = sorted(predicted_incidents, key=lambda p: p.first_flag_time)

    for p_idx, pred in enumerate(sorted_preds):
        for gt_idx, gt in enumerate(true_attacks):
            if gt_idx in matched_gt:
                continue
            if pred.merchant_id != gt.merchant_id:
                continue

            # Temporal overlap condition: [pred_start, pred_end] overlaps [gt_start, gt_end]
            overlap = not (pred.last_flag_time < gt.start_time or pred.first_flag_time > gt.end_time)
            if overlap:
                matched_gt.add(gt_idx)
                matched_preds.add(p_idx)

                # Detection Latency = first_flag_time - true_incident_start
                # (Lower bound at 0.0 if flag occurred before or at start)
                latency = max(0.0, (pred.first_flag_time - gt.start_time).total_seconds())
                latencies_sec.append(latency)
                break

    tp = len(matched_gt)
    fp = len(predicted_incidents) - len(matched_preds)
    fn = total_true_attacks - tp

    prec = tp / max(1, tp + fp) if (tp + fp) > 0 else 0.0
    rec = tp / max(1, total_true_attacks) if total_true_attacks > 0 else 0.0
    f1 = 2.0 * prec * rec / max(1e-4, prec + rec) if (prec + rec) > 0 else 0.0

    latencies_min = [s / 60.0 for s in latencies_sec] if latencies_sec else [0.0]
    p50_lat = float(np.percentile(latencies_min, 50))
    p90_lat = float(np.percentile(latencies_min, 90))

    # Monetary recall (GMV weighted)
    caught_gmv = sum(true_attacks[i].total_gmv for i in matched_gt)
    total_fraud_gmv = sum(gt.total_gmv for gt in true_attacks)
    missed_gmv = max(0.0, total_fraud_gmv - caught_gmv)
    gmv_rec = caught_gmv / max(1.0, total_fraud_gmv) if total_fraud_gmv > 0 else 1.0

    return IncidentMatchingResults(
        true_positive_count=tp,
        false_positive_count=fp,
        false_negative_count=fn,
        incident_recall=rec,
        incident_precision=prec,
        incident_f1=f1,
        latency_p50_minutes=p50_lat,
        latency_p90_minutes=p90_lat,
        caught_fraud_gmv=caught_gmv,
        missed_fraud_gmv=missed_gmv,
        gmv_recall=gmv_rec,
    )
