"""The single risk context that both the live API and the offline evaluator score against.

Two things here are deliberate and load-bearing:

**Past-only windows.** The context builder streams transactions in timestamp order and
maintains running state. A feature can only ever see events strictly before the
transaction being scored. That is what a live system actually has, and it means the first
transaction of a campaign genuinely has no campaign context yet — detection lead time is a
result to be measured, not a leak to be enjoyed.

**One context type, two builders.** The offline evaluator and the online API produce the
same :class:`RiskContext`, so every feature function runs identical code in both. Anything
computed only online (Redis counters) is surfaced as evidence, never as a model feature,
because a feature that exists in production and not in training is a silent skew bug.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

DEFAULT_WINDOW_SECONDS = 900
DEFAULT_MAX_NEIGHBOURS = 400


@dataclass
class TxnView:
    """Normalized, float-valued transaction view used by feature code."""

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
    device_id: str | None
    network_fingerprint: str | None
    payment_method: str
    instrument_fingerprint: str | None
    retry_count: int
    status: str
    actor_type: str
    timestamp: datetime

    def entity_keys(self) -> list[tuple[str, str]]:
        """Typed entity keys used to build the graph and find neighbours."""
        keys: list[tuple[str, str]] = [
            ("CUSTOMER", self.customer_id),
            ("MERCHANT", self.merchant_id),
        ]
        for kind, value in (
            ("AGENT", self.agent_id),
            ("SESSION", self.session_id),
            ("DEVICE", self.device_id),
            ("NETWORK", self.network_fingerprint),
            ("SKU", self.sku_id),
            ("COUPON", self.coupon_id),
            ("INSTRUMENT", self.instrument_fingerprint),
        ):
            if value:
                keys.append((kind, value))
        return keys

    def linking_keys(self) -> list[tuple[str, str]]:
        """Entity keys that make two transactions *related* for neighbourhood purposes.

        Merchant and category are excluded: every transaction at a large merchant would
        otherwise be everyone's neighbour, which makes the neighbourhood meaningless and
        expensive at the same time.
        """
        return [k for k in self.entity_keys() if k[0] not in ("MERCHANT",)]


@dataclass
class ActionView:
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
class DelegationView:
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
class CustomerHistory:
    """Everything known about a customer strictly before the transaction being scored."""

    transaction_count: int = 0
    mean_amount: float = 0.0
    m2_amount: float = 0.0  # Welford's aggregate, for a streaming standard deviation
    max_amount: float = 0.0
    distinct_merchants: int = 0
    distinct_categories: int = 0
    distinct_devices: int = 0
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    failed_count: int = 0

    @property
    def std_amount(self) -> float:
        if self.transaction_count < 2:
            return 0.0
        return math.sqrt(max(0.0, self.m2_amount / (self.transaction_count - 1)))

    @property
    def age_seconds(self) -> float:
        if not self.first_seen or not self.last_seen:
            return 0.0
        return (self.last_seen - self.first_seen).total_seconds()


@dataclass
class AgentHistory:
    transaction_count: int = 0
    session_count: int = 0
    action_count: int = 0
    distinct_customers: int = 0
    distinct_merchants: int = 0
    mean_actions_per_minute: float = 0.0
    mean_amount: float = 0.0
    failed_count: int = 0
    first_seen: datetime | None = None


@dataclass
class RiskContext:
    """Everything the feature engine and risk components are allowed to look at."""

    transaction: TxnView
    now: datetime
    actions: list[ActionView] = field(default_factory=list)
    delegation: DelegationView | None = None
    intent_text: str | None = None
    customer_history: CustomerHistory = field(default_factory=CustomerHistory)
    agent_history: AgentHistory = field(default_factory=AgentHistory)
    neighbourhood: list[TxnView] = field(default_factory=list)
    session_actions_by_session: dict[str, list[ActionView]] = field(default_factory=dict)
    window_seconds: int = DEFAULT_WINDOW_SECONDS
    degraded: list[str] = field(default_factory=list)
    hot_state: dict[str, float] = field(default_factory=dict)
    neighbourhood_truncated: bool = False

    def mark_degraded(self, component: str) -> None:
        if component not in self.degraded:
            self.degraded.append(component)


class StreamingContextBuilder:
    """Maintains past-only state over a chronological transaction stream.

    Used directly by the offline evaluator (one pass over the benchmark) and by the API's
    replay/backfill path. The online request path builds an equivalent context from
    PostgreSQL and Redis instead.
    """

    def __init__(
        self,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
        max_neighbours: int = DEFAULT_MAX_NEIGHBOURS,
    ) -> None:
        self.window_seconds = window_seconds
        self.max_neighbours = max_neighbours
        self._window: deque[TxnView] = deque()
        self._by_entity: dict[tuple[str, str], deque[str]] = defaultdict(deque)
        self._txn_by_id: dict[str, TxnView] = {}
        self._customers: dict[str, CustomerHistory] = {}
        self._customer_sets: dict[str, tuple[set, set, set]] = {}
        self._agents: dict[str, AgentHistory] = {}
        self._agent_sets: dict[str, tuple[set, set, set]] = {}

    # -- window maintenance ----------------------------------------------------------

    def _evict(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.window_seconds)
        while self._window and self._window[0].timestamp < cutoff:
            stale = self._window.popleft()
            self._txn_by_id.pop(stale.transaction_id, None)
            for key in stale.linking_keys():
                bucket = self._by_entity.get(key)
                if bucket:
                    try:
                        bucket.remove(stale.transaction_id)
                    except ValueError:
                        pass
                    if not bucket:
                        self._by_entity.pop(key, None)

    def neighbourhood(self, txn: TxnView) -> tuple[list[TxnView], bool]:
        """Transactions in the window sharing at least one linking entity with ``txn``.

        Bounded: an ego-neighbourhood, not the whole window. A full-window graph per
        transaction would be both slower and less meaningful, since unrelated traffic
        dilutes exactly the cluster structure we want to measure.
        """
        seen: set[str] = set()
        found: list[TxnView] = []
        truncated = False
        for key in txn.linking_keys():
            for txn_id in self._by_entity.get(key, ()):  # noqa: SIM118
                if txn_id in seen:
                    continue
                seen.add(txn_id)
                neighbour = self._txn_by_id.get(txn_id)
                if neighbour is not None:
                    found.append(neighbour)
                    if len(found) >= self.max_neighbours:
                        truncated = True
                        break
            if truncated:
                break
        found.sort(key=lambda t: t.timestamp)
        return found, truncated

    # -- history -------------------------------------------------------------------

    def _customer_history(self, customer_id: str) -> CustomerHistory:
        return self._customers.get(customer_id, CustomerHistory())

    def _agent_history(self, agent_id: str | None) -> AgentHistory:
        if not agent_id:
            return AgentHistory()
        return self._agents.get(agent_id, AgentHistory())

    def observe(self, txn: TxnView, actions: list[ActionView] | None = None) -> None:
        """Fold a transaction into history. Call *after* building its context."""
        self._evict(txn.timestamp)

        hist = self._customers.setdefault(txn.customer_id, CustomerHistory())
        merchants, categories, devices = self._customer_sets.setdefault(
            txn.customer_id, (set(), set(), set())
        )
        merchants.add(txn.merchant_id)
        categories.add(txn.merchant_category)
        if txn.device_id:
            devices.add(txn.device_id)
        hist.transaction_count += 1
        delta = txn.amount - hist.mean_amount
        hist.mean_amount += delta / hist.transaction_count
        hist.m2_amount += delta * (txn.amount - hist.mean_amount)
        hist.max_amount = max(hist.max_amount, txn.amount)
        hist.distinct_merchants = len(merchants)
        hist.distinct_categories = len(categories)
        hist.distinct_devices = len(devices)
        hist.first_seen = hist.first_seen or txn.timestamp
        hist.last_seen = txn.timestamp
        if txn.status == "FAILED":
            hist.failed_count += 1

        if txn.agent_id:
            agent = self._agents.setdefault(txn.agent_id, AgentHistory())
            a_customers, a_merchants, a_sessions = self._agent_sets.setdefault(
                txn.agent_id, (set(), set(), set())
            )
            a_customers.add(txn.customer_id)
            a_merchants.add(txn.merchant_id)
            if txn.session_id:
                a_sessions.add(txn.session_id)
            agent.transaction_count += 1
            agent.mean_amount += (txn.amount - agent.mean_amount) / agent.transaction_count
            agent.distinct_customers = len(a_customers)
            agent.distinct_merchants = len(a_merchants)
            agent.session_count = len(a_sessions)
            agent.action_count += len(actions or ())
            agent.first_seen = agent.first_seen or txn.timestamp
            if txn.status == "FAILED":
                agent.failed_count += 1
            span_minutes = max(
                1e-6, (txn.timestamp - agent.first_seen).total_seconds() / 60.0
            )
            agent.mean_actions_per_minute = agent.action_count / max(1.0, span_minutes)

        self._window.append(txn)
        self._txn_by_id[txn.transaction_id] = txn
        for key in txn.linking_keys():
            self._by_entity[key].append(txn.transaction_id)

    def build(
        self,
        txn: TxnView,
        actions: list[ActionView] | None = None,
        delegation: DelegationView | None = None,
        intent_text: str | None = None,
        session_actions: dict[str, list[ActionView]] | None = None,
    ) -> RiskContext:
        """Build the context for ``txn`` using only what happened before it."""
        self._evict(txn.timestamp)
        neighbours, truncated = self.neighbourhood(txn)
        prior_actions = [a for a in (actions or ()) if a.timestamp <= txn.timestamp]
        return RiskContext(
            transaction=txn,
            now=txn.timestamp,
            actions=prior_actions,
            delegation=delegation,
            intent_text=intent_text,
            customer_history=self._customer_history(txn.customer_id),
            agent_history=self._agent_history(txn.agent_id),
            neighbourhood=neighbours,
            session_actions_by_session=session_actions or {},
            window_seconds=self.window_seconds,
            neighbourhood_truncated=truncated,
        )
