"""Scenario stream injection engine (Phase 2.1).

Injects scenarios into an ongoing merchant transaction stream, preserving continuous
temporal ordering and entity sharing without bundle boundaries.
"""

from __future__ import annotations

import random
from datetime import datetime

from data.generators.population import MerchantProfile
from data.generators.recipes import SCENARIO_RECIPES
from data.generators.timeline import AnnotatedTransaction


def inject_scenario_into_timeline(
    profile: MerchantProfile,
    base_transactions: list[AnnotatedTransaction],
    scenario_id: str,
    start_time: datetime,
    intensity: float = 1.0,
    seed: int = 42,
) -> list[AnnotatedTransaction]:
    """Inject scenario transactions into an ongoing merchant stream and sort chronologically."""
    if scenario_id not in SCENARIO_RECIPES:
        raise ValueError(f"Unknown scenario_id: '{scenario_id}'; registered: {sorted(SCENARIO_RECIPES.keys())}")

    rng = random.Random(seed)
    recipe_fn = SCENARIO_RECIPES[scenario_id]

    injected_txns = recipe_fn(
        profile=profile,
        start_time=start_time,
        rng=rng,
        intensity=intensity,
    )

    combined = base_transactions + injected_txns
    # Sort strictly by payment attempt timestamp
    combined.sort(key=lambda t: t.attempt.timestamp)
    return combined
