"""NetworkX implementation of the graph risk engine.

The graph is an entity–transaction bipartite structure: transaction nodes on one side,
typed entity nodes (customer, device, network, agent, session, SKU, coupon, instrument)
on the other. Two transactions are related when they touch a shared entity.

Nothing sensitive ever enters the graph. Node IDs are synthetic tokens, and the
instrument node is a non-reversible fingerprint, never a card reference.

Campaign detection starts at the simple end, as the PRD asks: connected components over
shared-entity edges, then a bounded concentration score per component. No graph neural
network — there is no measured benefit here to justify one.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from datetime import datetime

import networkx as nx

from app.core.versions import GRAPH_VERSION
from app.features.context import RiskContext, TxnView
from app.features.util import coefficient_of_variation, gaps, safe_div
from app.graph.base import CampaignCandidate, ClusterSummary

GRAPH_FEATURE_NAMES = [
    "graph_cluster_size",
    "graph_cluster_customers",
    "graph_cluster_devices",
    "graph_cluster_networks",
    "graph_cluster_agents",
    "graph_cluster_instruments",
    "graph_cluster_merchants",
    "graph_cluster_skus",
    "graph_cluster_coupons",
    "graph_customers_per_device",
    "graph_customers_per_network",
    "graph_customers_per_agent",
    "graph_instruments_per_customer",
    "graph_device_customer_degree",
    "graph_network_customer_degree",
    "graph_agent_customer_degree",
    "graph_coupon_customer_degree",
    "graph_sku_customer_degree",
    "graph_instrument_customer_degree",
    "graph_customer_device_degree",
    "graph_shared_sku_ratio",
    "graph_shared_coupon_ratio",
    "graph_cluster_density",
    "graph_cluster_sequence_similarity",
    "graph_cluster_amount_similarity",
    "graph_cluster_interarrival_cv",
    "graph_cluster_failure_rate",
    "graph_cluster_retry_rate",
    "graph_cluster_span_seconds",
    "graph_concentration_score",
]

# Entity kinds whose reuse across many customers is structurally informative.
FAN_IN_KINDS = ("DEVICE", "NETWORK", "AGENT", "COUPON", "SKU", "INSTRUMENT")


def _cluster_key(transaction_ids: list[str]) -> str:
    digest = hashlib.sha256("|".join(sorted(transaction_ids)).encode()).hexdigest()
    return digest[:32]


class NetworkXGraphEngine:
    """In-process graph analytics over bounded windows."""

    version = GRAPH_VERSION

    def __init__(self, min_cluster_size: int = 5) -> None:
        self.min_cluster_size = min_cluster_size

    # -- graph construction ------------------------------------------------------------

    @staticmethod
    def build_graph(transactions: list[TxnView]) -> nx.Graph:
        graph = nx.Graph()
        for txn in transactions:
            txn_node = ("TRANSACTION", txn.transaction_id)
            graph.add_node(txn_node, kind="TRANSACTION", timestamp=txn.timestamp,
                           amount=txn.amount, status=txn.status, retry_count=txn.retry_count)
            for kind, value in txn.entity_keys():
                entity_node = (kind, value)
                graph.add_node(entity_node, kind=kind)
                graph.add_edge(txn_node, entity_node, relationship=f"HAS_{kind}")
        return graph

    # -- per-transaction context -------------------------------------------------------

    def build_context(self, ctx: RiskContext) -> ClusterSummary:
        # The ego-neighbourhood plus the transaction itself: everything already filtered to
        # the past-only window by the context builder.
        members = [*ctx.neighbourhood, ctx.transaction]
        return self._summarise(members, ctx.session_actions_by_session)

    def _summarise(self, members: list[TxnView], session_actions: dict | None) -> ClusterSummary:
        session_actions = session_actions or {}
        by_kind: dict[str, set[str]] = defaultdict(set)
        for txn in members:
            for kind, value in txn.entity_keys():
                by_kind[kind].add(value)

        timestamps = [t.timestamp for t in members]
        gap_series = gaps(timestamps)
        span = (max(timestamps) - min(timestamps)).total_seconds() if len(timestamps) > 1 else 0.0
        amounts = [t.amount for t in members]

        # Which entities are actually shared, i.e. touched by more than one transaction.
        shared: dict[str, list[str]] = {}
        for kind in FAN_IN_KINDS:
            counts = Counter(
                value
                for txn in members
                for k, value in txn.entity_keys()
                if k == kind
            )
            repeated = [value for value, count in counts.items() if count > 1]
            if repeated:
                shared[kind] = sorted(repeated)[:20]

        customers = by_kind.get("CUSTOMER", set())
        devices = by_kind.get("DEVICE", set())

        summary = ClusterSummary(
            cluster_key=_cluster_key([t.transaction_id for t in members]),
            transaction_ids=[t.transaction_id for t in members],
            size=len(members),
            customer_count=len(customers),
            agent_count=len(by_kind.get("AGENT", set())),
            device_count=len(devices),
            network_count=len(by_kind.get("NETWORK", set())),
            session_count=len(by_kind.get("SESSION", set())),
            instrument_count=len(by_kind.get("INSTRUMENT", set())),
            merchant_count=len(by_kind.get("MERCHANT", set())),
            sku_count=len(by_kind.get("SKU", set())),
            coupon_count=len(by_kind.get("COUPON", set())),
            shared_entities=shared,
            span_seconds=span,
            interarrival_cv=coefficient_of_variation(gap_series),
            failure_rate=safe_div(sum(1 for t in members if t.status == "FAILED"), len(members)),
            retry_rate=safe_div(sum(1 for t in members if t.retry_count > 0), len(members)),
            sequence_similarity=self._sequence_similarity(members, session_actions),
            amount_similarity=(
                1.0 - min(1.0, coefficient_of_variation(amounts)) if len(amounts) >= 3 else 0.0
            ),
            first_seen=min(timestamps) if timestamps else None,
            last_seen=max(timestamps) if timestamps else None,
        )
        summary.concentration_score = self.concentration_score(summary)
        return summary

    @staticmethod
    def _sequence_similarity(members: list[TxnView], session_actions: dict) -> float:
        """Share of sessions in the cluster running the *same* action-type sequence.

        A device farm replays one workflow; a crowd of real shoppers does not.
        """
        sequences = []
        for txn in members:
            actions = session_actions.get(txn.session_id or "", [])
            if actions:
                sequences.append(tuple(a.action_type for a in actions))
        if len(sequences) < 3:
            return 0.0
        modal_count = Counter(sequences).most_common(1)[0][1]
        return modal_count / len(sequences)

    @staticmethod
    def concentration_score(summary: ClusterSummary) -> float:
        """Bounded 0..1 heuristic describing how "farmed" a cluster looks.

        This is one *feature*, not the campaign risk score. The fusion layer learns how
        much to trust it from validation data rather than us asserting a weight here.
        """
        if summary.size < 2:
            return 0.0
        customers_per_device = safe_div(summary.customer_count, max(1, summary.device_count))
        customers_per_agent = safe_div(summary.customer_count, max(1, summary.agent_count))
        # Many accounts behind few devices/agents, one coupon or SKU, replayed workflow.
        parts = [
            min(1.0, customers_per_device / 10.0),
            min(1.0, customers_per_agent / 15.0),
            1.0 if summary.coupon_count == 1 and summary.customer_count >= 5 else 0.0,
            1.0 if summary.sku_count == 1 and summary.customer_count >= 5 else 0.0,
            summary.sequence_similarity,
            max(0.0, 1.0 - summary.interarrival_cv),
        ]
        return sum(parts) / len(parts)

    # -- features ----------------------------------------------------------------------

    def extract_features(self, ctx: RiskContext) -> dict[str, float]:
        txn = ctx.transaction
        members = [*ctx.neighbourhood, txn]
        summary = self.build_context(ctx)

        def customers_sharing(kind: str, value: str | None) -> int:
            if not value:
                return 0
            return len(
                {
                    t.customer_id
                    for t in members
                    if any(k == kind and v == value for k, v in t.entity_keys())
                }
            )

        customer_devices = len(
            {t.device_id for t in members if t.customer_id == txn.customer_id and t.device_id}
        )
        sku_matches = (
            sum(1 for t in members if txn.sku_id and t.sku_id == txn.sku_id) if txn.sku_id else 0
        )
        coupon_matches = (
            sum(1 for t in members if txn.coupon_id and t.coupon_id == txn.coupon_id)
            if txn.coupon_id
            else 0
        )

        # Density of the entity–transaction graph: how tightly interlinked the ego-net is.
        graph = self.build_graph(members)
        density = nx.density(graph) if graph.number_of_nodes() > 1 else 0.0

        return {
            "graph_cluster_size": float(summary.size),
            "graph_cluster_customers": float(summary.customer_count),
            "graph_cluster_devices": float(summary.device_count),
            "graph_cluster_networks": float(summary.network_count),
            "graph_cluster_agents": float(summary.agent_count),
            "graph_cluster_instruments": float(summary.instrument_count),
            "graph_cluster_merchants": float(summary.merchant_count),
            "graph_cluster_skus": float(summary.sku_count),
            "graph_cluster_coupons": float(summary.coupon_count),
            "graph_customers_per_device": safe_div(
                summary.customer_count, max(1, summary.device_count)
            ),
            "graph_customers_per_network": safe_div(
                summary.customer_count, max(1, summary.network_count)
            ),
            "graph_customers_per_agent": safe_div(
                summary.customer_count, max(1, summary.agent_count)
            ),
            "graph_instruments_per_customer": safe_div(
                summary.instrument_count, max(1, summary.customer_count)
            ),
            "graph_device_customer_degree": float(customers_sharing("DEVICE", txn.device_id)),
            "graph_network_customer_degree": float(
                customers_sharing("NETWORK", txn.network_fingerprint)
            ),
            "graph_agent_customer_degree": float(customers_sharing("AGENT", txn.agent_id)),
            "graph_coupon_customer_degree": float(customers_sharing("COUPON", txn.coupon_id)),
            "graph_sku_customer_degree": float(customers_sharing("SKU", txn.sku_id)),
            "graph_instrument_customer_degree": float(
                customers_sharing("INSTRUMENT", txn.instrument_fingerprint)
            ),
            "graph_customer_device_degree": float(customer_devices),
            "graph_shared_sku_ratio": safe_div(sku_matches, len(members)),
            "graph_shared_coupon_ratio": safe_div(coupon_matches, len(members)),
            "graph_cluster_density": float(density),
            "graph_cluster_sequence_similarity": summary.sequence_similarity,
            "graph_cluster_amount_similarity": summary.amount_similarity,
            "graph_cluster_interarrival_cv": summary.interarrival_cv,
            "graph_cluster_failure_rate": summary.failure_rate,
            "graph_cluster_retry_rate": summary.retry_rate,
            "graph_cluster_span_seconds": summary.span_seconds,
            "graph_concentration_score": summary.concentration_score,
        }

    # -- campaign detection ------------------------------------------------------------

    def find_campaigns(
        self,
        transactions: list[TxnView],
        session_actions: dict | None = None,
        min_size: int | None = None,
    ) -> list[CampaignCandidate]:
        """Connected components over shared-entity edges, scored by concentration.

        Merchant and SKU are excluded from the linking edges, otherwise every transaction
        at a busy merchant collapses into one giant component that means nothing.
        """
        min_size = min_size or self.min_cluster_size
        if len(transactions) < min_size:
            return []

        linker = nx.Graph()
        for txn in transactions:
            txn_node = ("TRANSACTION", txn.transaction_id)
            linker.add_node(txn_node)
            for kind, value in txn.linking_keys():
                if kind in ("SKU", "SESSION"):
                    continue
                linker.add_edge(txn_node, (kind, value))

        by_id = {t.transaction_id: t for t in transactions}
        candidates: list[CampaignCandidate] = []
        for component in nx.connected_components(linker):
            txn_ids = [node[1] for node in component if node[0] == "TRANSACTION"]
            if len(txn_ids) < min_size:
                continue
            members = [by_id[i] for i in txn_ids if i in by_id]
            if len(members) < min_size:
                continue
            summary = self._summarise(members, session_actions)
            summary.cluster_key = _cluster_key(txn_ids)
            candidates.append(
                CampaignCandidate(
                    cluster=summary,
                    score=summary.concentration_score,
                    reasons=self._reasons(summary),
                )
            )
        candidates.sort(key=lambda c: (-c.score, -c.cluster.size))
        return candidates

    @staticmethod
    def _reasons(summary: ClusterSummary) -> list[dict]:
        reasons: list[dict] = []
        if summary.device_count and summary.customer_count / summary.device_count >= 3:
            reasons.append(
                {
                    "signal": "shared_device_cluster",
                    "observed": (
                        f"{summary.customer_count} customer accounts share "
                        f"{summary.device_count} device fingerprint(s)"
                    ),
                    "observed_value": summary.customer_count / summary.device_count,
                    "expected_value": 1.0,
                }
            )
        if summary.coupon_count == 1 and summary.customer_count >= 5:
            reasons.append(
                {
                    "signal": "coupon_concentration",
                    "observed": (
                        f"one coupon redeemed across {summary.customer_count} accounts "
                        f"within {summary.span_seconds:.0f}s"
                    ),
                    "observed_value": float(summary.customer_count),
                    "expected_value": 1.0,
                }
            )
        if summary.sequence_similarity >= 0.7 and summary.size >= 5:
            reasons.append(
                {
                    "signal": "action_sequence_similarity",
                    "observed": (
                        f"{summary.sequence_similarity:.0%} of sessions in the cluster replay "
                        "an identical action sequence"
                    ),
                    "observed_value": summary.sequence_similarity,
                    "expected_value": 0.2,
                }
            )
        if summary.size >= 5 and summary.interarrival_cv <= 0.15 and summary.span_seconds > 0:
            reasons.append(
                {
                    "signal": "scripted_cadence",
                    "observed": (
                        f"{summary.size} transactions arrived on a near-constant cadence "
                        f"(interarrival CoV {summary.interarrival_cv:.2f})"
                    ),
                    "observed_value": summary.interarrival_cv,
                    "expected_value": 0.5,
                }
            )
        if summary.failure_rate >= 0.5 and summary.size >= 5:
            reasons.append(
                {
                    "signal": "cluster_failure_rate",
                    "observed": (
                        f"{summary.failure_rate:.0%} of transactions in the cluster failed"
                    ),
                    "observed_value": summary.failure_rate,
                    "expected_value": 0.05,
                }
            )
        if summary.customer_count and summary.instrument_count / summary.customer_count >= 3:
            reasons.append(
                {
                    "signal": "instrument_fan_out",
                    "observed": (
                        f"{summary.instrument_count} distinct payment instruments across "
                        f"{summary.customer_count} accounts"
                    ),
                    "observed_value": summary.instrument_count / summary.customer_count,
                    "expected_value": 1.0,
                }
            )
        return reasons


def default_graph_engine() -> NetworkXGraphEngine:
    return NetworkXGraphEngine()
