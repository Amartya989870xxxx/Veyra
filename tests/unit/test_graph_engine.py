"""Unit tests for GraphEngine and Family J relationship features (Phase 3.3)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.graph.engine import GraphEngine
from app.graph.metrics import compute_gini, compute_shannon_entropy
from app.schemas.entities import Geo, InstrumentMeta, PaymentAttempt
from data.generators.population import generate_merchant_population
from data.generators.recipes import inject_card_testing_burst, inject_flash_sale_spike
import random


def test_gini_concentration_metric():
    """Verify Gini calculation on uniform vs extreme concentration."""
    # Uniform: [10, 10, 10, 10] -> Gini = 0.0
    assert compute_gini([10, 10, 10, 10]) == pytest.approx(0.0, abs=1e-4)

    # Extreme star concentration: [100, 0, 0, 0, 0] -> Gini > 0.7
    assert compute_gini([100, 0, 0, 0, 0]) > 0.7


def test_graph_features_distinguish_card_testing_ring_from_flash_sale():
    """Verify that card testing ring exhibits high bipartite Gini and cluster concentration."""
    profile = generate_merchant_population(n_merchants=1, seed=42)[0]
    now = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)

    # 1. Card testing ring (30 txns on 1 device)
    ct_txns = inject_card_testing_burst(profile, now, random.Random(42), intensity=1.0)
    engine = GraphEngine()
    ct_graph = engine.compute_window_graph_features(ct_txns)

    # 2. Flash sale (independent buyers)
    fs_txns = inject_flash_sale_spike(profile, now, random.Random(42), intensity=1.0)
    fs_graph = engine.compute_window_graph_features(fs_txns)

    # Card testing ring has extreme device concentration
    assert ct_graph.largest_cluster_vol_share > 0.5
    # Flash sale has dispersed independent entities
    assert fs_graph.devices_per_account_max <= 2


def test_cross_merchant_entity_tracking():
    """Verify that multi-merchant entity appearances are captured in Family J."""
    now = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)
    attempt = PaymentAttempt(
        transaction_id="txn_multi_1",
        merchant_id="m_001",
        customer_id="cus_syndicate",
        instrument_fp="if_syndicate",
        device_fp="dv_syndicate",
        amount=Decimal("100.00"),
        timestamp=now,
    )

    cross_map = {
        "DEV:dv_syndicate": {"m_001", "m_002", "m_003"},
        "INS:if_syndicate": {"m_001", "m_002"},
    }

    engine = GraphEngine()
    res = engine.compute_window_graph_features([attempt], cross_merchant_entity_map=cross_map)

    assert res.cross_merchant_entities >= 2
    assert res.cross_merchant_fanout_max == 3
