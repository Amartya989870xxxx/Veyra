"""Integration tests for event ingestion and storage (Phase 1.3 & 1.4)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.redis_client import HotStateClient
from app.ingestion.service import IngestionService
from app.models.base import Base
from app.models.repositories import RawEventsRepository
from app.schemas.entities import Dispute, OrderOutcome, PaymentAttempt, PaymentOutcome, Refund
from app.schemas.enums import (
    DeclineSource,
    DisputeType,
    EventType,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    RefundReason,
)
from app.schemas.events import (
    DisputeEvent,
    OrderStatusEvent,
    PaymentAttemptEvent,
    PaymentResultEvent,
    RefundEvent,
)


@pytest.fixture
async def test_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def ingestion_service():
    return IngestionService(hot_state=HotStateClient(enabled=False))


async def test_ingest_payment_attempt_event(
    test_session: AsyncSession, ingestion_service: IngestionService
):
    now = datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)
    attempt = PaymentAttempt(
        transaction_id="txn_001",
        merchant_id="m_test",
        instrument_fp="if_card_001",
        amount=Decimal("1499.00"),
        currency="INR",
        payment_method=PaymentMethod.CARD,
        timestamp=now,
    )
    event = PaymentAttemptEvent(
        event_id="evt_001",
        timestamp=now,
        payment_attempt=attempt,
    )

    outcome = await ingestion_service.ingest(test_session, event)
    assert outcome.result.accepted is True
    assert outcome.result.duplicate is False
    assert outcome.transaction_id == "txn_001"

    # Confirm in raw_events table
    row = await RawEventsRepository.get_by_event_id(test_session, "evt_001")
    assert row is not None
    assert row.event_type == EventType.PAYMENT_ATTEMPT.value
    assert row.merchant_id == "m_test"
    assert row.payload["payment_attempt"]["amount"] == "1499.00"


async def test_ingest_idempotency_duplicate(
    test_session: AsyncSession, ingestion_service: IngestionService
):
    now = datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)
    attempt = PaymentAttempt(
        transaction_id="txn_002",
        merchant_id="m_test",
        instrument_fp="if_card_002",
        amount=Decimal("999.00"),
        currency="INR",
        timestamp=now,
    )
    event = PaymentAttemptEvent(
        event_id="evt_002",
        timestamp=now,
        payment_attempt=attempt,
    )

    # First ingest -> Accepted
    outcome1 = await ingestion_service.ingest(test_session, event)
    assert outcome1.result.accepted is True

    # Second ingest -> Detected duplicate
    outcome2 = await ingestion_service.ingest(test_session, event)
    assert outcome2.result.accepted is False
    assert outcome2.result.duplicate is True
    assert outcome2.result.reason == "event already ingested"


async def test_ingest_all_event_types_batch(
    test_session: AsyncSession, ingestion_service: IngestionService
):
    now = datetime(2026, 3, 15, 12, 1, 0, tzinfo=UTC)

    attempt_event = PaymentAttemptEvent(
        event_id="evt_batch_1",
        timestamp=now,
        payment_attempt=PaymentAttempt(
            transaction_id="txn_b1",
            merchant_id="m_batch",
            instrument_fp="if_b1",
            amount=Decimal("500.00"),
            timestamp=now,
        ),
    )

    result_event = PaymentResultEvent(
        event_id="evt_batch_2",
        timestamp=now,
        merchant_id="m_batch",
        outcome=PaymentOutcome(
            transaction_id="txn_b1",
            status=PaymentStatus.CAPTURED,
            timestamp=now,
        ),
    )

    refund_event = RefundEvent(
        event_id="evt_batch_3",
        timestamp=now,
        merchant_id="m_batch",
        refund=Refund(
            refund_id="ref_01",
            transaction_id="txn_b1",
            amount=Decimal("500.00"),
            reason_code=RefundReason.CUSTOMER_REQUEST,
            timestamp=now,
        ),
    )

    dispute_event = DisputeEvent(
        event_id="evt_batch_4",
        timestamp=now,
        merchant_id="m_batch",
        dispute=Dispute(
            dispute_id="dsp_01",
            transaction_id="txn_b1",
            dispute_type=DisputeType.FRAUD,
            amount=Decimal("500.00"),
            days_after_transaction=14,
            timestamp=now,
        ),
    )

    order_event = OrderStatusEvent(
        event_id="evt_batch_5",
        timestamp=now,
        order=OrderOutcome(
            order_id="ord_01",
            merchant_id="m_batch",
            status=OrderStatus.DELIVERED,
            timestamp=now,
        ),
    )

    events = [attempt_event, result_event, refund_event, dispute_event, order_event]
    outcomes = await ingestion_service.ingest_batch(test_session, events)

    assert len(outcomes) == 5
    assert all(o.result.accepted for o in outcomes)

    # Verify all 5 events exist in raw_events
    for evt in events:
        row = await RawEventsRepository.get_by_event_id(test_session, evt.event_id)
        assert row is not None
        assert row.event_type == evt.event_type.value
