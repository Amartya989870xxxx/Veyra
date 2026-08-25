"""Shared API dependencies: auth, rate limiting, and the long-lived engine singletons."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import session_scope
from app.core.errors import AuthError, RateLimitedError
from app.core.logging import get_logger
from app.core.redis_client import get_hot_state
from app.decision.policy import DecisionPolicy
from app.features.baselines import Baselines
from app.features.engine import FeatureEngine
from app.graph.networkx_engine import NetworkXGraphEngine
from app.ingestion.service import IngestionService
from app.intent.service import IntentService
from app.risk.engine import RiskEngine
from app.risk.models import ModelBundle
from app.risk.rules import RuleEngine
from app.risk.service import RiskService

log = get_logger(__name__)

_state: dict = {}


def build_state(settings: Settings | None = None) -> dict:
    """Construct the engine graph once at startup.

    A missing model bundle is a supported state, not a failure: the API starts, serves
    deterministic rule- and policy-based decisions, and reports every ML component as
    unavailable. That is what lets `/health` and the test suite work before any training run.
    """
    settings = settings or get_settings()
    bundle = ModelBundle.try_load(settings.model_dir)

    baselines_path = Path(settings.model_dir) / "baselines.json"
    baselines = Baselines.load(baselines_path) if baselines_path.exists() else None
    if baselines is None:
        log.info("baselines_unavailable_using_defaults", extra={"path": str(baselines_path)})

    graph_engine = NetworkXGraphEngine()
    thresholds = (bundle.thresholds if bundle else None) or {}
    policy = DecisionPolicy(
        review_threshold=float(thresholds.get("review", 0.45)),
        block_threshold=float(thresholds.get("block", 0.75)),
    )
    engine = RiskEngine(
        feature_engine=FeatureEngine(graph_engine=graph_engine, baselines=baselines),
        rule_engine=RuleEngine(),
        intent_service=IntentService(),
        policy=policy,
        bundle=bundle,
    )
    return {
        "settings": settings,
        "bundle": bundle,
        "graph_engine": graph_engine,
        "risk_engine": engine,
        "risk_service": RiskService(engine=engine, graph_engine=graph_engine),
        "ingestion_service": IngestionService(hot_state=get_hot_state()),
        "policy": policy,
    }


def get_state() -> dict:
    if not _state:
        _state.update(build_state())
    return _state


def reset_state() -> None:
    """Rebuild the engine graph. Used by tests and after a training run."""
    _state.clear()


async def db_session() -> AsyncIterator[AsyncSession]:
    async with session_scope() as session:
        yield session


def get_risk_service() -> RiskService:
    return get_state()["risk_service"]


def get_ingestion_service() -> IngestionService:
    return get_state()["ingestion_service"]


def get_graph_engine() -> NetworkXGraphEngine:
    return get_state()["graph_engine"]


async def require_api_key(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """Static bearer auth. Disabled by default for local development."""
    if not settings.require_auth:
        return
    if not settings.api_key:
        raise AuthError("authentication is required but no API key is configured")
    expected = f"Bearer {settings.api_key}"
    if authorization != expected:
        raise AuthError("invalid or missing bearer token")


async def rate_limit(request: Request, settings: Settings = Depends(get_settings)) -> None:
    """Per-client sliding-window rate limit.

    Degrades to a bounded in-process counter when Redis is unavailable, which is weaker
    across replicas but never fails open silently — the degradation is logged.
    """
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
