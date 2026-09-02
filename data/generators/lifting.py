"""Window label lifting engine for Veyra v2 (Phase 2.3 & ADR-003).

Truth arrives per transaction; the detection and scoring unit is (merchant_id, window_size, window_end).

Lifting Rule:
    window is POSITIVE (FRAUD_SPIKE) iff:
        n_abusive >= K and abusive_share >= max(M, merchant_baseline_rate * 3)

    window is LEGIT_SPIKE iff:
        not FRAUD_SPIKE and (n_spike >= K and spike_share >= M)

    window is NORMAL otherwise.

Default parameters: K = 5, M = 0.20.
Three distinct classes (NORMAL, LEGIT_SPIKE, FRAUD_SPIKE) ensure false positive rates
on legitimate flash sales are measured honestly.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Sequence

from app.schemas.enums import WindowLabel
from app.windows import WindowSize, align_to_grid, contains, grid_points
from data.generators.timeline import AnnotatedTransaction


@dataclass(frozen=True, slots=True)
class ScoredWindowLabel:
    merchant_id: str
    window_size: WindowSize
    window_end: datetime
    label: WindowLabel
    total_txns: int
    n_abusive: int
    abusive_share: float
    n_spike: int
    spike_share: float
    dominant_scenario_id: str | None = None

    @property
    def is_positive(self) -> bool:
        return self.label is WindowLabel.FRAUD_SPIKE


def lift_labels_to_windows(
    transactions: Sequence[AnnotatedTransaction],
    merchant_id: str,
    window_sizes: Sequence[WindowSize] = (WindowSize.M1, WindowSize.M5, WindowSize.M15, WindowSize.H1),
    merchant_baseline_abusive_rate: float = 0.001,
    K: int = 5,
    M: float = 0.20,
) -> list[ScoredWindowLabel]:
    """Aggregate transaction-level annotations into grid-aligned window ground truth."""
    if not transactions:
        return []

    earliest_ts = min(t.attempt.timestamp for t in transactions)
    latest_ts = max(t.attempt.timestamp for t in transactions)

    # Grid scoring points from earliest to latest + 1 grid step
    start_grid = align_to_grid(earliest_ts)
    end_grid = align_to_grid(latest_ts) + timedelta(seconds=60)

    results: list[ScoredWindowLabel] = []

    # Sort once, then binary-search each window. This used to re-scan every transaction
    # for every (window_size, grid_point) pair — O(windows x transactions) — which is
    # what made generating a dataset large enough for a meaningful evaluation
    # impractical. `bisect_left` on both bounds reproduces the half-open [w_start, w_end)
    # rule exactly: a transaction at w_start is in, one at w_end belongs to the next
    # window (app/windows.py).
    sorted_txns = sorted(transactions, key=lambda t: t.attempt.timestamp)
    sorted_stamps = [t.attempt.timestamp for t in sorted_txns]

    for w_size in window_sizes:
        for w_end in grid_points(start_grid + w_size.delta, end_grid + timedelta(seconds=60)):
            w_start = w_end - w_size.delta

            # Find all transactions inside [w_start, w_end)
            lo = bisect_left(sorted_stamps, w_start)
            hi = bisect_left(sorted_stamps, w_end)
            in_window = sorted_txns[lo:hi]

            total_count = len(in_window)
            if total_count == 0:
                results.append(
                    ScoredWindowLabel(
                        merchant_id=merchant_id,
                        window_size=w_size,
                        window_end=w_end,
                        label=WindowLabel.NORMAL,
                        total_txns=0,
                        n_abusive=0,
                        abusive_share=0.0,
                        n_spike=0,
                        spike_share=0.0,
                        dominant_scenario_id="normal_day",
                    )
                )
                continue

            n_abusive = sum(1 for t in in_window if t.is_abusive)
            abusive_share = n_abusive / total_count

            n_spike = sum(1 for t in in_window if t.is_spike)
            spike_share = n_spike / total_count

            # Count scenario breakdown
            scenario_counts: dict[str, int] = defaultdict(int)
            for t in in_window:
                scenario_counts[t.scenario_id] += 1
            dominant_scenario = max(scenario_counts.items(), key=lambda x: x[1])[0]

            # Lift decision
            threshold_share = max(M, merchant_baseline_abusive_rate * 3.0)
            if n_abusive >= K and abusive_share >= threshold_share:
                label = WindowLabel.FRAUD_SPIKE
            elif n_spike >= K and spike_share >= M:
                label = WindowLabel.LEGIT_SPIKE
            else:
                label = WindowLabel.NORMAL

            results.append(
                ScoredWindowLabel(
                    merchant_id=merchant_id,
                    window_size=w_size,
                    window_end=w_end,
                    label=label,
                    total_txns=total_count,
                    n_abusive=n_abusive,
                    abusive_share=abusive_share,
                    n_spike=n_spike,
                    spike_share=spike_share,
                    dominant_scenario_id=dominant_scenario,
                )
            )

    return results


def compute_label_sensitivity(
    transactions: Sequence[AnnotatedTransaction],
    merchant_id: str,
    K_grid: Sequence[int] = (3, 5, 10),
    M_grid: Sequence[float] = (0.10, 0.20, 0.40),
) -> dict[tuple[int, float], dict[str, int]]:
    """Compute sensitivity of positive window count across (K, M) hyperparameter variations."""
    sensitivity: dict[tuple[int, float], dict[str, int]] = {}

    for k in K_grid:
        for m in M_grid:
            labels = lift_labels_to_windows(
                transactions=transactions,
                merchant_id=merchant_id,
                window_sizes=(WindowSize.M5,),
                K=k,
                M=m,
            )
            fraud_count = sum(1 for l in labels if l.label is WindowLabel.FRAUD_SPIKE)
            legit_count = sum(1 for l in labels if l.label is WindowLabel.LEGIT_SPIKE)
            normal_count = sum(1 for l in labels if l.label is WindowLabel.NORMAL)
            sensitivity[(k, m)] = {
                "FRAUD_SPIKE": fraud_count,
                "LEGIT_SPIKE": legit_count,
                "NORMAL": normal_count,
            }

    return sensitivity
