"""Unit tests for the six dedicated storage stores and repositories (Phase 1.4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.entities import (
    BaselineStoreRow,
    EvalStoreRow,
    FeatureStoreRow,
    IncidentStoreRow,
    RawEventRow,
    RelationshipStoreRow,
)
from app.models.repositories import (
    BaselineStoreRepository,
    EvalStoreRepository,
    FeatureStoreRepository,
    IncidentStoreRepository,
    RawEventsRepository,
    RelationshipStoreRepository,
)
from app.schemas.enums import (
    ActionTier,
    BaselineConfidence,
    IncidentStatus,
    Severity,
    SplitName,
    WindowLabel,
)


@pytest.fixture
async def test_db_session():
    """In-memory SQLite async session for storage unit testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session

    await engine.dispose()


async def test_raw_events_store_lifecycle(test_db_session: AsyncSession):
    """1. raw_events: test persistence and query by event_id / idempotency_key."""
    now = datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)
    row = RawEventRow(
        event_id="evt_test_01",
        event_type="PAYMENT_ATTEMPT",
        source="synthetic",
        timestamp=now,
        schema_version="2.0",
        idempotency_key="idemp_01",
        merchant_id="m_100",
        payload_hash="hash123",
        payload={"amount": "500.00", "currency": "INR"},
    )
    await RawEventsRepository.insert_event(test_db_session, row)

    fetched = await RawEventsRepository.get_by_event_id(test_db_session, "evt_test_01")
    assert fetched is not None
    assert fetched.merchant_id == "m_100"
    assert fetched.payload["amount"] == "500.00"

    by_key = await RawEventsRepository.get_by_idempotency_key(test_db_session, "idemp_01")
    assert by_key is not None
    assert by_key.event_id == "evt_test_01"

    events = await RawEventsRepository.list_events_for_merchant(
        test_db_session, "m_100", now - timedelta(minutes=5), now + timedelta(minutes=5)
    )
    assert len(events) == 1


async def test_feature_store_lifecycle(test_db_session: AsyncSession):
    """2. feature_store: window aggregates per (merchant, window, ts)."""
    now = datetime(2026, 3, 15, 12, 5, 0, tzinfo=UTC)
    features = {"A.txn_rate": 45.2, "C.failure_rate": 0.02}
    evidence = {"n_txns": 226, "unique_devices": 220}

    row = await FeatureStoreRepository.save_window_features(
        test_db_session, "m_100", "5m", now, features, evidence
    )
    assert row.merchant_id == "m_100"

    fetched = await FeatureStoreRepository.get_window_features(
        test_db_session, "m_100", "5m", now
    )
    assert fetched is not None
    assert fetched.features["A.txn_rate"] == 45.2
    assert fetched.evidence["n_txns"] == 226


async def test_baseline_store_lifecycle(test_db_session: AsyncSession):
    """3. baseline_store: versioned expected behavioral baselines and MAD variability."""
    row = await BaselineStoreRepository.save_baseline(
        session=test_db_session,
        merchant_id="m_100",
        feature_id="A.txn_rate",
        window_size="5m",
        hour_of_week=42,
        expected_median=12.5,
        variability_mad=2.1,
        sample_count=200,
        confidence=BaselineConfidence.HIGH,
        version=1,
    )
    assert row.expected_median == 12.5
    assert row.confidence == "HIGH"

    fetched = await BaselineStoreRepository.get_baseline(
        test_db_session, "m_100", "A.txn_rate", "5m", 42, version=1
    )
    assert fetched is not None
    assert fetched.variability_mad == 2.1


async def test_relationship_store_lifecycle(test_db_session: AsyncSession):
    """4. relationship_store: graph entity co-occurrence persistence."""
    now = datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)
    row = await RelationshipStoreRepository.record_co_occurrence(
        session=test_db_session,
        merchant_id="m_100",
        entity_type_a="device",
        entity_id_a="dv_abc",
        entity_type_b="instrument",
        entity_id_b="if_xyz",
        seen_at=now,
        window_end=now + timedelta(minutes=5),
        expires_at=now + timedelta(days=7),
    )
    assert row.co_occurrence_count == 1

    # Record co-occurrence again -> count increases
    row2 = await RelationshipStoreRepository.record_co_occurrence(
        session=test_db_session,
        merchant_id="m_100",
        entity_type_a="device",
        entity_id_a="dv_abc",
        entity_type_b="instrument",
        entity_id_b="if_xyz",
        seen_at=now + timedelta(minutes=1),
        window_end=now + timedelta(minutes=5),
    )
    assert row2.co_occurrence_count == 2


async def test_incident_store_lifecycle(test_db_session: AsyncSession):
    """5. incident_store: first-class incident lifecycle and exposure."""
    now = datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)
    incident = IncidentStoreRow(
        incident_id="inc_001",
        merchant_id="m_100",
        severity=Severity.HIGH.value,
        status=IncidentStatus.OPEN.value,
        action_tier=ActionTier.REVIEW.value,
        first_flag_time=now,
        last_flag_time=now + timedelta(minutes=10),
        window_sizes=["1m", "5m"],
        risk_score=0.88,
        exposure_amount=Decimal("12500.00"),
        baseline_confidence=BaselineConfidence.HIGH.value,
        evidence={"card_testing_detected": True},
        explanation="High velocity card enumeration detected.",
    )
    await IncidentStoreRepository.create_or_update_incident(test_db_session, incident)

    fetched = await IncidentStoreRepository.get_incident(test_db_session, "inc_001")
    assert fetched is not None
    assert fetched.risk_score == 0.88
    assert fetched.exposure_amount == Decimal("12500.00")
    assert fetched.status == "OPEN"

    # Update status to ACKNOWLEDGED
    fetched.status = IncidentStatus.ACKNOWLEDGED.value
    await IncidentStoreRepository.create_or_update_incident(test_db_session, fetched)

    updated = await IncidentStoreRepository.get_incident(test_db_session, "inc_001")
    assert updated is not None
    assert updated.status == "ACKNOWLEDGED"


async def test_eval_store_lifecycle(test_db_session: AsyncSession):
    """6. eval_store: model predictions, ground truth and run records."""
    now = datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)
    eval_row = EvalStoreRow(
        eval_id="eval_001",
        run_id="run_2026_03_15_01",
        split=SplitName.TEST.value,
        merchant_id="m_100",
        window_size="5m",
        window_end=now,
        detector_name="veyra_fusion",
        predicted_score=0.91,
        action_tier=ActionTier.RESTRICT.value,
        ground_truth_label=WindowLabel.FRAUD_SPIKE.value,
        scenario_id="card_testing_burst",
        loss_incurred=0.0,
    )
    await EvalStoreRepository.record_prediction(test_db_session, eval_row)

    records = await EvalStoreRepository.list_run_records(test_db_session, "run_2026_03_15_01")
    assert len(records) == 1
    assert records[0].detector_name == "veyra_fusion"
    assert records[0].ground_truth_label == "FRAUD_SPIKE"
