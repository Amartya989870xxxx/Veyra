"""Record types emitted by the synthetic generator.

These are plain dataclasses rather than Pydantic models: the generator produces millions
of small objects and validation happens once, at the ingestion boundary, where it belongs.
``to_transaction_payload`` produces exactly the canonical API shape so the same rows can be
replayed through ``POST /api/v1/events`` unchanged.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from data.generators.catalog import Catalog


@dataclass
class GenSession:
    session_id: str
    customer_id: str
    agent_id: str | None
    actor_type: str
    device_id: str
    network_fingerprint: str
    started_at: datetime
    ended_at: datetime | None = None


@dataclass
class GenAction:
    action_id: str
    agent_id: str
    session_id: str
    sequence_number: int
    action_type: str
    tool_name: str | None
    timestamp: datetime
    merchant_id: str | None = None
    sku_id: str | None = None


@dataclass
class GenDelegation:
    delegation_id: str
    customer_id: str
    agent_id: str
    purpose: str
    max_amount: float
    currency: str
    allowed_categories: list[str]
    forbidden_categories: list[str]
    allowed_merchants: list[str]
    merchant_policy: str
    approval_required_above: float | None
    issued_at: datetime
    expires_at: datetime


@dataclass
class GenTransaction:
    transaction_id: str
    merchant_id: str
    customer_id: str
    agent_id: str | None
    session_id: str | None
    delegation_id: str | None
    amount: float
    currency: str
    merchant_category: str
    sku_id: str | None
    quantity: int
    coupon_id: str | None
    coupon_value: float
    device_id: str
    network_fingerprint: str
    payment_method: str
    instrument_fingerprint: str
    retry_count: int
    status: str
    actor_type: str
    timestamp: datetime

    # --- ground truth; never visible to any detector at inference time ---------------
    label_class: str = "LEGIT_HUMAN"
    is_abusive: bool = False
    scenario: str = "unknown"
    group_id: str = "grp_unknown"
    campaign_id: str | None = None
    hard_negative: bool = False


@dataclass
class Episode:
    """One coherent slice of activity that must never be split across train and test."""

    group_id: str
    scenario: str
    label_class: str
    hard_negative: bool
    campaign_id: str | None = None
    transactions: list[GenTransaction] = field(default_factory=list)
    actions: list[GenAction] = field(default_factory=list)
    sessions: list[GenSession] = field(default_factory=list)
    delegations: list[GenDelegation] = field(default_factory=list)
    customers: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    devices: list[str] = field(default_factory=list)
    networks: list[str] = field(default_factory=list)


class IdAllocator:
    """Monotonic, zero-padded ID minting. Deterministic given call order."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}

    def next(self, prefix: str, width: int = 6) -> str:
        n = self._counters.get(prefix, 0)
        self._counters[prefix] = n + 1
        return f"{prefix}_{n:0{width}d}"

    def next_many(self, prefix: str, count: int, width: int = 6) -> list[str]:
        return [self.next(prefix, width) for _ in range(count)]


@dataclass
class EpisodeContext:
    """Everything a scenario builder needs. One per episode, with its own seeded RNG."""

    rng: random.Random
    catalog: Catalog
    ids: IdAllocator
    start: datetime
    horizon: timedelta

    def when(self) -> datetime:
        """A uniformly random moment inside the benchmark window."""
        seconds = self.rng.uniform(0, self.horizon.total_seconds())
        return self.start + timedelta(seconds=seconds)

    def business_hours(self, base: datetime) -> datetime:
        """Nudge a timestamp toward waking hours; humans mostly do not shop at 04:00."""
        return self._with_hour(base, self.rng.gauss(14, 4), low=6, high=23)

    def diurnal(self, spread: float = 5.5) -> datetime:
        """A timestamp shaped by the same daily traffic curve, with a wider tail.

        Abusive traffic is shaped diurnally too — it runs when merchant traffic is heavy
        precisely in order to blend in. Leaving abuse uniform across 24h while legitimate
        traffic clustered around midday made hour-of-day a strong artificial giveaway
        (single-feature ROC-AUC 0.75) that had nothing to do with the behaviour we mean to
        detect. The wider spread keeps a weak, genuine night skew.
        """
        return self._with_hour(self.when(), self.rng.gauss(14, spread), low=0, high=23)

    def _with_hour(self, base: datetime, hour: float, low: int, high: int) -> datetime:
        clamped = int(min(high, max(low, hour)))
        return base.replace(
            hour=clamped, minute=self.rng.randrange(60), second=self.rng.randrange(60)
        )


def dump_record(record) -> dict:
    """Dataclass -> JSON-ready dict with ISO timestamps."""
    out = asdict(record)
    for key, value in out.items():
        if isinstance(value, datetime):
            out[key] = value.isoformat()
    return out
