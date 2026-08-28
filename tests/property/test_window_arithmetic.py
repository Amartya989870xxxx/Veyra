"""Invariants on the 60s scoring grid.

These are the three invariants named in `docs/ROADMAP.md` §1.2. They are property tests
rather than examples because the failures they guard against — an event counted twice, a
window reaching one second into its own future — do not raise. They produce a number
that is wrong by an amount no report will ever show.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from app.windows import (
    GRID_SECONDS,
    WindowSize,
    align_to_grid,
    contains,
    disjoint_cover,
    grid_points,
    is_aligned,
    window_ends_covering,
    window_start,
)

# A year-wide band of instants. Wide enough that DST-free UTC arithmetic and epoch
# alignment are both exercised, narrow enough that shrinking stays readable.
INSTANTS = st.datetimes(
    min_value=datetime(2026, 1, 1),
    max_value=datetime(2026, 12, 31, 23, 59, 59),
).map(lambda d: d.replace(tzinfo=UTC))

SIZES = st.sampled_from(list(WindowSize))


@given(ts=INSTANTS)
def test_alignment_is_idempotent(ts: datetime) -> None:
    """Aligning an aligned instant is a no-op.

    Without this, a window end would depend on how many times a value happened to pass
    through the pipeline — the same event landing in different windows on different code
    paths.
    """
    once = align_to_grid(ts)
    assert align_to_grid(once) == once
    assert is_aligned(once)


@given(ts=INSTANTS)
def test_alignment_floors_within_one_grid_step(ts: datetime) -> None:
    aligned = align_to_grid(ts)
    assert aligned <= ts
    assert ts - aligned < timedelta(seconds=GRID_SECONDS)


@given(ts=INSTANTS, size=SIZES)
def test_window_never_sees_its_own_future(ts: datetime, size: WindowSize) -> None:
    """The past-only rule (brief §11), as arithmetic.

    An event exactly at ``window_end`` belongs to the next window. If it belonged to
    this one, every feature would carry one grid step of hindsight — invisible in a
    report, fatal in production.
    """
    end = align_to_grid(ts)
    assert not contains(end, size, end)
    assert not contains(end, size, end + timedelta(microseconds=1))
    assert contains(end, size, end - timedelta(microseconds=1))
    assert contains(end, size, window_start(end, size))


@given(ts=INSTANTS, size=SIZES)
def test_covering_windows_are_exactly_those_that_contain(ts: datetime, size: WindowSize) -> None:
    """``window_ends_covering`` agrees with ``contains``, in both directions.

    These are the two sides of the aggregator: one decides where an arriving event is
    written, the other decides what a window reads back. If they disagree, events are
    dropped or double counted, and long windows quietly under-count — a bug that
    presents as "the model just prefers short windows".
    """
    covering = window_ends_covering(ts, size)
    assert len(covering) == size.grid_steps
    assert len(set(covering)) == len(covering)
    for end in covering:
        assert is_aligned(end)
        assert contains(end, size, ts)

    # And no neighbouring grid window outside the returned set contains it.
    lo, hi = min(covering), max(covering)
    for step in range(1, 3):
        assert not contains(lo - timedelta(seconds=GRID_SECONDS * step), size, ts)
        assert not contains(hi + timedelta(seconds=GRID_SECONDS * step), size, ts)


@given(
    ts=INSTANTS,
    size=SIZES,
    offsets=st.lists(st.integers(min_value=0, max_value=3599), min_size=0, max_size=120),
)
def test_additivity_1m_tiles_the_larger_window(
    ts: datetime, size: WindowSize, offsets: list[int]
) -> None:
    """A window contains exactly what its 1m tiles contain — no gap, no double count.

    This is the invariant that makes multi-window fusion meaningful. If a 1h window and
    its sixty 1m windows disagree on how many events occurred, then every cross-window
    comparison the model makes is comparing two different realities.
    """
    end = align_to_grid(ts)
    events = [end - timedelta(seconds=off) for off in offsets]

    whole = [e for e in events if contains(end, size, e)]

    tiles = disjoint_cover(end, size)
    assert len(tiles) == size.grid_steps

    # Count how many tiles claim each event, by position rather than by value — the
    # same instant can legitimately appear twice in `events`.
    claims = [sum(contains(t, WindowSize.M1, e) for t in tiles) for e in events]
    tiled = [e for e, n in zip(events, claims, strict=True) if n]

    assert sorted(tiled) == sorted(whole), "tiles and whole window disagree on membership"
    assert all(n <= 1 for n in claims), "an event was claimed by more than one 1m tile"
    assert all(n == 1 for e, n in zip(events, claims, strict=True) if contains(end, size, e)), (
        "an event inside the window was claimed by no tile"
    )


@given(ts=INSTANTS, minutes=st.integers(min_value=0, max_value=180))
def test_grid_points_are_aligned_ascending_and_half_open(ts: datetime, minutes: int) -> None:
    """Scoring instants tile the evaluation period without repeating an instant."""
    start = align_to_grid(ts)
    end = start + timedelta(minutes=minutes)
    points = list(grid_points(start, end))

    assert len(points) == minutes
    assert all(is_aligned(p) for p in points)
    assert points == sorted(points)
    assert all(start <= p < end for p in points)


@given(ts=INSTANTS, size=SIZES)
def test_window_length_is_exactly_the_declared_size(ts: datetime, size: WindowSize) -> None:
    end = align_to_grid(ts)
    assert end - window_start(end, size) == size.delta
    assert size.grid_steps * GRID_SECONDS == size.seconds


@given(ts=INSTANTS)
def test_naive_datetimes_are_rejected(ts: datetime) -> None:
    """A naive timestamp compares wrong against an aware one without raising.

    That is the same class of silent corruption these tests exist to prevent, so it is
    refused at the boundary rather than coerced.
    """
    naive = ts.replace(tzinfo=None)
    assume(naive.tzinfo is None)
    with pytest.raises(ValueError):
        align_to_grid(naive)
