"""Tests for scenario coverage accounting and the no-fabrication rule.

The failure these guard against is specific and already happened once: the benchmark
report substituted a hardcoded list of hard-negative scenario names and printed "0 false
positives" for each when the TEST split contained none of them, turning "we never tested
this" into "we tested this and passed". Coverage must be counted from what the generator
actually injected, and an absent scenario must be reported as NOT EVALUATED, never 0.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.evaluation.coverage import (
    NOT_EVALUATED,
    compute_dataset_coverage,
    format_coverage_report,
)
from app.schemas.enums import SplitName
from data.generators.pipeline import (
    ATTACK_SCENARIOS,
    HARD_NEGATIVE_SCENARIOS,
    generate_benchmark_dataset,
)

START = datetime(2026, 3, 1, tzinfo=UTC)


@pytest.fixture(scope="module")
def scheduled_dataset():
    """Small split-scheduled dataset — the Phase 2 configuration in miniature."""
    return generate_benchmark_dataset(
        n_merchants=2,
        days=4,
        start_date=START,
        inject_scenarios=True,
        seed=42,
        injections_per_split_per_merchant=2,
        hard_negative_ratio=0.5,
    )


def test_every_split_receives_both_attack_and_hard_negative_episodes(scheduled_dataset):
    """The whole point of split-aware scheduling: TEST cannot end up with zero of either."""
    coverage = compute_dataset_coverage(scheduled_dataset)
    for split in (SplitName.TRAIN, SplitName.VALIDATION, SplitName.TEST):
        c = coverage.get(split)
        assert c.fraud_episodes > 0, f"{split} has no fraud episodes"
        assert c.hard_negative_episodes > 0, f"{split} has no hard-negative episodes"


def test_test_split_has_multiple_independent_incidents(scheduled_dataset):
    """Guards the exact defect this pass exists to fix: TEST previously held one incident."""
    test_cov = compute_dataset_coverage(scheduled_dataset).get(SplitName.TEST)
    assert test_cov.fraud_episodes >= 2
    assert test_cov.hard_negative_episodes >= 2


def test_absent_scenario_reports_not_evaluated_never_zero(scheduled_dataset):
    coverage = compute_dataset_coverage(scheduled_dataset)
    result = coverage.scenario_or_not_evaluated(
        SplitName.TEST, "a_scenario_that_was_never_injected", 0
    )
    assert result == NOT_EVALUATED
    assert result != 0


def test_present_scenario_reports_its_real_value(scheduled_dataset):
    coverage = compute_dataset_coverage(scheduled_dataset)
    test_cov = coverage.get(SplitName.TEST)
    present = [s for s in test_cov.windows_by_scenario if test_cov.is_scenario_present(s)]
    assert present, "fixture should contain at least one present scenario"
    assert coverage.scenario_or_not_evaluated(SplitName.TEST, present[0], 7) == 7


def test_scenario_presence_requires_both_injection_and_labelled_windows(scheduled_dataset):
    """An episode injected but never crossing the labelling threshold is not coverage.

    Presence is the conjunction of "was injected" and "produced labelled windows" — a
    scenario that was scheduled but produced nothing measurable must not be counted as
    evaluated, because no metric computed over it would mean anything.
    """
    test_cov = compute_dataset_coverage(scheduled_dataset).get(SplitName.TEST)
    injected = set(test_cov.fraud_episodes_by_scenario) | set(test_cov.hard_negative_episodes_by_scenario)

    for scenario in injected:
        if test_cov.windows_by_scenario.get(scenario, 0) == 0:
            assert not test_cov.is_scenario_present(scenario)

    for scenario in test_cov.windows_by_scenario:
        if scenario not in injected:
            assert not test_cov.is_scenario_present(scenario)


def test_episode_scenarios_are_drawn_from_the_declared_pools(scheduled_dataset):
    for ep in scheduled_dataset.injected_episodes:
        if ep.is_attack:
            assert ep.scenario_id in ATTACK_SCENARIOS
        else:
            assert ep.scenario_id in HARD_NEGATIVE_SCENARIOS


def test_injected_episodes_do_not_straddle_split_boundaries(scheduled_dataset):
    """Chronological integrity: an episode scheduled in TRAIN must not start so late
    that its transactions land in VALIDATION."""
    ds = scheduled_dataset
    for ep in ds.injected_episodes:
        split = ds.split_for_timestamp(ep.start_time)
        boundary = {
            SplitName.TRAIN: ds.train_split_end,
            SplitName.VALIDATION: ds.val_split_end,
            SplitName.TEST: ds.test_split_end,
        }[split]
        remaining_minutes = (boundary - ep.start_time).total_seconds() / 60.0
        assert remaining_minutes >= 90, (
            f"{ep.scenario_id} starts {remaining_minutes:.0f}min before the {split} boundary; "
            "a long scenario could bleed into the next split"
        )


def test_scheduling_is_deterministic_for_a_fixed_seed():
    kwargs = dict(
        n_merchants=2,
        days=4,
        start_date=START,
        inject_scenarios=True,
        seed=1234,
        injections_per_split_per_merchant=2,
    )
    a = generate_benchmark_dataset(**kwargs)
    b = generate_benchmark_dataset(**kwargs)

    assert [(e.merchant_id, e.scenario_id, e.start_time, e.intensity) for e in a.injected_episodes] == [
        (e.merchant_id, e.scenario_id, e.start_time, e.intensity) for e in b.injected_episodes
    ]
    assert len(a.transactions) == len(b.transactions)


def test_default_scheduling_behaviour_is_unchanged():
    """`injections_per_split_per_merchant=None` must preserve the original generator."""
    ds = generate_benchmark_dataset(
        n_merchants=2, days=4, start_date=START, inject_scenarios=True, seed=42
    )
    assert 2 * 2 <= len(ds.injected_episodes) <= 2 * 4  # 2-4 injections per merchant


def test_format_coverage_report_mentions_every_split(scheduled_dataset):
    text = format_coverage_report(compute_dataset_coverage(scheduled_dataset))
    for split in ("TRAIN", "VALIDATION", "TEST"):
        assert split in text
