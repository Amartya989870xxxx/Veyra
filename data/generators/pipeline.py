"""End-to-end dataset pipeline generator for Veyra v2 (Phase 2).

Generates multi-merchant synthetic datasets with temporal train/validation/test splits,
injected scenarios, and window labels lifted on the 60s scoring grid.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Sequence

from app.schemas.enums import SplitName, WindowLabel
from app.windows import WindowSize
from data.generators.injection import inject_scenario_into_timeline
from data.generators.lifting import ScoredWindowLabel, lift_labels_to_windows
from data.generators.population import MerchantProfile, generate_merchant_population
from data.generators.recipes import SCENARIO_RECIPES
from data.generators.timeline import AnnotatedTransaction, generate_organic_timeline


ATTACK_SCENARIOS: tuple[str, ...] = (
    "card_testing_burst",
    "bin_enumeration_attack",
    "device_farm_ring",
    "promo_coupon_harvesting",
    "ring_under_flash_sale",
    "slow_ramp_infiltration",
    "low_volume_relationship_anomaly",
    "card_testing_low_value",
)
"""Scenarios whose injected transactions carry ``is_abusive=True``."""

HARD_NEGATIVE_SCENARIOS: tuple[str, ...] = (
    "flash_sale_spike",
    "gateway_retry_storm",
    "subscription_renewal_batch",
)
"""Legitimate high-volume surges. These are the scenarios a volume-only detector is
supposed to get wrong; an evaluation that does not contain them cannot measure the only
false-positive number that matters (ADR-003)."""

_MAX_SCENARIO_DURATION_MIN = 90
"""Longest scenario span (slow_ramp_infiltration runs 60m), plus headroom. Injections are
scheduled at least this far before a split boundary so an incident started in TRAIN
cannot bleed into VALIDATION — chronological split integrity has to hold at the
transaction level, not just at the window level."""


@dataclass(frozen=True, slots=True)
class InjectedEpisode:
    """One scheduled scenario injection, recorded as ground truth for coverage counting.

    Counting incidents by grouping window labels after the fact is guesswork: two
    injections of the same scenario close together look like one, and a low-intensity
    injection that never crossed the labelling threshold looks like none. The schedule is
    the truth, so it is recorded when it is created.
    """

    merchant_id: str
    scenario_id: str
    start_time: datetime
    intensity: float
    is_attack: bool


@dataclass
class SyntheticDataset:
    merchants: list[MerchantProfile]
    transactions: list[AnnotatedTransaction]
    window_labels: list[ScoredWindowLabel]
    train_split_end: datetime
    val_split_end: datetime
    test_split_end: datetime
    injected_episodes: list[InjectedEpisode] = field(default_factory=list)

    def split_for_timestamp(self, ts: datetime) -> SplitName:
        if ts < self.train_split_end:
            return SplitName.TRAIN
        if ts < self.val_split_end:
            return SplitName.VALIDATION
        return SplitName.TEST

    def episodes_in_split(self, split: SplitName) -> list[InjectedEpisode]:
        return [e for e in self.injected_episodes if self.split_for_timestamp(e.start_time) is split]


def _plan_split_schedule(
    rng: random.Random,
    split_bounds: list[tuple[datetime, datetime]],
    injections_per_split: int,
    hard_negative_ratio: float,
) -> list[tuple[str, datetime, float]]:
    """Plan ``(scenario_id, start_time, intensity)`` injections for one merchant.

    Scenario *type* is scheduled round-robin so every split is guaranteed to contain
    both attack and hard-negative episodes — the previous uniform-random draw across the
    whole timeline is what left TEST with one attack and zero hard negatives, which makes
    a false-positive rate unmeasurable rather than merely noisy.

    Coverage is the only thing made deterministic. Timing, intensity, duration, entity
    choice, failure draws and volume all stay random, so scheduling a type does not hand
    the model a fingerprint to learn: knowing that a flash sale exists somewhere in TEST
    tells a detector nothing about which window it is in or what it looks like.
    """
    attack_cycle = list(ATTACK_SCENARIOS)
    negative_cycle = list(HARD_NEGATIVE_SCENARIOS)
    rng.shuffle(attack_cycle)
    rng.shuffle(negative_cycle)

    plan: list[tuple[str, datetime, float]] = []
    a_i = n_i = 0

    for split_start, split_end in split_bounds:
        latest_start = split_end - timedelta(minutes=_MAX_SCENARIO_DURATION_MIN)
        if latest_start <= split_start:
            # Split too short to hold a contained episode; skip rather than let one
            # bleed across the boundary.
            continue

        n_negative = max(1, round(injections_per_split * hard_negative_ratio))
        n_attack = max(1, injections_per_split - n_negative)

        for _ in range(n_attack):
            scenario = attack_cycle[a_i % len(attack_cycle)]
            a_i += 1
            plan.append((scenario, _random_time_between(rng, split_start, latest_start), rng.uniform(0.5, 1.6)))

        for _ in range(n_negative):
            scenario = negative_cycle[n_i % len(negative_cycle)]
            n_i += 1
            plan.append((scenario, _random_time_between(rng, split_start, latest_start), rng.uniform(0.6, 1.5)))

    plan.sort(key=lambda item: item[1])
    return plan


def _random_time_between(rng: random.Random, start: datetime, end: datetime) -> datetime:
    span_seconds = max(1.0, (end - start).total_seconds())
    return start + timedelta(seconds=rng.uniform(0.0, span_seconds))


def generate_benchmark_dataset(
    n_merchants: int = 5,
    days: int = 7,
    start_date: datetime | None = None,
    inject_scenarios: bool = True,
    seed: int = 42,
    injections_per_split_per_merchant: int | None = None,
    hard_negative_ratio: float = 0.40,
) -> SyntheticDataset:
    """Generate complete synthetic benchmark dataset with temporal splits.

    ``injections_per_split_per_merchant``: when set, scenarios are scheduled *per split*
    (TRAIN/VALIDATION/TEST each receive this many per merchant, mixed attack and
    hard-negative per ``hard_negative_ratio``) instead of being scattered uniformly at
    random across the whole timeline. Leaving it ``None`` preserves the original
    behaviour exactly.
    """
    rng = random.Random(seed)
    start_ts = start_date or datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)
    total_duration = timedelta(days=days)

    # 60% Train, 20% Validation, 20% Test temporal split
    train_seconds = int(total_duration.total_seconds() * 0.60)
    val_seconds = int(total_duration.total_seconds() * 0.20)

    train_duration = timedelta(seconds=train_seconds)
    val_duration = timedelta(seconds=val_seconds)

    train_split_end = start_ts + train_duration
    val_split_end = train_split_end + val_duration
    test_split_end = start_ts + total_duration

    profiles = generate_merchant_population(n_merchants=n_merchants, seed=seed)
    all_transactions: list[AnnotatedTransaction] = []
    all_window_labels: list[ScoredWindowLabel] = []
    injected_episodes: list[InjectedEpisode] = []

    available_scenarios = list(SCENARIO_RECIPES.keys())
    split_bounds = [
        (start_ts, train_split_end),
        (train_split_end, val_split_end),
        (val_split_end, test_split_end),
    ]

    for p_idx, profile in enumerate(profiles):
        # 1. Generate base organic timeline
        base_txns = generate_organic_timeline(
            profile=profile,
            start_time=start_ts,
            duration=total_duration,
            seed=seed + p_idx * 101,
        )

        merchant_txns = base_txns

        # 2. Inject scenarios if enabled
        if inject_scenarios:
            if injections_per_split_per_merchant is not None:
                plan = _plan_split_schedule(
                    rng=rng,
                    split_bounds=split_bounds,
                    injections_per_split=injections_per_split_per_merchant,
                    hard_negative_ratio=hard_negative_ratio,
                )
            else:
                # Original behaviour: 2-4 injections scattered across the whole timeline.
                plan = []
                for _ in range(rng.randint(2, 4)):
                    scenario_id = rng.choice(available_scenarios)
                    offset_hours = rng.uniform(4.0, (days * 24.0) - 4.0)
                    plan.append((scenario_id, start_ts + timedelta(hours=offset_hours), rng.uniform(0.6, 1.5)))

            for inj_i, (scenario_id, inj_time, intensity) in enumerate(plan):
                merchant_txns = inject_scenario_into_timeline(
                    profile=profile,
                    base_transactions=merchant_txns,
                    scenario_id=scenario_id,
                    start_time=inj_time,
                    intensity=intensity,
                    seed=seed + p_idx * 1000 + inj_i,
                )
                injected_episodes.append(
                    InjectedEpisode(
                        merchant_id=profile.merchant.merchant_id,
                        scenario_id=scenario_id,
                        start_time=inj_time,
                        intensity=intensity,
                        is_attack=scenario_id in ATTACK_SCENARIOS,
                    )
                )

        # 3. Lift labels to windows
        labels = lift_labels_to_windows(
            transactions=merchant_txns,
            merchant_id=profile.merchant.merchant_id,
            window_sizes=(WindowSize.M1, WindowSize.M5, WindowSize.M15, WindowSize.H1),
        )

        all_transactions.extend(merchant_txns)
        all_window_labels.extend(labels)

    all_transactions.sort(key=lambda t: t.attempt.timestamp)

    return SyntheticDataset(
        merchants=profiles,
        transactions=all_transactions,
        window_labels=all_window_labels,
        train_split_end=train_split_end,
        val_split_end=val_split_end,
        test_split_end=test_split_end,
        injected_episodes=injected_episodes,
    )
