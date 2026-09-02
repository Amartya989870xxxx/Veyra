"""Unit tests for incident clustering, temporal overlap matching, and detection latency (Phase 5.2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import pytest

from app.evaluation.incidents import (
    FlaggedWindowRecord,
    GroundTruthIncident,
    assemble_predicted_incidents,
    match_incidents,
)
from app.windows import WindowSize


def test_assemble_predicted_incidents_merges_contiguous_runs():
    """Verify flagged consecutive windows merge into single predicted incident."""
    base_t = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)
    windows = [
        FlaggedWindowRecord("m_001", WindowSize.M1, base_t + timedelta(minutes=1), 0.85, 1000.0),
        FlaggedWindowRecord("m_001", WindowSize.M1, base_t + timedelta(minutes=2), 0.90, 1200.0),
        FlaggedWindowRecord("m_001", WindowSize.M1, base_t + timedelta(minutes=3), 0.80, 800.0),
        # Gap > tolerance (5 minutes later)
        FlaggedWindowRecord("m_001", WindowSize.M1, base_t + timedelta(minutes=8), 0.75, 500.0),
    ]

    incidents = assemble_predicted_incidents(windows, gap_tolerance_seconds=120)

    # 4 windows should group into 2 distinct incidents
    assert len(incidents) == 2
    assert incidents[0].window_count == 3
    assert incidents[0].max_risk_score == 0.90
    assert incidents[0].total_gmv == 3000.0
    assert incidents[1].window_count == 1


def test_match_incidents_computes_latency_and_recall():
    """Verify temporal overlap matching and detection latency calculation."""
    base_t = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)

    # Ground truth incident starts at 12:00 and lasts 15 minutes
    gt = [
        GroundTruthIncident(
            scenario_id="card_testing_burst",
            merchant_id="m_001",
            start_time=base_t,
            end_time=base_t + timedelta(minutes=15),
            is_attack=True,
            total_gmv=50000.0,
        )
    ]

    # Model flags first window at 12:02 (2 minutes latency)
    flagged = [
        FlaggedWindowRecord("m_001", WindowSize.M1, base_t + timedelta(minutes=2), 0.90, 5000.0),
        FlaggedWindowRecord("m_001", WindowSize.M1, base_t + timedelta(minutes=3), 0.92, 5000.0),
    ]

    preds = assemble_predicted_incidents(flagged)
    results = match_incidents(preds, gt)

    assert results.true_positive_count == 1
    assert results.false_negative_count == 0
    assert results.incident_recall == 1.0
    assert results.latency_p50_minutes == pytest.approx(1.0, abs=0.5)
    assert results.caught_fraud_gmv == 50000.0
    assert results.missed_fraud_gmv == 0.0
