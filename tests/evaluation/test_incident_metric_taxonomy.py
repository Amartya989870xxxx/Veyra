"""Adversarial cases for the incident metric taxonomy.

The point of these is to pin down *intentional* behaviour in the situations where
"incident recall" is ambiguous, so nobody can later present one number as if it meant
another. Each case below is named in the task that prompted this work.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.evaluation.incident_metrics import evaluate_incident_detection
from app.evaluation.incidents import GroundTruthIncident, PredictedIncident

T0 = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)
M = "m_1"


def _gt(start_min: float, end_min: float, merchant: str = M, scenario: str = "card_testing_burst"):
    return GroundTruthIncident(
        scenario_id=scenario,
        merchant_id=merchant,
        start_time=T0 + timedelta(minutes=start_min),
        end_time=T0 + timedelta(minutes=end_min),
        is_attack=True,
        total_gmv=1000.0,
    )


def _pred(start_min: float, end_min: float, merchant: str = M):
    return PredictedIncident(
        incident_id=f"p_{start_min}_{end_min}",
        merchant_id=merchant,
        first_flag_time=T0 + timedelta(minutes=start_min),
        last_flag_time=T0 + timedelta(minutes=end_min),
        window_count=int(end_min - start_min),
        max_risk_score=0.9,
        total_gmv=1000.0,
    )


def test_case_a_one_prediction_one_ground_truth():
    """Case A: clean 1:1. Everything should be maximal and unambiguous."""
    report = evaluate_incident_detection([_pred(0, 30)], [_gt(0, 30)])

    assert report.detection_recall == 1.0
    assert report.strict_match_recall == 1.0
    assert report.incident_precision == 1.0
    assert report.false_alarm_incidents == 0
    assert report.mean_temporal_iou == pytest.approx(1.0)
    assert report.fragmentation_index == pytest.approx(1.0)
    assert report.merge_index == pytest.approx(1.0)


def test_case_b_one_prediction_spanning_one_incidents_many_windows():
    """Case B: one prediction covering the contiguous windows of a single real incident.

    This is the *correct* behaviour of a well-behaved detector and must score fully on
    both recall metrics — it is not fragmentation and not merging.
    """
    report = evaluate_incident_detection([_pred(0, 30)], [_gt(2, 28)])

    assert report.detection_recall == 1.0
    assert report.strict_match_recall == 1.0
    assert report.fragmentation_index == pytest.approx(1.0)
    assert report.merge_index == pytest.approx(1.0)
    # Boundaries are close but not exact, so IoU is high yet below 1.
    assert 0.8 < report.mean_temporal_iou < 1.0


def test_case_c_one_broad_prediction_swallows_multiple_ground_truths():
    """Case C: the divergence that produced the 45% vs 100% gap.

    One prediction materially overlapping three distinct incidents: all three were
    *noticed* (detection_recall 1.0) but only one got its own distinct prediction
    (strict_match_recall 1/3). Both are correct answers to different questions, and
    `merge_index` is what explains the gap.
    """
    pred = _pred(0, 120)
    gts = [_gt(0, 20), _gt(40, 60), _gt(90, 110)]

    report = evaluate_incident_detection([pred], gts)

    assert report.detection_recall == 1.0
    assert report.strict_match_recall == pytest.approx(1 / 3)
    assert report.merge_index == pytest.approx(3.0)
    assert report.detected_count == 3
    assert report.strict_matched_count == 1
    # A single sprawling prediction localises badly, and IoU says so.
    assert report.mean_temporal_iou < 0.35


def test_case_d_fragmented_predictions_over_one_incident():
    """Case D: one real incident split across several predictions.

    Detected once (not three times), and fragmentation_index reports the splitting.
    Precision must not be punished — every fragment is a true overlap.
    """
    preds = [_pred(0, 8), _pred(10, 18), _pred(20, 30)]
    report = evaluate_incident_detection(preds, [_gt(0, 30)])

    assert report.detected_count == 1
    assert report.detection_recall == 1.0
    assert report.strict_match_recall == 1.0  # one GT, one claim
    assert report.fragmentation_index == pytest.approx(3.0)
    assert report.false_alarm_incidents == 0
    assert report.incident_precision == 1.0


def test_case_e_tiny_accidental_overlap_does_not_count_as_detection():
    """Case E: a one-minute brush against a two-hour attack is not a detection.

    Without this rule any "flag something occasionally" detector reaches 100% recall,
    which is how an unfalsifiable number gets published.
    """
    gt = _gt(0, 120)  # two hours
    brush = _pred(119, 120)  # one minute of overlap, ~0.8% of the incident

    report = evaluate_incident_detection([brush], [gt])

    assert report.detection_recall == 0.0, "a trivial overlap must not count as detection"
    assert report.strict_match_recall == 0.0
    assert report.false_alarm_incidents == 1


def test_case_e_material_overlap_does_count():
    """The complement of Case E: a substantial overlap on the same incident counts."""
    gt = _gt(0, 120)
    substantial = _pred(90, 120)  # 25% of the incident

    report = evaluate_incident_detection([substantial], [gt])

    assert report.detection_recall == 1.0
    assert report.detected_count == 1


def test_short_incidents_remain_detectable():
    """The 60s floor must not make brief incidents impossible to detect."""
    gt = _gt(0, 1)  # one minute
    report = evaluate_incident_detection([_pred(0, 1)], [gt])
    assert report.detection_recall == 1.0


def test_predictions_never_cross_merchant_boundaries():
    report = evaluate_incident_detection(
        [_pred(0, 30, merchant="m_other")], [_gt(0, 30, merchant="m_1")]
    )
    assert report.detection_recall == 0.0
    assert report.false_alarm_incidents == 1


def test_false_alarms_are_counted_separately_from_misses():
    gts = [_gt(0, 30)]
    preds = [_pred(0, 30), _pred(200, 230)]  # one hit, one spurious

    report = evaluate_incident_detection(preds, gts)

    assert report.detection_recall == 1.0
    assert report.false_alarm_incidents == 1
    assert report.incident_precision == pytest.approx(0.5)


def test_no_ground_truth_incidents_does_not_fabricate_perfect_recall():
    """A split with no attacks must not report 1.0 recall — there is nothing to recall."""
    report = evaluate_incident_detection([_pred(0, 10)], [])
    assert report.n_ground_truth == 0
    assert report.detection_recall == 0.0
    assert report.strict_match_recall == 0.0
    assert report.false_alarm_incidents == 1


def test_strict_recall_never_exceeds_detection_recall():
    """Structural invariant: you cannot separate more incidents than you noticed."""
    scenarios = [
        ([_pred(0, 120)], [_gt(0, 20), _gt(40, 60), _gt(90, 110)]),
        ([_pred(0, 8), _pred(10, 18)], [_gt(0, 30)]),
        ([_pred(0, 30), _pred(200, 230)], [_gt(0, 30), _gt(205, 225)]),
        ([], [_gt(0, 30)]),
    ]
    for preds, gts in scenarios:
        report = evaluate_incident_detection(preds, gts)
        assert report.strict_match_recall <= report.detection_recall + 1e-9


def test_missed_incident_is_reported_as_missed():
    report = evaluate_incident_detection([], [_gt(0, 30)])
    assert report.detection_recall == 0.0
    assert report.detected_count == 0
    assert report.n_predicted == 0


def test_report_table_never_mixes_incident_metric_families():
    import importlib.util
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[2] / "scripts" / "generate_experiment_report.py"
    spec = importlib.util.spec_from_file_location("veyra_report_gen_family_check", script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    source = script.read_text(encoding="utf-8")
    # The detector table must read the taxonomy fields, never the legacy any-overlap one.
    assert "incident_detection_rate" in source
    assert "incident_strict_recall" in source
    assert "'incident_recall'" not in source, (
        "report generator is reading the legacy any-overlap incident_recall; pairing it "
        "with the strict column breaks the strict <= detection invariant in the table"
    )
