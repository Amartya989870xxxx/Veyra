"""Graph engine interface.

NetworkX is an in-process prototype choice, not an architectural commitment. Everything
outside this package talks to :class:`GraphRiskEngine`, so swapping in Neo4j or a
distributed graph store later is a new implementation, not a refactor of the risk engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from app.features.context import RiskContext, TxnView


@dataclass
class ClusterSummary:
    """A connected group of related transactions and the shape of what connects them."""

    cluster_key: str
    transaction_ids: list[str] = field(default_factory=list)
    size: int = 0
    customer_count: int = 0
    agent_count: int = 0
    device_count: int = 0
    network_count: int = 0
    session_count: int = 0
    instrument_count: int = 0
    merchant_count: int = 0
    sku_count: int = 0
    coupon_count: int = 0
    shared_entities: dict[str, list[str]] = field(default_factory=dict)
    span_seconds: float = 0.0
    interarrival_cv: float = 0.0
    failure_rate: float = 0.0
    retry_rate: float = 0.0
    sequence_similarity: float = 0.0
    amount_similarity: float = 0.0
    concentration_score: float = 0.0
    first_seen: datetime | None = None
    last_seen: datetime | None = None


@dataclass
class CampaignCandidate:
    """A cluster the engine considers campaign-shaped, with its supporting numbers."""

    cluster: ClusterSummary
    score: float
    reasons: list[dict] = field(default_factory=list)


@runtime_checkable
class GraphRiskEngine(Protocol):
    """Contract every graph implementation must satisfy."""

    version: str

    def build_context(self, ctx: RiskContext) -> ClusterSummary:
        """Summarise the ego-neighbourhood of the transaction being scored."""
        ...

    def extract_features(self, ctx: RiskContext) -> dict[str, float]:
        """Graph-derived features for the transaction being scored."""
        ...

    def find_campaigns(
        self, transactions: list[TxnView], session_actions: dict | None = None,
        min_size: int = 5,
    ) -> list[CampaignCandidate]:
        """Detect campaign-shaped clusters across a batch/window of transactions."""
        ...
