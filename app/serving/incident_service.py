"""Incident lifecycle and analyst actions service (Phase 6.1).

Manages incident triage, resolution, and applying recommended merchant defensive controls.
"""

from __future__ import annotations

from typing import Any, Sequence
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import IncidentStoreRow
from app.models.repositories import IncidentStoreRepository
from app.schemas.enums import ActionTier, IncidentStatus


class IncidentService:
    """Incident management and action execution."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_incidents(
        self,
        merchant_id: str | None = None,
        status: IncidentStatus | str | None = None,
        limit: int = 50,
    ) -> list[IncidentStoreRow]:
        st_val = status.value if isinstance(status, IncidentStatus) else status
        return await IncidentStoreRepository.list_incidents(
            session=self.session,
            merchant_id=merchant_id,
            status=st_val,
            limit=limit,
        )

    async def get_incident(self, incident_id: str) -> IncidentStoreRow | None:
        return await IncidentStoreRepository.get_incident(
            session=self.session,
            incident_id=incident_id,
        )

    async def apply_action(
        self,
        incident_id: str,
        action: str,  # "ACKNOWLEDGE", "APPLY_DEFENSE", "DISMISS", "RESOLVE"
        analyst_notes: str = "",
    ) -> IncidentStoreRow | None:
        incident = await IncidentStoreRepository.get_incident(
            session=self.session,
            incident_id=incident_id,
        )
        if not incident:
            return None

        new_status = incident.status
        if action == "ACKNOWLEDGE":
            new_status = IncidentStatus.ACKNOWLEDGED.value
        elif action == "APPLY_DEFENSE":
            new_status = IncidentStatus.CONFIRMED.value
        elif action == "DISMISS":
            new_status = IncidentStatus.DISMISSED.value
        elif action == "RESOLVE":
            new_status = IncidentStatus.CLOSED.value

        incident.status = new_status
        # IncidentStoreRow has no `analyst_notes` column; notes live inside the existing
        # `evidence` JSON blob. Reassigning (not mutating in place) is required for
        # SQLAlchemy to see the JSON column as dirty and persist it.
        evidence = dict(incident.evidence or {})
        evidence["analyst_notes"] = analyst_notes or f"Applied action {action}"
        incident.evidence = evidence
        await self.session.flush()
        return incident
