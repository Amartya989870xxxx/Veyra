"""Veyra v2 FastAPI Application entrypoint (Phase 6)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.events import router as v1_events_router
from app.api.v2 import v2_router
from app.core.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup hooks.
    #
    # Warm the demo detector on a daemon thread rather than inline: fitting it takes
    # ~30s (app/serving/demo_model_service.py), and blocking startup on that would make
    # the whole API unavailable until it finished. Fired here so the model is usually
    # ready before the first /v2/demo/simulate call; if a request does arrive first it
    # simply waits on the same lock rather than training a second copy.
    import contextlib
    import threading

    from app.serving.demo_model_service import get_demo_model_service

    def _warm() -> None:
        # A failed warm-up must not take the app down; the first request retries the fit.
        with contextlib.suppress(Exception):
            get_demo_model_service().ensure_trained()

    threading.Thread(target=_warm, name="veyra-demo-model-warmup", daemon=True).start()

    yield
    # Shutdown hooks


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Veyra v2 — Fraud Spike Detection API",
        description="Near-real-time fraud spike detection and incident management platform.",
        version="2.0.0",
        lifespan=lifespan,
    )

    from app.api.middleware.rate_limit import RateLimitAndBotProtectionMiddleware
    from app.api.middleware.security_headers import SecurityHeadersMiddleware

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitAndBotProtectionMiddleware)

    # CORS: never a wildcard origin combined with credentials (browsers ignore the spec
    # violation and some stacks silently echo the request Origin, which defeats the
    # allowlist entirely). `settings.cors_origins_list` is required, non-wildcard config
    # in production — `Settings._production_fails_closed` refuses to even start
    # otherwise. Outside production, an explicit localhost fallback keeps the bundled
    # frontend dev server working with zero configuration.
    # 5173 is `vite dev`; 4173 is `vite preview`, which serves the production
    # bundle locally and is how the built frontend gets verified before deploy.
    # Omitting it made that check fail with an opaque CORS error rather than a
    # useful one. Production is unaffected: this branch is skipped entirely.
    cors_origins = settings.cors_origins_list or (
        [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
            "http://localhost:8008",
        ]
        if settings.environment != "production"
        else []
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "X-API-Key", "X-Merchant-ID", "Content-Type"],
    )

    # Health check
    @app.get("/health", tags=["Health"])
    async def health_check():
        return {"status": "ok", "version": "2.0.0", "environment": settings.environment}

    # Mount v1 and v2 routers
    app.include_router(v1_events_router)
    app.include_router(v2_router)

    # Mount frontend static distribution if built
    from pathlib import Path

    from fastapi.staticfiles import StaticFiles

    dist_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if dist_dir.exists():
        app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="frontend")

    return app


app = create_app()
