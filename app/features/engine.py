"""Feature engine: assembles every feature group into one versioned, hashable snapshot.

The snapshot hash is what makes a decision reproducible. Given the hash, the feature
version and the stored snapshot, a past decision can be recomputed exactly.

Feature *groups* are first-class because the central experiment is an ablation:
``TRANSACTION_ONLY`` is what a conventional payment-risk model sees; ``FULL`` adds the
agent, authorization, graph and temporal signals. Both run through identical code.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from app.core.ids import stable_hash
from app.core.versions import FEATURE_VERSION
from app.features.authorization import (
    AUTHORIZATION_FEATURE_NAMES,
    AuthorizationViolation,
    authorization_features,
    check_authorization,
)
from app.features.baselines import DEFAULT_BASELINES, Baselines
from app.features.behavior import BEHAVIOR_FEATURE_NAMES, behavior_features
from app.features.context import RiskContext
from app.features.temporal import TEMPORAL_FEATURE_NAMES, temporal_features
from app.features.transaction import TRANSACTION_FEATURE_NAMES, transaction_features
from app.graph.base import ClusterSummary
from app.graph.networkx_engine import GRAPH_FEATURE_NAMES, NetworkXGraphEngine

FEATURE_GROUPS: dict[str, list[str]] = {
    "transaction": TRANSACTION_FEATURE_NAMES,
    "behavior": BEHAVIOR_FEATURE_NAMES,
    "authorization": AUTHORIZATION_FEATURE_NAMES,
    "graph": GRAPH_FEATURE_NAMES,
    "temporal": TEMPORAL_FEATURE_NAMES,
}

ALL_FEATURE_NAMES: list[str] = [
    name for group in ("transaction", "behavior", "authorization", "graph", "temporal")
    for name in FEATURE_GROUPS[group]
]

# The two arms of the central experiment.
TRANSACTION_ONLY_FEATURES = list(TRANSACTION_FEATURE_NAMES)
FULL_FEATURES = list(ALL_FEATURE_NAMES)

# Component feature sets. Each risk component is trained on its own slice so the persisted
# component scores are genuinely independent readings rather than five views of one model.
COMPONENT_FEATURES = {
    "transaction_risk": TRANSACTION_FEATURE_NAMES,
    "behavior_risk": BEHAVIOR_FEATURE_NAMES,
    "campaign_risk": GRAPH_FEATURE_NAMES + TEMPORAL_FEATURE_NAMES,
}


@dataclass
class FeatureSnapshot:
    values: dict[str, float]
    violations: list[AuthorizationViolation] = field(default_factory=list)
    cluster: ClusterSummary | None = None
    feature_version: str = FEATURE_VERSION
    snapshot_hash: str = ""
    latency_ms: dict[str, float] = field(default_factory=dict)
    degraded: list[str] = field(default_factory=list)

    def vector(self, names: list[str]) -> list[float]:
        return [float(self.values.get(name, 0.0)) for name in names]

    def group(self, name: str) -> dict[str, float]:
        return {k: self.values[k] for k in FEATURE_GROUPS[name] if k in self.values}


class FeatureEngine:
    """Deterministic feature extraction. Same code path online and offline."""

    version = FEATURE_VERSION

    def __init__(
        self,
        graph_engine: NetworkXGraphEngine | None = None,
        baselines: Baselines | None = None,
    ) -> None:
        self.graph_engine = graph_engine or NetworkXGraphEngine()
        self.baselines = baselines or DEFAULT_BASELINES

    def extract(self, ctx: RiskContext) -> FeatureSnapshot:
        latency: dict[str, float] = {}
        values: dict[str, float] = {}

        started = time.perf_counter()
        values.update(transaction_features(ctx, self.baselines))
        latency["transaction"] = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        values.update(behavior_features(ctx))
        latency["behavior"] = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        violations = check_authorization(ctx)
        values.update(authorization_features(ctx, violations))
        latency["authorization"] = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        cluster: ClusterSummary | None = None
        try:
            values.update(self.graph_engine.extract_features(ctx))
            cluster = self.graph_engine.build_context(ctx)
        except Exception:
            # The graph layer is the most complex component and the least essential to a
            # safe decision. If it fails we mark it unavailable and leave its features
            # absent rather than filling in zeros that read as "no cluster here".
            ctx.mark_degraded("graph_engine")
            for name in GRAPH_FEATURE_NAMES:
                values.setdefault(name, 0.0)
        latency["graph"] = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        values.update(temporal_features(ctx))
        latency["temporal"] = (time.perf_counter() - started) * 1000

        if ctx.neighbourhood_truncated:
            ctx.mark_degraded("graph_window_truncated")

        snapshot_hash = stable_hash(
            json.dumps(
                {"v": FEATURE_VERSION, "f": {k: round(v, 6) for k, v in sorted(values.items())}},
                sort_keys=True,
            )
        )
        return FeatureSnapshot(
            values=values,
            violations=violations,
            cluster=cluster,
            snapshot_hash=snapshot_hash,
            latency_ms=latency,
            degraded=list(ctx.degraded),
        )
