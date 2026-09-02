"""Shared API dependencies: rate limiting and database sessions.

Authentication and tenant authorization live in `app.core.auth` — `get_current_principal`,
`verify_tenant_access`, `resolve_tenant_scope`. This module intentionally does not define
an auth dependency of its own; it used to (`require_api_key`, a single global bearer
token with no merchant/role concept), and having two auth paths meant most routes ended
up wired to neither. Routes needing identity should depend on
`app.core.auth.get_current_principal` directly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import session_scope
from app.core.errors import RateLimitedError
from app.core.logging import get_logger
from app.core.redis_client import get_hot_state
from app.ingestion.service import IngestionService

log = get_logger(__name__)

_state: dict = {}


def get_ingestion_service() -> IngestionService:
    if "ingestion_service" not in _state:
        _state["ingestion_service"] = IngestionService(hot_state=get_hot_state())
    return _state["ingestion_service"]


def reset_state() -> None:
    _state.clear()


async def db_session() -> AsyncIterator[AsyncSession]:
    async with session_scope() as session:
        yield session


async def rate_limit(request: Request, settings: Settings = Depends(get_settings)) -> None:
    """Per-client sliding-window rate limit."""
    if settings.rate_limit_per_minute <= 0:
        return
    client = request.client.host if request.client else "unknown"
    key = f"veyra:ratelimit:{client}"
    count, degraded = await get_hot_state().incr_window(key, 60)
    if degraded:
        log.debug("rate_limit_degraded", extra={"client": client})
    if count > settings.rate_limit_per_minute:
        raise RateLimitedError(
            "rate limit exceeded",
            details={"limit_per_minute": settings.rate_limit_per_minute},
        )
