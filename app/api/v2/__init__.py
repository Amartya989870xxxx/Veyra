"""Veyra v2 API routers package (Phase 6 & 7)."""

from fastapi import APIRouter

from app.api.v2.baselines import router as baselines_router
from app.api.v2.demo import router as demo_router
from app.api.v2.demo_benchmarks import router as demo_benchmarks_router
from app.api.v2.demo_runs import router as demo_runs_router
from app.api.v2.incidents import router as incidents_router
from app.api.v2.scoring import router as scoring_router

v2_router = APIRouter(prefix="/v2")
v2_router.include_router(scoring_router)
v2_router.include_router(incidents_router)
v2_router.include_router(baselines_router)
# Order matters: the more specific /demo/runs and /demo/benchmarks prefixes are mounted
# before /demo, so they are not shadowed by a broader route on the demo router.
v2_router.include_router(demo_runs_router)
v2_router.include_router(demo_benchmarks_router)
v2_router.include_router(demo_router)

__all__ = ["v2_router"]
