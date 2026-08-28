"""Liveness, readiness and metrics endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.db import check_database
from app.core.metrics import METRICS, RISK_LATENCY_MS
from app.core.redis_client import get_hot_state
from app.core.versions import APP_VERSION, FEATURE_VERSION, POLICY_VERSION, SCHEMA_VERSION

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
async def health() -> dict:
    """Liveness only. Deliberately does not touch dependencies, so a database blip cannot
    make the process look dead to an orchestrator."""
    return {
        "status": "ok",
        "service": "veyra",
        "version": APP_VERSION,
        "schema_version": SCHEMA_VERSION,
    }


@router.get("/ready", summary="Readiness probe")
async def ready() -> dict:
    """Readiness, with each dependency reported separately.

    Redis being down is *degraded*, not unready: Veyra is designed to keep deciding without
    it. The database being down is unready, because a decision that cannot be persisted
    cannot be audited.
    """
    from app.api.deps import get_state

    db_ok, db_error = await check_database()
    redis_ok = await get_hot_state().ping()
    settings = get_settings()
    state = get_state()
    bundle = state.get("bundle")

    components = {
        "database": {"status": "ok" if db_ok else "unavailable", "detail": db_error},
        "redis": {
            "status": "ok" if redis_ok else "degraded",
            "detail": None if redis_ok else "using bounded in-process fallback",
        },
        "model_bundle": {
            "status": "ok" if bundle else "unavailable",
            "detail": None if bundle else "no trained bundle; deterministic components only",
        },
        "semantic_engine": {
            "status": "ok" if settings.semantic_is_configured() else "disabled",
            "detail": None if settings.semantic_is_configured()
            else "semantic verification not configured; deterministic checks only",
        },
    }

    ready_state = db_ok
    degraded = [name for name, c in components.items() if c["status"] != "ok"]
    return {
        "status": (
            "ready" if ready_state and not degraded else ("ready" if ready_state else "not_ready")
        ),
        "ready": ready_state,
        "degraded_components": degraded,
        "components": components,
        "versions": {
            "app": APP_VERSION,
            "schema": SCHEMA_VERSION,
            "policy": POLICY_VERSION,
            "features": FEATURE_VERSION,
        },
    }


@router.get("/api/v1/metrics", tags=["observability"], summary="In-process metrics snapshot")
async def metrics() -> dict:
    snapshot = METRICS.snapshot()
    snapshot["derived"] = {
        "risk_p95_latency_ms": METRICS.percentile(RISK_LATENCY_MS, 95),
        "risk_p50_latency_ms": METRICS.percentile(RISK_LATENCY_MS, 50),
    }
    return snapshot
