"""Relationship and entity graph engine for Veyra v2 (Phase 3.3).

Computes bipartite degree distributions, Gini concentration coefficients, connected
component cluster metrics, and cross-merchant tracking for Family J features.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence

import networkx as nx

from app.graph.metrics import compute_gini
from app.schemas.entities import PaymentAttempt
from data.generators.timeline import AnnotatedTransaction


@dataclass
class GraphFeatures:
    devices_per_account_max: float = 1.0
    accounts_per_ip_max: float = 1.0
    bipartite_gini: float = 0.0
    cluster_count: int = 0
    largest_cluster_size: int = 0
    largest_cluster_vol_share: float = 0.0
    cluster_density: float = 0.0
    cluster_density_z: float = 0.0
    entity_novelty_share: float = 0.0
    cross_merchant_entities: int = 0
    cross_merchant_fanout_max: int = 1
    shared_address_clusters: int = 0

    def to_dict(self) -> dict[str, float]:
        return {
            "J.devices_per_account_max": float(self.devices_per_account_max),
            "J.accounts_per_ip_max": float(self.accounts_per_ip_max),
            "J.bipartite_gini": float(self.bipartite_gini),
            "J.cluster_count": float(self.cluster_count),
            "J.largest_cluster_size": float(self.largest_cluster_size),
            "J.largest_cluster_vol_share": float(self.largest_cluster_vol_share),
            "J.cluster_density": float(self.cluster_density),
            "J.cluster_density_z": float(self.cluster_density_z),
            "J.entity_novelty_share": float(self.entity_novelty_share),
            "J.cross_merchant_entities": float(self.cross_merchant_entities),
            "J.cross_merchant_fanout_max": float(self.cross_merchant_fanout_max),
            "J.shared_address_clusters": float(self.shared_address_clusters),
        }


class GraphEngine:
    """Extracts bipartite degree distributions and graph clusters past-only."""

    def __init__(self, historical_entities: set[str] | None = None) -> None:
        self.historical_entities = historical_entities or set()

    def compute_window_graph_features(
        self,
        transactions: Sequence[AnnotatedTransaction | PaymentAttempt],
        cross_merchant_entity_map: dict[str, set[str]] | None = None,
    ) -> GraphFeatures:
        if not transactions:
            return GraphFeatures()

        G = nx.Graph()
        account_devices: dict[str, set[str]] = defaultdict(set)
        ip_accounts: dict[str, set[str]] = defaultdict(set)
        entity_txns: dict[str, int] = defaultdict(int)

        current_entities: set[str] = set()

        for item in transactions:
            attempt = item.attempt if isinstance(item, AnnotatedTransaction) else item
            cust = attempt.customer_id or f"anon_cus_{attempt.transaction_id}"
            dev = attempt.device_fp or f"anon_dev_{attempt.transaction_id}"
            inst = attempt.instrument_fp
            ip = attempt.ip_fp or f"anon_ip_{attempt.transaction_id}"

            cust_node = f"CUS:{cust}"
            dev_node = f"DEV:{dev}"
            inst_node = f"INS:{inst}"
            ip_node = f"IP:{ip}"

            current_entities.update({cust_node, dev_node, inst_node, ip_node})

            # Record bipartite associations
            account_devices[cust].add(dev)
            ip_accounts[ip].add(cust)

            # Build graph edges
            G.add_edge(cust_node, dev_node, txn_id=attempt.transaction_id)
            G.add_edge(dev_node, inst_node, txn_id=attempt.transaction_id)
            G.add_edge(cust_node, ip_node, txn_id=attempt.transaction_id)

            entity_txns[cust_node] += 1
            entity_txns[dev_node] += 1

        # 1. Degree distributions
        devices_per_account = [len(devs) for devs in account_devices.values()]
        accounts_per_ip = [len(accs) for accs in ip_accounts.values()]

        max_dev_per_acc = max(devices_per_account) if devices_per_account else 1
        max_acc_per_ip = max(accounts_per_ip) if accounts_per_ip else 1

        # Bipartite degree Gini (accounts per device distribution)
        device_degrees = [d for n, d in G.degree() if n.startswith("DEV:")]
        bipartite_gini = compute_gini(device_degrees) if device_degrees else 0.0

        # 2. Connected Components & Cluster Extraction
        components = list(nx.connected_components(G))
        cluster_count = len(components)

        total_txns = len(transactions)
        largest_cluster_size = 0
        largest_cluster_vol_share = 0.0
        cluster_density = 0.0
        cluster_density_z = 0.0

        if components:
            largest_comp = max(components, key=len)
            subG = G.subgraph(largest_comp)
            n_nodes = subG.number_of_nodes()
            n_edges = subG.number_of_edges()

            largest_cluster_size = n_edges  # Number of transaction edges in largest ring
            largest_cluster_vol_share = min(1.0, largest_cluster_size / max(1, total_txns))

            cluster_density = n_edges / max(1, n_nodes)
            # Density relative to expected baseline density
            cluster_density_z = cluster_density / max(1.0, (n_nodes - 1.0) / 2.0) if n_nodes > 2 else 0.0

        # 3. Novelty vs historical entities
        novel_count = sum(1 for e in current_entities if e not in self.historical_entities)
        novelty_share = novel_count / max(1, len(current_entities))

        # 4. Cross-merchant fanout
        cross_merchant_entities = 0
        cross_merchant_fanout_max = 1
        if cross_merchant_entity_map:
            for e in current_entities:
                merchants_touched = cross_merchant_entity_map.get(e, set())
                if len(merchants_touched) > 1:
                    cross_merchant_entities += 1
                    cross_merchant_fanout_max = max(cross_merchant_fanout_max, len(merchants_touched))

        return GraphFeatures(
            devices_per_account_max=float(max_dev_per_acc),
            accounts_per_ip_max=float(max_acc_per_ip),
            bipartite_gini=float(bipartite_gini),
            cluster_count=cluster_count,
            largest_cluster_size=largest_cluster_size,
            largest_cluster_vol_share=float(largest_cluster_vol_share),
            cluster_density=float(cluster_density),
            cluster_density_z=float(cluster_density_z),
            entity_novelty_share=float(novelty_share),
            cross_merchant_entities=cross_merchant_entities,
            cross_merchant_fanout_max=cross_merchant_fanout_max,
            shared_address_clusters=0,
        )
