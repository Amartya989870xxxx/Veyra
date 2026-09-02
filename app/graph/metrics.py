"""Graph, statistical concentration and divergence mathematical utilities (Phase 3.3)."""

from __future__ import annotations

import math
from collections import Counter
from typing import Sequence


def compute_gini(values: Sequence[float | int]) -> float:
    """Compute the Gini coefficient of a distribution.

    Gini = 0.0 means perfect equality (all entities have the same degree).
    Gini -> 1.0 means extreme concentration (one hub holds all connections).
    """
    if not values:
        return 0.0
    val_list = [float(v) for v in values if float(v) >= 0]
    if not val_list or sum(val_list) == 0:
        return 0.0

    val_list.sort()
    n = len(val_list)
    index = range(1, n + 1)
    return (2.0 * sum(i * y for i, y in zip(index, val_list))) / (n * sum(val_list)) - (n + 1.0) / n


def compute_shannon_entropy(counts: Sequence[int] | dict[str, int]) -> float:
    """Compute Shannon entropy in bits over a frequency distribution."""
    if isinstance(counts, dict):
        freqs = list(counts.values())
    else:
        freqs = list(counts)

    total = sum(freqs)
    if total <= 0:
        return 0.0

    entropy = 0.0
    for c in freqs:
        if c > 0:
            p = c / total
            entropy -= p * math.log2(p)
    return float(entropy)


def compute_jensen_shannon_divergence(
    dist_p: dict[str, float], dist_q: dict[str, float]
) -> float:
    """Compute Jensen-Shannon divergence between two discrete categorical distributions.

    Bounded in [0.0, 1.0]. JSD = 0 means identical distributions.
    """
    keys = set(dist_p.keys()) | set(dist_q.keys())
    if not keys:
        return 0.0

    p_total = sum(dist_p.values())
    q_total = sum(dist_q.values())

    if p_total <= 0 or q_total <= 0:
        return 0.0

    norm_p = {k: dist_p.get(k, 0.0) / p_total for k in keys}
    norm_q = {k: dist_q.get(k, 0.0) / q_total for k in keys}

    # Midpoint distribution M = 0.5 * (P + Q)
    norm_m = {k: 0.5 * (norm_p[k] + norm_q[k]) for k in keys}

    def kl_div(a: dict[str, float], b: dict[str, float]) -> float:
        res = 0.0
        for k in keys:
            if a[k] > 0 and b[k] > 0:
                res += a[k] * math.log2(a[k] / b[k])
        return res

    jsd = 0.5 * kl_div(norm_p, norm_m) + 0.5 * kl_div(norm_q, norm_m)
    return float(max(0.0, min(1.0, math.sqrt(max(0.0, jsd)))))
