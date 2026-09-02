"""The benchmark report must not invent results for scenarios that were never tested.

This is a regression test for a specific defect: a previous report generator kept a
hardcoded fallback list of three hard-negative scenario names and printed "0 false
positives" for each whenever the run produced no hard-negative records at all — turning
"never evaluated" into "evaluated and clean". These tests drive the report generator with
a payload where scenarios are deliberately absent and assert the output says so.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from app.evaluation.coverage import NOT_EVALUATED
from data.generators.pipeline import ATTACK_SCENARIOS, HARD_NEGATIVE_SCENARIOS

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "generate_experiment_report.py"


def _load_generator_module():
    spec = importlib.util.spec_from_file_location("veyra_report_generator", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _detector_block(hard_negative_fps=None, fraud_scenario_recall=None):
    return {
        "precision": 0.9, "recall": 0.8, "f1": 0.85, "pr_auc": 0.9, "roc_auc": 0.95,
        "tn": 100, "fp": 5, "fn": 10, "tp": 40,
        "false_positive_rate": 0.05, "false_negative_rate": 0.2,
        "incident_recall": 0.5, "incident_tp": 2, "incident_fn": 2,
        "incident_detection_rate": 0.75,
        "incident_strict_recall": 0.50,
        "mean_temporal_iou": 0.42,
        "fragmentation_index": 1.2,
        "merge_index": 2.1,
        "incident_precision": 0.8,
        "hard_negative_fps": hard_negative_fps or {},
        "fraud_scenario_recall": fraud_scenario_recall or {},
        "expected_loss": 12345.0,
        "threshold": 0.5,
    }


def _payload(test_fraud_scenarios, test_hard_negative_scenarios, detectors):
    return {
        "config": {
            "seeds": [42], "merchants": 4, "days": 6,
            "injections_per_split_per_merchant": 3, "review_capacity_cap": 0.15,
            "fn_cost_inr": 5000.0, "fp_cost_inr": 250.0, "runtime_seconds": 10.0,
            "baselines_fitted": False,
        },
        "seeds": [
            {
                "seed": 42,
                "n_test_windows": 1000,
                "test_fraud_episodes": sum(test_fraud_scenarios.values()),
                "test_hard_negative_episodes": sum(test_hard_negative_scenarios.values()),
                "test_fraud_scenarios": test_fraud_scenarios,
                "test_hard_negative_scenarios": test_hard_negative_scenarios,
                "dev_twins_are_raw_values": True,
                "detectors": detectors,
            }
        ],
        "aggregate": {},
    }


@pytest.fixture(scope="module")
def generator():
    return _load_generator_module()


def test_absent_hard_negative_scenario_renders_not_evaluated(generator):
    """Only one hard negative present: the other two must say NOT EVALUATED, not 0."""
    present = HARD_NEGATIVE_SCENARIOS[0]
    absent = HARD_NEGATIVE_SCENARIOS[1:]

    detectors = {
        name: _detector_block(hard_negative_fps={present: 3})
        for name in ("volume_only", "contextual_ml", "veyra_fusion",
                     "ablation_graph_only", "ablation_contextual_no_dev")
    }
    payload = _payload({ATTACK_SCENARIOS[0]: 2}, {present: 2}, detectors)

    report = generator.build_report(payload, None)

    for scenario in absent:
        line = next(
            l for l in report.splitlines()
            if l.lstrip().startswith("|") and f"`{scenario}`" in l and "Episodes" not in l
        )
        assert NOT_EVALUATED in line, f"absent scenario {scenario} did not report NOT EVALUATED: {line}"
        assert "| 0 |" not in line.replace(f"`{scenario}` | 0 |", ""), (
            f"absent scenario {scenario} rendered a fabricated zero: {line}"
        )


def test_absent_fraud_scenario_renders_not_evaluated(generator):
    present = ATTACK_SCENARIOS[0]
    detectors = {
        name: _detector_block(fraud_scenario_recall={present: [2, 3]})
        for name in ("volume_only", "contextual_ml", "veyra_fusion",
                     "ablation_graph_only", "ablation_contextual_no_dev")
    }
    payload = _payload({present: 3}, {HARD_NEGATIVE_SCENARIOS[0]: 1}, detectors)

    report = generator.build_report(payload, None)

    section = report.split("## 5. Fraud Scenario Results")[1].split("## 6.")[0]
    for scenario in ATTACK_SCENARIOS[1:]:
        # Match the table ROW, not prose that happens to name the scenario.
        line = next(
            l for l in section.splitlines()
            if l.lstrip().startswith("|") and f"`{scenario}`" in l
        )
        assert NOT_EVALUATED in line, f"{scenario} was never tested but did not say so: {line}"
        assert "%" not in line, f"{scenario} was never tested but a recall percentage was printed: {line}"


def test_present_scenario_reports_real_numbers(generator):
    present = HARD_NEGATIVE_SCENARIOS[0]
    detectors = {
        name: _detector_block(hard_negative_fps={present: 17})
        for name in ("volume_only", "contextual_ml", "veyra_fusion",
                     "ablation_graph_only", "ablation_contextual_no_dev")
    }
    payload = _payload({ATTACK_SCENARIOS[0]: 1}, {present: 4}, detectors)

    report = generator.build_report(payload, None)
    line = next(
        l for l in report.split("## 4. Hard-Negative Results")[1].split("## 5.")[0].splitlines()
        if f"`{present}`" in l
    )
    assert "17" in line
    assert NOT_EVALUATED not in line


def test_report_states_dev_twin_finding_when_baselines_unfitted(generator):
    detectors = {
        name: _detector_block()
        for name in ("volume_only", "contextual_ml", "veyra_fusion",
                     "ablation_graph_only", "ablation_contextual_no_dev")
    }
    payload = _payload({ATTACK_SCENARIOS[0]: 1}, {HARD_NEGATIVE_SCENARIOS[0]: 1}, detectors)

    # The fixture sets baselines_fitted=False and dev_twins_are_raw_values=True, i.e. the
    # inert-baseline condition. The report must say so and void the conclusion rather
    # than quietly presenting the `_dev` ablation as a measurement.
    report = generator.build_report(payload, None)
    assert "measuring nothing" in report
    assert "void" in report


def test_report_never_claims_guarantees(generator):
    """Language check: the report must not overclaim."""
    detectors = {
        name: _detector_block()
        for name in ("volume_only", "contextual_ml", "veyra_fusion",
                     "ablation_graph_only", "ablation_contextual_no_dev")
    }
    payload = _payload({ATTACK_SCENARIOS[0]: 1}, {HARD_NEGATIVE_SCENARIOS[0]: 1}, detectors)
    report = generator.build_report(payload, None).lower()

    for banned in ("guaranteed", "proven", "100% secure", "perfect detection", "zero fraud risk"):
        assert banned not in report, f"report contains overclaiming language: {banned!r}"
