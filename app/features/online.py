"""Online context builder: assembles a :class:`RiskContext` from PostgreSQL and Redis.

Produces exactly the same context type the offline evaluator builds, so every feature
function runs identical code in both paths. Where the offline builder streams state in
memory, this one queries indexed, time-bounded slices of the database.

Redis contributes rate limiting, dedupe and a cross-request hot velocity reading that is
attached to ``ctx.hot_state`` for *evidence only* — never as a model feature. A feature that
exists in production but not in training is a silent skew bug, and keeping Redis out of the
feature vector is what prevents one.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis_client import DEGRADED_TEMPORAL, HotStateClient, get_hot_state
from app.features.context import (
    ActionView,
    AgentHistory,
    CustomerHistory,
    DelegationView,
    RiskContext,
    TxnView,
)
from app.models.entities import AgentActionRow, AgentDelegationRow, TransactionRow
from app.schemas.entities import AgentAction, AgentDelegation, Transaction
from app.transactions import repository as repo

log = get_logger(__name__)


def row_to_txn_view(row: TransactionRow) -> TxnView:
    return TxnView(
        transaction_id=row.transaction_id,
        merchant_id=row.merchant_id,
        customer_id=row.customer_id,
        agent_id=row.agent_id,
        session_id=row.session_id,
        delegation_id=row.delegation_id,
        amount=float(row.amount),
        currency=row.currency,
        merchant_category=row.merchant_category,
        sku_id=row.sku_id,
        quantity=row.quantity,
        coupon_id=row.coupon_id,
        coupon_value=float(row.coupon_value or 0),
        device_id=row.device_id,
        network_fingerprint=row.network_fingerprint,
        payment_method=row.payment_method,
        instrument_fingerprint=row.instrument_fingerprint,
        retry_count=row.retry_count,
        status=row.status,
        actor_type=row.actor_type,
        timestamp=row.timestamp,
    )


def schema_to_txn_view(txn: Transaction) -> TxnView:
    return TxnView(
        transaction_id=txn.transaction_id,
        merchant_id=txn.merchant_id,
        customer_id=txn.customer_id,
        agent_id=txn.agent_id,
        session_id=txn.session_id,
        delegation_id=txn.delegation_id,
        amount=float(txn.amount),
        currency=txn.currency,
        merchant_category=txn.merchant_category,
        sku_id=txn.sku_id,
        quantity=txn.quantity,
        coupon_id=txn.coupon_id,
        coupon_value=float(txn.coupon_value),
        device_id=txn.device_id,
        network_fingerprint=txn.network_fingerprint,
        payment_method=txn.payment_method,
        instrument_fingerprint=txn.instrument_fingerprint,
        retry_count=txn.retry_count,
        status=str(txn.status),
        actor_type=str(txn.actor_type),
        timestamp=txn.timestamp,
    )


def action_row_to_view(row: AgentActionRow) -> ActionView:
    return ActionView(
        action_id=row.action_id,
        agent_id=row.agent_id,
        session_id=row.session_id,
        sequence_number=row.sequence_number,
        action_type=row.action_type,
        tool_name=row.tool_name,
        timestamp=row.timestamp,
        merchant_id=row.merchant_id,
        sku_id=row.sku_id,
    )


def action_schema_to_view(action: AgentAction) -> ActionView:
    return ActionView(
        action_id=action.action_id,
        agent_id=action.agent_id,
        session_id=action.session_id,
        sequence_number=action.sequence_number,
        action_type=str(action.action_type),
        tool_name=action.tool_name,
        timestamp=action.timestamp,
        merchant_id=action.merchant_id,
        sku_id=action.sku_id,
    )


def delegation_row_to_view(row: AgentDelegationRow) -> DelegationView:
    return DelegationView(
        delegation_id=row.delegation_id,
        customer_id=row.customer_id,
        agent_id=row.agent_id,
        purpose=row.purpose,
        max_amount=float(row.max_amount),
        currency=row.currency,
        allowed_categories=list(row.allowed_categories or []),
        forbidden_categories=list(row.forbidden_categories or []),
        allowed_merchants=list(row.allowed_merchants or []),
        merchant_policy=row.merchant_policy,
        approval_required_above=(
            float(row.approval_required_above)
            if row.approval_required_above is not None
            else None
        ),
        issued_at=row.issued_at,
        expires_at=row.expires_at,
    )


def delegation_schema_to_view(delegation: AgentDelegation) -> DelegationView:
    return DelegationView(
        delegation_id=delegation.delegation_id,
        customer_id=delegation.customer_id,
        agent_id=delegation.agent_id,
        purpose=delegation.purpose,
        max_amount=float(delegation.max_amount),
        currency=delegation.currency,
        allowed_categories=list(delegation.allowed_categories),
        forbidden_categories=list(delegation.forbidden_categories),
        allowed_merchants=list(delegation.allowed_merchants),
        merchant_policy=str(delegation.merchant_policy),
        approval_required_above=(
            float(delegation.approval_required_above)
            if delegation.approval_required_above is not None
            else None
        ),
        issued_at=delegation.issued_at,
        expires_at=delegation.expires_at,
    )


def _customer_history(rows: list[TransactionRow], before: datetime) -> CustomerHistory:
    history = CustomerHistory()
    amounts: list[float] = []
    merchants, categories, devices = set(), set(), set()
    for row in rows:
        if row.timestamp >= before:
            continue
        amount = float(row.amount)
        amounts.append(amount)
        merchants.add(row.merchant_id)
        categories.add(row.merchant_category)
        if row.device_id:
            devices.add(row.device_id)
        if row.status == "FAILED":
            history.failed_count += 1
        history.first_seen = min(history.first_seen or row.timestamp, row.timestamp)
        history.last_seen = max(history.last_seen or row.timestamp, row.timestamp)
    if amounts:
        history.transaction_count = len(amounts)
        history.mean_amount = sum(amounts) / len(amounts)
        mean = history.mean_amount
        history.m2_amount = sum((a - mean) ** 2 for a in amounts)
        history.max_amount = max(amounts)
    history.distinct_merchants = len(merchants)
    history.distinct_categories = len(categories)
    history.distinct_devices = len(devices)
    return history


def _agent_history(rows: list[TransactionRow], before: datetime) -> AgentHistory:
    history = AgentHistory()
    customers, merchants, sessions = set(), set(), set()
    amounts: list[float] = []
    for row in rows:
        if row.timestamp >= before:
            continue
        customers.add(row.customer_id)
        merchants.add(row.merchant_id)
        if row.session_id:
            sessions.add(row.session_id)
        amounts.append(float(row.amount))
        if row.status == "FAILED":
            history.failed_count += 1
        history.first_seen = min(history.first_seen or row.timestamp, row.timestamp)
    history.transaction_count = len(amounts)
    history.mean_amount = sum(amounts) / len(amounts) if amounts else 0.0
    history.distinct_customers = len(customers)
    history.distinct_merchants = len(merchants)
    history.session_count = len(sessions)
    return history


class OnlineContextBuilder:
    """Builds a scoring context from the system of record plus hot state."""

    def __init__(self, hot_state: HotStateClient | None = None) -> None:
        settings = get_settings()
        self.hot_state = hot_state or get_hot_state()
        self.window_seconds = settings.graph_window_seconds
        self.window_max_events = settings.graph_window_max_events

    async def build(
        self,
        session: AsyncSession,
        transaction: Transaction,
        supplied_actions: list[AgentAction] | None = None,
        supplied_delegation: AgentDelegation | None = None,
        instruction_text: str | None = None,
    ) -> RiskContext:
        view = schema_to_txn_view(transaction)
        now = transaction.timestamp

        # Actions: caller-supplied trace takes precedence, otherwise read the session's trace.
        actions: list[ActionView] = []
        if supplied_actions:
            actions = [action_schema_to_view(a) for a in supplied_actions]
        elif transaction.session_id:
            rows = await repo.actions_for_session(session, transaction.session_id, before=now)
            actions = [action_row_to_view(r) for r in rows]
        actions = [a for a in actions if a.timestamp <= now]
        actions.sort(key=lambda a: (a.sequence_number, a.timestamp))

        delegation: DelegationView | None = None
        if supplied_delegation is not None:
            delegation = delegation_schema_to_view(supplied_delegation)
        elif transaction.delegation_id:
            row = await repo.get_delegation(session, transaction.delegation_id)
            if row:
                delegation = delegation_row_to_view(row)
        elif transaction.agent_id:
            row = await repo.active_delegation_for(
                session, transaction.customer_id, transaction.agent_id, now
            )
            if row:
                delegation = delegation_row_to_view(row)

        customer_rows = await repo.customer_history_rows(session, transaction.customer_id, now)
        agent_rows = (
            await repo.agent_history_rows(session, transaction.agent_id, now)
            if transaction.agent_id
            else []
        )

        window_rows = await repo.transactions_in_window(
            session, now, self.window_seconds, limit=self.window_max_events
        )
        linking = set(view.linking_keys())
        neighbourhood: list[TxnView] = []
        truncated = False
        for row in window_rows:
            if row.transaction_id == transaction.transaction_id:
                continue
            candidate = row_to_txn_view(row)
            if linking & set(candidate.linking_keys()):
                neighbourhood.append(candidate)
                if len(neighbourhood) >= 400:
                    truncated = True
                    break

        session_actions: dict[str, list[ActionView]] = {}
        for neighbour in (*neighbourhood, view):
            if not neighbour.session_id or neighbour.session_id in session_actions:
                continue
            if neighbour.session_id == transaction.session_id and actions:
                session_actions[neighbour.session_id] = actions
                continue
            rows = await repo.actions_for_session(session, neighbour.session_id, before=now)
            session_actions[neighbour.session_id] = [action_row_to_view(r) for r in rows]

        ctx = RiskContext(
            transaction=view,
            now=now,
            actions=actions,
            delegation=delegation,
            intent_text=instruction_text,
            customer_history=_customer_history(customer_rows, now),
            agent_history=_agent_history(agent_rows, now),
            neighbourhood=neighbourhood,
            session_actions_by_session=session_actions,
            window_seconds=self.window_seconds,
            neighbourhood_truncated=truncated,
        )

        await self._attach_hot_state(ctx, transaction)
        return ctx

    async def _attach_hot_state(self, ctx: RiskContext, transaction: Transaction) -> None:
        """Cross-request velocity counters, for evidence only. Never a model feature."""
        readings: dict[str, float] = {}
        degraded = False
        for label, key in (
            ("customer_60s", f"tyche:vel:cus:{transaction.customer_id}"),
            ("device_60s", f"tyche:vel:dev:{transaction.device_id or 'none'}"),
            ("agent_60s", f"tyche:vel:agent:{transaction.agent_id or 'none'}"),
        ):
            count, was_degraded = await self.hot_state.incr_window(key, 60)
            readings[label] = float(count)
            degraded = degraded or was_degraded
        ctx.hot_state = readings
        if degraded:
            ctx.mark_degraded(DEGRADED_TEMPORAL)
