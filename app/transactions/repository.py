"""Transaction, entity and relationship persistence."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    AgentActionRow,
    AgentDelegationRow,
    AgentRow,
    AgentSessionRow,
    CustomerRow,
    EntityRelationshipRow,
    MerchantRow,
    OrderRow,
    TransactionRow,
)
from app.schemas.entities import (
    AgentAction,
    AgentDelegation,
    AgentSession,
    Order,
    Transaction,
)
from app.schemas.enums import RelationshipType


async def upsert_merchant(session: AsyncSession, merchant_id: str, category: str) -> None:
    if await session.get(MerchantRow, merchant_id):
        return
    session.add(MerchantRow(merchant_id=merchant_id, category=category))


async def upsert_customer(session: AsyncSession, customer_id: str) -> None:
    if await session.get(CustomerRow, customer_id):
        return
    session.add(CustomerRow(customer_id=customer_id))


async def upsert_agent(session: AsyncSession, agent_id: str, provider: str = "synthetic") -> None:
    if await session.get(AgentRow, agent_id):
        return
    session.add(AgentRow(agent_id=agent_id, provider=provider))


async def save_transaction(session: AsyncSession, txn: Transaction) -> TransactionRow:
    """Insert a transaction, or return the existing row if the ID is already known.

    Returning the existing row rather than raising is what makes replay idempotent at the
    service layer while the primary key remains the actual guarantee.
    """
    existing = await session.get(TransactionRow, txn.transaction_id)
    if existing:
        return existing

    await upsert_merchant(session, txn.merchant_id, txn.merchant_category)
    await upsert_customer(session, txn.customer_id)
    if txn.agent_id:
        await upsert_agent(session, txn.agent_id)

    row = TransactionRow(
        transaction_id=txn.transaction_id,
        merchant_id=txn.merchant_id,
        customer_id=txn.customer_id,
        agent_id=txn.agent_id,
        session_id=txn.session_id,
        order_id=txn.order_id,
        delegation_id=txn.delegation_id,
        amount=txn.amount,
        currency=txn.currency,
        merchant_category=txn.merchant_category,
        sku_id=txn.sku_id,
        quantity=txn.quantity,
        coupon_id=txn.coupon_id,
        coupon_value=txn.coupon_value,
        device_id=txn.device_id,
        network_fingerprint=txn.network_fingerprint,
        payment_method=txn.payment_method,
        instrument_fingerprint=txn.instrument_fingerprint,
        retry_count=txn.retry_count,
        status=str(txn.status),
        actor_type=str(txn.actor_type),
        timestamp=txn.timestamp,
    )
    session.add(row)
    await session.flush()
    await record_relationships(session, txn)
    return row


async def record_relationships(session: AsyncSession, txn: Transaction) -> None:
    """Materialise the entity edges implied by a transaction.

    Never carries payment secrets: ``instrument_fingerprint`` is a synthetic non-reversible
    token, and no credential, card number or authentication artefact reaches this table.
    """
    edges: list[tuple[str, str, str, str, RelationshipType]] = []
    customer = ("CUSTOMER", txn.customer_id)

    for kind, value, relationship in (
        ("DEVICE", txn.device_id, RelationshipType.USES_DEVICE),
        ("NETWORK", txn.network_fingerprint, RelationshipType.USES_NETWORK),
        ("AGENT", txn.agent_id, RelationshipType.OPERATED_BY_AGENT),
        ("SESSION", txn.session_id, RelationshipType.IN_SESSION),
        ("MERCHANT", txn.merchant_id, RelationshipType.PAID_MERCHANT),
        ("SKU", txn.sku_id, RelationshipType.PURCHASED_SKU),
        ("COUPON", txn.coupon_id, RelationshipType.REDEEMED_COUPON),
    ):
        if value:
            edges.append((customer[0], customer[1], kind, value, relationship))
    edges.append(
        ("CUSTOMER", txn.customer_id, "TRANSACTION", txn.transaction_id,
         RelationshipType.MADE_TRANSACTION)
    )

    for source_type, source_id, target_type, target_id, relationship in edges:
        stmt = select(EntityRelationshipRow).where(
            EntityRelationshipRow.source_type == source_type,
            EntityRelationshipRow.source_id == source_id,
            EntityRelationshipRow.target_type == target_type,
            EntityRelationshipRow.target_id == target_id,
            EntityRelationshipRow.relationship == str(relationship),
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing:
            existing.observation_count += 1
            existing.last_seen = txn.timestamp
        else:
            session.add(
                EntityRelationshipRow(
                    source_type=source_type,
                    source_id=source_id,
                    target_type=target_type,
                    target_id=target_id,
                    relationship=str(relationship),
                    first_seen=txn.timestamp,
                    last_seen=txn.timestamp,
                )
            )


async def get_transaction(session: AsyncSession, transaction_id: str) -> TransactionRow | None:
    return await session.get(TransactionRow, transaction_id)


async def save_session(session: AsyncSession, agent_session: AgentSession) -> None:
    if await session.get(AgentSessionRow, agent_session.session_id):
        return
    await upsert_customer(session, agent_session.customer_id)
    if agent_session.agent_id:
        await upsert_agent(session, agent_session.agent_id)
    session.add(
        AgentSessionRow(
            session_id=agent_session.session_id,
            agent_id=agent_session.agent_id,
            customer_id=agent_session.customer_id,
            actor_type=str(agent_session.actor_type),
            device_id=agent_session.device_id,
            network_fingerprint=agent_session.network_fingerprint,
            started_at=agent_session.started_at,
            ended_at=agent_session.ended_at,
        )
    )


async def save_action(session: AsyncSession, action: AgentAction) -> bool:
    """Insert an agent action. Returns False when the action ID is already present."""
    if await session.get(AgentActionRow, action.action_id):
        return False
    await upsert_agent(session, action.agent_id)
    session.add(
        AgentActionRow(
            action_id=action.action_id,
            agent_id=action.agent_id,
            session_id=action.session_id,
            sequence_number=action.sequence_number,
            action_type=str(action.action_type),
            tool_name=action.tool_name,
            merchant_id=action.merchant_id,
            sku_id=action.sku_id,
            timestamp=action.timestamp,
            action_metadata=action.metadata,
        )
    )
    return True


async def save_delegation(session: AsyncSession, delegation: AgentDelegation) -> None:
    if await session.get(AgentDelegationRow, delegation.delegation_id):
        return
    await upsert_customer(session, delegation.customer_id)
    await upsert_agent(session, delegation.agent_id)
    session.add(
        AgentDelegationRow(
            delegation_id=delegation.delegation_id,
            customer_id=delegation.customer_id,
            agent_id=delegation.agent_id,
            purpose=delegation.purpose,
            max_amount=delegation.max_amount,
            currency=delegation.currency,
            allowed_categories=list(delegation.allowed_categories),
            forbidden_categories=list(delegation.forbidden_categories),
            allowed_merchants=list(delegation.allowed_merchants),
            allowed_actions=[str(a) for a in delegation.allowed_actions],
            merchant_policy=str(delegation.merchant_policy),
            approval_required_above=delegation.approval_required_above,
            issued_at=delegation.issued_at,
            expires_at=delegation.expires_at,
        )
    )


async def save_order(session: AsyncSession, order: Order) -> None:
    if await session.get(OrderRow, order.order_id):
        return
    await upsert_merchant(session, order.merchant_id, "unknown")
    await upsert_customer(session, order.customer_id)
    session.add(
        OrderRow(
            order_id=order.order_id,
            merchant_id=order.merchant_id,
            customer_id=order.customer_id,
            amount=order.amount,
            currency=order.currency,
            sku_id=order.sku_id,
            quantity=order.quantity,
            created_at=order.created_at,
        )
    )


async def actions_for_session(
    session: AsyncSession, session_id: str, before: datetime | None = None, limit: int = 500
) -> list[AgentActionRow]:
    stmt = select(AgentActionRow).where(AgentActionRow.session_id == session_id)
    if before:
        stmt = stmt.where(AgentActionRow.timestamp <= before)
    stmt = stmt.order_by(AgentActionRow.sequence_number).limit(limit)
    return list((await session.execute(stmt)).scalars())


async def transactions_in_window(
    session: AsyncSession, until: datetime, window_seconds: int, limit: int = 5000
) -> list[TransactionRow]:
    """All transactions in the past-only window ending at ``until``."""
    since = until - timedelta(seconds=window_seconds)
    stmt = (
        select(TransactionRow)
        .where(TransactionRow.timestamp >= since, TransactionRow.timestamp <= until)
        .order_by(TransactionRow.timestamp.desc())
        .limit(limit)
    )
    rows = list((await session.execute(stmt)).scalars())
    rows.reverse()
    return rows


async def customer_history_rows(
    session: AsyncSession, customer_id: str, before: datetime, limit: int = 1000
) -> list[TransactionRow]:
    stmt = (
        select(TransactionRow)
        .where(TransactionRow.customer_id == customer_id, TransactionRow.timestamp < before)
        .order_by(TransactionRow.timestamp.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars())


async def agent_history_rows(
    session: AsyncSession, agent_id: str, before: datetime, limit: int = 1000
) -> list[TransactionRow]:
    stmt = (
        select(TransactionRow)
        .where(TransactionRow.agent_id == agent_id, TransactionRow.timestamp < before)
        .order_by(TransactionRow.timestamp.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars())


async def get_delegation(
    session: AsyncSession, delegation_id: str
) -> AgentDelegationRow | None:
    return await session.get(AgentDelegationRow, delegation_id)


async def active_delegation_for(
    session: AsyncSession, customer_id: str, agent_id: str, at: datetime
) -> AgentDelegationRow | None:
    """Most recently issued delegation for the pair, whether or not it has expired.

    Expired delegations are returned deliberately: an expired grant is a *finding*, and
    hiding it would turn a hard authorization breach into a silent "no delegation present".
    """
    stmt = (
        select(AgentDelegationRow)
        .where(
            AgentDelegationRow.customer_id == customer_id,
            AgentDelegationRow.agent_id == agent_id,
            AgentDelegationRow.issued_at <= at,
        )
        .order_by(AgentDelegationRow.issued_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()
