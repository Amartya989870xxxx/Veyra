"""Window arithmetic on the 60-second scoring grid.

ADR-001 makes ``(merchant_id, window_size, window_end)`` the scored unit; ADR-002 fixes
the window set at 1m/5m/15m/1h and the scoring cadence at 60s. Every store, feature,
label and metric in the system is keyed by that tuple, which makes the arithmetic that
produces it load-bearing in an unusually quiet way: an off-by-one here does not raise,
it silently shifts which events a window can see, and every number downstream is wrong
by an amount nobody can see in a report.

That is why this lives in its own module with property tests rather than being inlined
into the aggregator.

**Windows are half-open:** ``[window_end - size, window_end)``. An event exactly at
``window_end`` belongs to the *next* window, never this one. This is the past-only rule
(brief §11) expressed as arithmetic instead of as a convention — a window physically
cannot contain an event from its own future.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from enum import StrEnum

GRID_SECONDS = 60
"""Scoring cadence. Every window end is a multiple of this from the epoch.

ADR-002 picks 60s because detection latency is reported as ``first_flag - incident_start``
and a coarser grid would quantise that measurement into uselessness.
"""


class WindowSize(StrEnum):
    """The four detection horizons.

    24h is deliberately absent: ADR-002 rules it a *baseline* window, not a detection
    window, because an alert whose evidence needs a full day to accumulate is a
    post-mortem. Including it here would let it leak into detection metrics and inflate
    recall with findings no merchant could act on.
    """

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"

    @property
    def seconds(self) -> int:
        return _WINDOW_SECONDS[self]

    @property
    def delta(self) -> timedelta:
        return timedelta(seconds=self.seconds)

    @property
    def grid_steps(self) -> int:
        """How many 60s grid steps this window spans."""
        return self.seconds // GRID_SECONDS


_WINDOW_SECONDS: dict[WindowSize, int] = {
    WindowSize.M1: 60,
    WindowSize.M5: 300,
    WindowSize.M15: 900,
    WindowSize.H1: 3600,
}

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _require_aware(ts: datetime, name: str) -> datetime:
    """Reject naive datetimes at the boundary.

    A naive timestamp compares wrong against an aware one without raising, which is the
    same class of silent corruption this module exists to prevent.
    """
    if ts.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return ts.astimezone(UTC)


def align_to_grid(ts: datetime) -> datetime:
    """Floor ``ts`` to the 60s scoring grid.

    Idempotent: aligning an aligned timestamp is a no-op, which the property suite
    asserts because a non-idempotent floor would make window ends depend on how many
    times a value had been passed through the pipeline.
    """
    ts = _require_aware(ts, "ts")
    elapsed = int((ts - _EPOCH).total_seconds())
    return _EPOCH + timedelta(seconds=elapsed - elapsed % GRID_SECONDS)


def is_aligned(ts: datetime) -> bool:
    return align_to_grid(ts) == _require_aware(ts, "ts")


def window_start(window_end: datetime, size: WindowSize) -> datetime:
    """The inclusive lower bound of the window ending at ``window_end``."""
    return _require_aware(window_end, "window_end") - size.delta


def contains(window_end: datetime, size: WindowSize, ts: datetime) -> bool:
    """Is ``ts`` inside ``[window_end - size, window_end)``?

    The strict upper bound is the past-only rule. Everything that decides which events
    feed a feature vector routes through here, so the rule is enforced in exactly one
    place rather than re-implemented per aggregate.
    """
    window_end = _require_aware(window_end, "window_end")
    ts = _require_aware(ts, "ts")
    return window_start(window_end, size) <= ts < window_end


def window_ends_covering(ts: datetime, size: WindowSize) -> list[datetime]:
    """Every grid-aligned window end of ``size`` whose window contains ``ts``.

    An event is not the property of one window. On the 60s grid a 1m window sees it
    once, but a 15m window sees it fifteen times at fifteen different window ends. The
    aggregator needs all of them, and getting this wrong under-counts long windows —
    a bug that looks like "the model just prefers short windows".
    """
    ts = _require_aware(ts, "ts")
    first = align_to_grid(ts) + timedelta(seconds=GRID_SECONDS)
    return [first + timedelta(seconds=GRID_SECONDS * i) for i in range(size.grid_steps)]


def grid_points(start: datetime, end: datetime) -> Iterator[datetime]:
    """Grid-aligned scoring instants in ``[start, end)``, ascending.

    Used to drive an evaluation run: every point produced here is scored for every
    window size, which is what makes latency measurable at 60s resolution.
    """
    cursor = align_to_grid(start)
    if cursor < _require_aware(start, "start"):
        cursor += timedelta(seconds=GRID_SECONDS)
    end = _require_aware(end, "end")
    while cursor < end:
        yield cursor
        cursor += timedelta(seconds=GRID_SECONDS)


def disjoint_cover(window_end: datetime, size: WindowSize) -> list[datetime]:
    """The 1m window ends that exactly tile the window ending at ``window_end``.

    Exists so the additivity invariant is checkable: a 1h window must contain precisely
    what its sixty constituent 1m windows contain, with no gap and no double count.
    """
    window_end = _require_aware(window_end, "window_end")
    return [
        window_end - timedelta(seconds=GRID_SECONDS * i)
        for i in range(size.grid_steps - 1, -1, -1)
    ]
