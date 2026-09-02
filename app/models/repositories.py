"""Repository access patterns for Veyra's six dedicated stores (Phase 1.4)."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, desc, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import incident_id, new_id, stable_hash
from app.models.entities import (
    BaselineStoreRow,
    EvalStoreRow,
    FeatureStoreRow,
    IncidentStoreRow,
    RawEventRow,
    RelationshipStoreRow,
)
from app.schemas.enums import BaselineConfidence, IncidentStatus, Severity


class RawEventsRepository:
    @staticmethod
    async def insert_event(session: AsyncSession, row: RawEventRow) -> RawEventRow:
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def get_by_event_id(session: AsyncSession, event_id: str) -> RawEventRow | None:
        return await session.get(RawEventRow, event_id)

    @staticmethod
    async def get_by_idempotency_key(session: AsyncSession, key: str) -> RawEventRow | None:
        stmt = select(RawEventRow).where(RawEventRow.idempotency_key == key)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_events_for_merchant(
        session: AsyncSession,
        merchant_id: str,
        start_ts: datetime,
        end_ts: datetime,
    ) -> list[RawEventRow]:
        stmt = (
            select(RawEventRow)
            .where(
                RawEventRow.merchant_id == merchant_id,
                RawEventRow.timestamp >= start_ts,
                RawEventRow.timestamp < end_ts,
            )
            .order_by(RawEventRow.timestamp.asc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


class FeatureStoreRepository:
    @staticmethod
    async def save_window_features(
        session: AsyncSession,
        merchant_id: str,
        window_size: str,
        window_end: datetime,
        features: dict[str, float],
        evidence: dict[str, Any] | None = None,
    ) -> FeatureStoreRow:
        row_id = stable_hash(f"{merchant_id}:{window_size}:{window_end.isoformat()}")
        existing = await session.get(FeatureStoreRow, row_id)
        if existing:
            existing.features = features
            existing.evidence = evidence or {}
            await session.flush()
            return existing

        row = FeatureStoreRow(
            id=row_id,
            merchant_id=merchant_id,
            window_size=window_size,
            window_end=window_end,
            features=features,
            evidence=evidence or {},
        )
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def get_window_features(
        session: AsyncSession,
        merchant_id: str,
        window_size: str,
        window_end: datetime,
    ) -> FeatureStoreRow | None:
        stmt = select(FeatureStoreRow).where(
            FeatureStoreRow.merchant_id == merchant_id,
            FeatureStoreRow.window_size == window_size,
            FeatureStoreRow.window_end == window_end,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


class BaselineStoreRepository:
    @staticmethod
    async def save_baseline(
        session: AsyncSession,
        merchant_id: str,
        feature_id: str,
        window_size: str,
        hour_of_week: int,
        expected_median: float,
        variability_mad: float,
        sample_count: int = 0,
        confidence: BaselineConfidence = BaselineConfidence.MEDIUM,
        version: int = 1,
        fit_period_start: datetime | None = None,
        fit_period_end: datetime | None = None,
    ) -> BaselineStoreRow:
        row_id = stable_hash(f"{merchant_id}:{feature_id}:{window_size}:{hour_of_week}:{version}")
        existing = await session.get(BaselineStoreRow, row_id)
        if existing:
            existing.expected_median = expected_median
            existing.variability_mad = variability_mad
            existing.sample_count = sample_count
            existing.confidence = confidence.value if isinstance(confidence, BaselineConfidence) else str(confidence)
            existing.fit_period_start = fit_period_start
            existing.fit_period_end = fit_period_end
            await session.flush()
            return existing

        row = BaselineStoreRow(
            id=row_id,
            merchant_id=merchant_id,
            feature_id=feature_id,
            window_size=window_size,
            hour_of_week=hour_of_week,
            version=version,
            expected_median=expected_median,
            variability_mad=variability_mad,
            sample_count=sample_count,
            confidence=confidence.value if isinstance(confidence, BaselineConfidence) else str(confidence),
            fit_period_start=fit_period_start,
            fit_period_end=fit_period_end,
        )
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def get_baseline(
        session: AsyncSession,
        merchant_id: str,
        feature_id: str,
        window_size: str,
        hour_of_week: int,
        version: int = 1,
    ) -> BaselineStoreRow | None:
        stmt = select(BaselineStoreRow).where(
            BaselineStoreRow.merchant_id == merchant_id,
            BaselineStoreRow.feature_id == feature_id,
            BaselineStoreRow.window_size == window_size,
            BaselineStoreRow.hour_of_week == hour_of_week,
            BaselineStoreRow.version == version,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_for_merchant(
        session: AsyncSession,
        merchant_id: str,
        version: int = 1,
    ) -> list[BaselineStoreRow]:
        stmt = select(BaselineStoreRow).where(
            BaselineStoreRow.merchant_id == merchant_id,
            BaselineStoreRow.version == version,
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


class RelationshipStoreRepository:
    @staticmethod
    async def record_co_occurrence(
        session: AsyncSession,
        merchant_id: str,
        entity_type_a: str,
        entity_id_a: str,
        entity_type_b: str,
        entity_id_b: str,
        seen_at: datetime,
        window_end: datetime,
        expires_at: datetime | None = None,
    ) -> RelationshipStoreRow:
        row_id = stable_hash(f"{merchant_id}:{entity_type_a}:{entity_id_a}:{entity_type_b}:{entity_id_b}")
        existing = await session.get(RelationshipStoreRow, row_id)
        if existing:
            existing.co_occurrence_count += 1
            existing.last_seen_at = seen_at
            existing.window_end = window_end
            existing.expires_at = expires_at or existing.expires_at
            await session.flush()
            return existing

        row = RelationshipStoreRow(
            id=row_id,
            merchant_id=merchant_id,
            entity_type_a=entity_type_a,
            entity_id_a=entity_id_a,
            entity_type_b=entity_type_b,
            entity_id_b=entity_id_b,
            co_occurrence_count=1,
            first_seen_at=seen_at,
            last_seen_at=seen_at,
            window_end=window_end,
            expires_at=expires_at,
        )
        session.add(row)
        await session.flush()
        return row


class IncidentStoreRepository:
    @staticmethod
    async def create_or_update_incident(session: AsyncSession, row: IncidentStoreRow) -> IncidentStoreRow:
        existing = await session.get(IncidentStoreRow, row.incident_id)
        if existing:
            existing.severity = row.severity
            existing.status = row.status
            existing.action_tier = row.action_tier
            existing.last_flag_time = row.last_flag_time
            existing.window_sizes = row.window_sizes
            existing.risk_score = row.risk_score
            existing.exposure_amount = row.exposure_amount
            existing.evidence = row.evidence
            existing.explanation = row.explanation
            await session.flush()
            return existing

        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def get_incident(session: AsyncSession, incident_id: str) -> IncidentStoreRow | None:
        return await session.get(IncidentStoreRow, incident_id)

    @staticmethod
    async def list_incidents(
        session: AsyncSession,
        merchant_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[IncidentStoreRow]:
        stmt = select(IncidentStoreRow)
        if merchant_id:
            stmt = stmt.where(IncidentStoreRow.merchant_id == merchant_id)
        if status:
            stmt = stmt.where(IncidentStoreRow.status == status)
        stmt = stmt.order_by(desc(IncidentStoreRow.last_flag_time)).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())


class EvalStoreRepository:
    @staticmethod
    async def record_prediction(session: AsyncSession, row: EvalStoreRow) -> EvalStoreRow:
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def list_run_records(
        session: AsyncSession,
        run_id: str,
        split: str | None = None,
    ) -> list[EvalStoreRow]:
        stmt = select(EvalStoreRow).where(EvalStoreRow.run_id == run_id)
        if split:
            stmt = stmt.where(EvalStoreRow.split == split)
        stmt = stmt.order_by(EvalStoreRow.window_end.asc())
        result = await session.execute(stmt)
        return list(result.scalars().all())
