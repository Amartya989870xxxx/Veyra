"""Scenario coverage accounting for evaluation splits.

The rule this module exists to enforce: **a metric may only be reported for a scenario
that is actually present in the split it is reported on.** A previous version of the
benchmark report substituted a hardcoded list of three hard-negative scenario names and
printed "0 false positives" for each whenever no hard-negative data existed at all —
reporting that nothing happened as though detection had succeeded.

Coverage is computed from ``SyntheticDataset.injected_episodes`` (the generator's own
schedule, i.e. ground truth about what was injected) cross-checked against the lifted
window labels (what the labelling rule actually produced). Both numbers matter and they
are not the same thing: an episode that was injected but never crossed the labelling
threshold is a real event that produced no positive window, and a report that silently
counts it as evaluated coverage would be overstating the evidence.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from app.schemas.enums import SplitName, WindowLabel
from data.generators.pipeline import SyntheticDataset

NOT_EVALUATED = "NOT PRESENT — NOT EVALUATED"
"""The only permitted output for a scenario absent from a split. Never print 0."""


@dataclass(frozen=True, slots=True)
class SplitCoverage:
    split: SplitName
    fraud_episodes: int
    hard_negative_episodes: int
    fraud_episodes_by_scenario: dict[str, int]
    hard_negative_episodes_by_scenario: dict[str, int]
    fraud_windows: int
    legit_spike_windows: int
    normal_windows: int
    windows_by_scenario: dict[str, int] = field(default_factory=dict)

    @property
    def total_windows(self) -> int:
        return self.fraud_windows + self.legit_spike_windows + self.normal_windows

    def is_scenario_present(self, scenario_id: str) -> bool:
        """Present means: injected in this split AND it produced labelled windows."""
        injected = (
            self.fraud_episodes_by_scenario.get(scenario_id, 0)
            + self.hard_negative_episodes_by_scenario.get(scenario_id, 0)
        )
        return injected > 0 and self.windows_by_scenario.get(scenario_id, 0) > 0


@dataclass(frozen=True, slots=True)
class DatasetCoverage:
    by_split: dict[SplitName, SplitCoverage]

    def get(self, split: SplitName) -> SplitCoverage:
        return self.by_split[split]

    def scenario_or_not_evaluated(self, split: SplitName, scenario_id: str, value: object) -> object:
        """Return ``value`` only if the scenario exists in the split, else NOT_EVALUATED."""
        if self.by_split[split].is_scenario_present(scenario_id):
            return value
        return NOT_EVALUATED


def compute_dataset_coverage(dataset: SyntheticDataset) -> DatasetCoverage:
    """Count injected episodes and lifted windows per split, broken down by scenario."""
    by_split: dict[SplitName, SplitCoverage] = {}

    for split in (SplitName.TRAIN, SplitName.VALIDATION, SplitName.TEST):
        episodes = dataset.episodes_in_split(split)
        fraud_by_scenario: dict[str, int] = defaultdict(int)
        negative_by_scenario: dict[str, int] = defaultdict(int)
        for ep in episodes:
            if ep.is_attack:
                fraud_by_scenario[ep.scenario_id] += 1
            else:
                negative_by_scenario[ep.scenario_id] += 1

        fraud_windows = legit_windows = normal_windows = 0
        windows_by_scenario: dict[str, int] = defaultdict(int)
        for w in dataset.window_labels:
            if dataset.split_for_timestamp(w.window_end) is not split:
                continue
            if w.label is WindowLabel.FRAUD_SPIKE:
                fraud_windows += 1
            elif w.label is WindowLabel.LEGIT_SPIKE:
                legit_windows += 1
            else:
                normal_windows += 1
            if w.dominant_scenario_id and w.dominant_scenario_id != "normal_day":
                windows_by_scenario[w.dominant_scenario_id] += 1

        by_split[split] = SplitCoverage(
            split=split,
            fraud_episodes=sum(fraud_by_scenario.values()),
            hard_negative_episodes=sum(negative_by_scenario.values()),
            fraud_episodes_by_scenario=dict(fraud_by_scenario),
            hard_negative_episodes_by_scenario=dict(negative_by_scenario),
            fraud_windows=fraud_windows,
            legit_spike_windows=legit_windows,
            normal_windows=normal_windows,
            windows_by_scenario=dict(windows_by_scenario),
        )

    return DatasetCoverage(by_split=by_split)


def format_coverage_report(coverage: DatasetCoverage) -> str:
    """Human-readable split/scenario coverage block for the benchmark report."""
    lines: list[str] = []
    for split in (SplitName.TRAIN, SplitName.VALIDATION, SplitName.TEST):
        c = coverage.get(split)
        lines.append(f"{split.value.upper()}:")
        lines.append(f"  fraud incidents (injected episodes):         {c.fraud_episodes}")
        lines.append(f"  hard-negative incidents (injected episodes): {c.hard_negative_episodes}")
        lines.append(
            f"  windows: {c.total_windows:,} "
            f"(FRAUD_SPIKE {c.fraud_windows:,} / LEGIT_SPIKE {c.legit_spike_windows:,} / NORMAL {c.normal_windows:,})"
        )
        lines.append("")
    return "\n".join(lines)
