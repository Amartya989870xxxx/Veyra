"""Bounded, in-process store for recent `/v2/demo/simulate` runs (Part 2 & 2A).

Purpose: let `GET /v2/demo/runs/{run_id}/*` page through the exact synthetic
transaction stream and feature vector behind a specific demo verdict, without:

- persisting arbitrary demo volume into the real database (`raw_events`, `incident_store`),
- committing any generated dataset to disk or git, or
- retaining runs forever.

Retention policy (Part 2A, option A: short-lived in-memory run store with bounded
retention): at most `Settings.demo_run_store_max_runs` runs (default 20), evicted
oldest-first once exceeded, and every run additionally expires after
`Settings.demo_run_store_ttl_seconds` (default 1800s / 30 minutes) regardless of count.
This is the same bounded-in-process pattern as `app/core/redis_client.LocalWindowStore`,
for the same reason stated there: a single process must never accumulate unbounded state
and then present it as if it were durable.

A demo run's own transaction list is already small — bounded by its window size (at most
1h of one synthetic merchant's traffic, realistically hundreds to a few thousand rows) —
so holding up to `max_runs` of them in memory is itself bounded, not just TTL'd.

Ownership: every run is tagged with the principal_id that created it. Reading another
principal's run returns "not found", not "forbidden" — the same 404-not-403 choice
`app/api/v2/incidents.py` makes, so a run_id cannot be used to probe whether a given
principal generated a demo recently.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.auth import AuthenticatedPrincipal, UserRole
from app.core.config import get_settings
from app.features.engine import WindowFeatureVector
from app.windows import WindowSize
from data.generators.timeline import AnnotatedTransaction


@dataclass
class DemoRunRecord:
    run_id: str
    created_by: str
    created_at: datetime
    scenario_id: str
    merchant_category: str
    merchant_id: str
    window_size: WindowSize
    window_end: datetime
    transactions: list[AnnotatedTransaction]
    feature_vector: WindowFeatureVector
    entity_graph_payload: dict[str, Any]
    risk_score: float
    action_tier: str
    abusive_count: int
    is_labelled_attack: bool
    _stored_at: float = field(default_factory=time.monotonic, repr=False)


class DemoRunStore:
    def __init__(self, max_runs: int | None = None, ttl_seconds: int | None = None) -> None:
        settings = get_settings()
        self.max_runs = max_runs if max_runs is not None else settings.demo_run_store_max_runs
        self.ttl_seconds = (
            ttl_seconds if ttl_seconds is not None else settings.demo_run_store_ttl_seconds
        )
        self._lock = threading.Lock()
        self._runs: OrderedDict[str, DemoRunRecord] = OrderedDict()

    def _evict_locked(self) -> None:
        now = time.monotonic()
        expired = [
            rid for rid, rec in self._runs.items() if now - rec._stored_at > self.ttl_seconds
        ]
        for rid in expired:
            self._runs.pop(rid, None)
        while len(self._runs) > self.max_runs:
            self._runs.popitem(last=False)

    def put(self, record: DemoRunRecord) -> None:
        with self._lock:
            self._evict_locked()
            self._runs[record.run_id] = record
            self._runs.move_to_end(record.run_id)

    def get(self, run_id: str, principal: AuthenticatedPrincipal) -> DemoRunRecord | None:
        """Return the run if it exists, hasn't expired, and belongs to `principal`
        (or the caller holds a `system_service` credential). Otherwise `None` — callers
        should surface this as a 404, never a 403, so a run_id can't be used to probe
        another principal's demo activity."""
        with self._lock:
            self._evict_locked()
            record = self._runs.get(run_id)
        if record is None:
            return None
        if principal.role == UserRole.SYSTEM_SERVICE or principal.is_demo_bypass:
            return record
        if record.created_by != principal.principal_id:
            return None
        return record

    def __len__(self) -> int:
        with self._lock:
            self._evict_locked()
            return len(self._runs)


_singleton: DemoRunStore | None = None
_singleton_lock = threading.Lock()


def get_demo_run_store() -> DemoRunStore:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = DemoRunStore()
    return _singleton


def reset_demo_run_store() -> None:
    """Test-only: clear the singleton's contents without changing its configuration."""
    global _singleton
    with _singleton_lock:
        _singleton = None
