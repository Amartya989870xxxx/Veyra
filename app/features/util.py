"""Small numeric helpers shared by the feature modules."""

from __future__ import annotations

import math
import statistics


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if not denominator:
        return default
    return numerator / denominator


def clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def log1p_amount(amount: float) -> float:
    return math.log1p(max(0.0, amount))


def coefficient_of_variation(values: list[float]) -> float:
    """Std/mean of a series. The core "is this a metronome?" statistic.

    Human and legitimate-agent activity is bursty and jittered (CoV typically > 0.3).
    Scripted activity has near-identical gaps (CoV near 0). Returns 0.0 for series too
    short to judge, which callers must treat as "unknown", not as "regular".
    """
    if len(values) < 3:
        return 0.0
    mean = statistics.fmean(values)
    if mean <= 0:
        return 0.0
    return statistics.pstdev(values) / mean


def gaps(timestamps: list) -> list[float]:
    """Inter-arrival gaps in seconds from a sorted timestamp series."""
    if len(timestamps) < 2:
        return []
    ordered = sorted(timestamps)
    return [
        (ordered[i + 1] - ordered[i]).total_seconds() for i in range(len(ordered) - 1)
    ]


def repeat_gap_ratio(gap_series: list[float], precision: int = 1) -> float:
    """Share of gaps that round to the single most common value.

    A scheduler firing every 2.0s produces a ratio near 1.0; organic traffic stays low.
    """
    if len(gap_series) < 3:
        return 0.0
    rounded = [round(g, precision) for g in gap_series]
    most_common = max(set(rounded), key=rounded.count)
    return rounded.count(most_common) / len(rounded)


def entropy(counts: list[int]) -> float:
    """Shannon entropy in bits; 0 when everything is concentrated in one bucket."""
    total = sum(counts)
    if total <= 0:
        return 0.0
    result = 0.0
    for count in counts:
        if count > 0:
            p = count / total
            result -= p * math.log2(p)
    return result


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)
