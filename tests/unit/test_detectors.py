"""Unit tests for comparative detectors (Detector A, B, C) (Phase 4.1)."""

from __future__ import annotations

import numpy as np
import pytest

from app.models_ml.contextual import ContextualMLDetector
from app.models_ml.fusion import VeyraFusionDetector
from app.models_ml.volume import VolumeOnlyDetector


def test_volume_only_detector_fit_and_predict():
    """Verify Detector A trains on volume deviations and emits valid probabilities."""
    X = [
        {"A.txn_rate_dev": 0.1, "B.txn_count": 10.0},
        {"A.txn_rate_dev": 0.5, "B.txn_count": 15.0},
        {"A.txn_rate_dev": 4.5, "B.txn_count": 200.0},
        {"A.txn_rate_dev": 6.0, "B.txn_count": 350.0},
    ]
    y = [0, 0, 1, 1]

    detector = VolumeOnlyDetector()
    detector.fit(X, y)

    probs = detector.predict_proba(X)
    assert len(probs) == 4
    assert np.all(probs >= 0.0) and np.all(probs <= 1.0)
    assert probs[3] > probs[0], "Higher volume deviation must produce higher risk probability"


def test_contextual_ml_detector_excludes_graph_features():
    """Verify Detector B fits on statistical features and strictly excludes Family J graph features."""
    X = [
        {"A.txn_rate": 10.0, "C.failure_rate": 0.02, "D.amount_median": 500.0, "J.bipartite_gini": 0.1},
        {"A.txn_rate": 12.0, "C.failure_rate": 0.03, "D.amount_median": 450.0, "J.bipartite_gini": 0.2},
        {"A.txn_rate": 80.0, "C.failure_rate": 0.90, "D.amount_median": 20.0, "J.bipartite_gini": 0.95},
        {"A.txn_rate": 95.0, "C.failure_rate": 0.85, "D.amount_median": 25.0, "J.bipartite_gini": 0.90},
    ]
    y = [0, 0, 1, 1]

    detector = ContextualMLDetector()
    detector.fit(X, y)

    # Assert Family J was excluded from feature names
    assert "J.bipartite_gini" not in detector.feature_names
    assert "A.txn_rate" in detector.feature_names
    assert "C.failure_rate" in detector.feature_names

    probs = detector.predict_proba(X)
    assert len(probs) == 4
    assert probs[2] > probs[0]


def test_veyra_fusion_detector_includes_graph_and_statistical_features():
    """Verify Detector C consumes full feature set including graph relationship metrics."""
    X = [
        {
            "A.txn_rate": 10.0,
            "C.failure_rate": 0.02,
            "D.amount_median": 500.0,
            "J.bipartite_gini": 0.05,
            "J.largest_cluster_vol_share": 0.10,
        },
        {
            "A.txn_rate": 12.0,
            "C.failure_rate": 0.03,
            "D.amount_median": 550.0,
            "J.bipartite_gini": 0.08,
            "J.largest_cluster_vol_share": 0.12,
        },
        {
            "A.txn_rate": 80.0,
            "C.failure_rate": 0.90,
            "D.amount_median": 30.0,
            "J.bipartite_gini": 0.95,
            "J.largest_cluster_vol_share": 0.85,
        },
        {
            "A.txn_rate": 95.0,
            "C.failure_rate": 0.85,
            "D.amount_median": 25.0,
            "J.bipartite_gini": 0.92,
            "J.largest_cluster_vol_share": 0.88,
        },
    ]
    y = [0, 0, 1, 1]

    detector = VeyraFusionDetector()
    detector.fit(X, y)

    assert "J.bipartite_gini" in detector.feature_names
    assert "J.largest_cluster_vol_share" in detector.feature_names
    assert "C.failure_rate" in detector.feature_names

    probs = detector.predict_proba(X)
    assert len(probs) == 4
    assert probs[2] > 0.60
    assert probs[0] < 0.40
