"""In-process metrics registry.

Deliberately not Prometheus: the prototype needs the numbers named in PRD §27 to be
observable and testable, not a metrics stack. ``snapshot()`` backs ``GET /api/v1/metrics``.
"""

from __future__ import annotations

import threading
from collections import defaultdict


def _label_key(name: str, labels: dict[str, str] | None) -> str:
    if not labels:
        return name
    parts = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
    return f"{name}{{{parts}}}"


class MetricsRegistry:
    """Counters plus bounded histograms (last 5k observations) for percentile readout."""

    _MAX_OBSERVATIONS = 5000

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, float] = defaultdict(float)
        self._histograms: dict[str, list[float]] = defaultdict(list)

    def increment(self, name: str, value: float = 1.0, **labels: str) -> None:
        with self._lock:
            self._counters[_label_key(name, labels)] += value

    def observe(self, name: str, value: float, **labels: str) -> None:
        key = _label_key(name, labels)
        with self._lock:
            series = self._histograms[key]
            series.append(value)
            if len(series) > self._MAX_OBSERVATIONS:
                del series[: len(series) - self._MAX_OBSERVATIONS]

    def percentile(self, name: str, pct: float, **labels: str) -> float | None:
        key = _label_key(name, labels)
        with self._lock:
            series = sorted(self._histograms.get(key, []))
        if not series:
            return None
        idx = min(len(series) - 1, max(0, int(round((pct / 100.0) * (len(series) - 1)))))
        return series[idx]

    def snapshot(self) -> dict:
        with self._lock:
            counters = dict(self._counters)
            hist_keys = list(self._histograms.keys())
            hists = {k: list(self._histograms[k]) for k in hist_keys}
        summaries = {}
        for key, series in hists.items():
            if not series:
                continue
            ordered = sorted(series)
            summaries[key] = {
                "count": len(ordered),
                "mean": sum(ordered) / len(ordered),
                "p50": ordered[len(ordered) // 2],
                "p95": ordered[min(len(ordered) - 1, int(0.95 * (len(ordered) - 1)))],
                "max": ordered[-1],
            }
        return {"counters": counters, "histograms": summaries}

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._histograms.clear()


METRICS = MetricsRegistry()

RISK_REQUESTS_TOTAL = "risk_requests_total"
RISK_DECISIONS_TOTAL = "risk_decisions_total"
RISK_DEGRADED_TOTAL = "risk_degraded_total"
MODEL_ERRORS_TOTAL = "model_errors_total"
EVENTS_INGESTED_TOTAL = "events_ingested_total"
EVENTS_DUPLICATE_TOTAL = "events_duplicate_total"
CAMPAIGNS_DETECTED_TOTAL = "campaigns_detected_total"
CASES_CREATED_TOTAL = "cases_created_total"
RISK_LATENCY_MS = "risk_latency_ms"
LLM_LATENCY_MS = "llm_latency_ms"
FEATURE_LATENCY_MS = "feature_engine_latency_ms"
GRAPH_LATENCY_MS = "graph_engine_latency_ms"
