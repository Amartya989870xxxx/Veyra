"""Visual evidence and UI payload builders for incident dashboards (Phase 6.2).

Generates structured JSON payloads for frontend analysts:
- Top feature deviations (z-scores/MADs)
- Bipartite entity graph nodes and edges for network canvas rendering
- Baseline comparison sparkline data
"""

from __future__ import annotations

from typing import Any, Sequence
from app.schemas.entities import PaymentAttempt
from data.generators.timeline import AnnotatedTransaction


def build_top_feature_deviations(
    features: dict[str, float],
    top_k: int = 6,
) -> list[dict[str, Any]]:
    """Return top contributing feature deviations sorted by absolute magnitude."""
    dev_features = []
    for k, v in features.items():
        if k.endswith("_dev"):
            base_name = k[:-4]
            dev_features.append({
                "feature_id": base_name,
                "deviation_mad": round(float(v), 2),
                "raw_value": round(float(features.get(base_name, 0.0)), 2),
                "direction": "HIGH" if v > 0 else "LOW",
            })

    dev_features.sort(key=lambda x: abs(x["deviation_mad"]), reverse=True)
    return dev_features[:top_k]


def build_entity_graph_payload(
    transactions: Sequence[AnnotatedTransaction | PaymentAttempt],
    max_nodes: int = 50,
) -> dict[str, Any]:
    """Build node-link bipartite entity graph structure for UI canvas rendering."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str]] = set()

    for item in transactions:
        attempt = item.attempt if isinstance(item, AnnotatedTransaction) else item

        cust_id = f"CUS:{attempt.customer_id or f'anon_{attempt.transaction_id}'}"
        dev_id = f"DEV:{attempt.device_fp or f'anon_{attempt.transaction_id}'}"
        inst_id = f"INS:{attempt.instrument_fp}"
        ip_id = f"IP:{attempt.ip_fp or f'anon_{attempt.transaction_id}'}"

        # Register nodes
        if cust_id not in nodes and len(nodes) < max_nodes:
            nodes[cust_id] = {"id": cust_id, "type": "customer", "label": cust_id[4:14]}
        if dev_id not in nodes and len(nodes) < max_nodes:
            nodes[dev_id] = {"id": dev_id, "type": "device", "label": dev_id[4:14]}
        if inst_id not in nodes and len(nodes) < max_nodes:
            nodes[inst_id] = {"id": inst_id, "type": "instrument", "label": inst_id[4:14]}
        if ip_id not in nodes and len(nodes) < max_nodes:
            nodes[ip_id] = {"id": ip_id, "type": "ip", "label": ip_id[3:13]}

        # Register edges
        pair1 = (cust_id, dev_id)
        if pair1 not in seen_edges and cust_id in nodes and dev_id in nodes:
            seen_edges.add(pair1)
            edges.append({"source": cust_id, "target": dev_id, "type": "used_device"})

        pair2 = (dev_id, inst_id)
        if pair2 not in seen_edges and dev_id in nodes and inst_id in nodes:
            seen_edges.add(pair2)
            edges.append({"source": dev_id, "target": inst_id, "type": "used_card"})

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "total_nodes": len(nodes),
        "total_edges": len(edges),
    }
