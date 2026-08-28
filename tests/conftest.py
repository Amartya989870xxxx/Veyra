"""Shared fixtures.

Two rules this file exists to enforce, both learned from the v1 evaluation:

*Determinism.* Every source of randomness is seeded from one place. A test that fails
one run in fifty is a test the team learns to re-run rather than read.

*No wall-clock dependence.* Nothing under test may call ``datetime.now()``. Time is an
input, passed explicitly, because window arithmetic that silently depends on when the
suite ran is untestable by construction.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

SEED = 20260827
"""One seed for the whole suite. Change it deliberately, never per-test."""


@pytest.fixture
def rng() -> random.Random:
    """A seeded generator. Prefer this over the ``random`` module singleton."""
    return random.Random(SEED)


@pytest.fixture
def now() -> datetime:
    """A fixed, grid-aligned 'current time'.

    Grid-aligned on purpose: an arbitrary instant would make half the window assertions
    accidentally pass or fail on where the second hand happened to be.
    """
    return datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "gate: leakage gate — never skip or weaken to go green")
