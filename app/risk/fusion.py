"""Risk fusion.

Component scores are combined by a logistic regression whose weights are **learned** from
out-of-fold predictions on the training split. The PRD is explicit that hand-picked weights
presented as a model are not acceptable, so the only hard-coded weights in this file are the
documented cold-start fallback used before any training has happened — and it labels itself
as such in the response.

Missing components are handled by passing an availability flag alongside each score rather
than substituting a value. A component that could not be computed is scored 0.0 *with its
flag off*, so the model can learn that absence means "unknown", not "safe". This is the
mechanism behind "never invent a score": a degraded component contributes no signal instead
of contributing a fabricated one.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.core.versions import FUSION_VERSION
from app.schemas.risk import ComponentScores

COMPONENT_ORDER = [
    "transaction_risk",
    "behavior_risk",
    "campaign_risk",
    "intent_deviation",
    "rule_violation_score",
]

AVAILABILITY_NAMES = [f"avail_{name}" for name in COMPONENT_ORDER]
FUSION_INPUT_NAMES = COMPONENT_ORDER + AVAILABILITY_NAMES

# Cold-start weights, used only when no trained bundle is loaded. Chosen to be conservative
# and deliberately unremarkable: they exist so the API can answer before a model exists, and
# every response produced with them reports fusion version "static-fallback-v1".
STATIC_WEIGHTS = {
    "transaction_risk": 0.22,
    "behavior_risk": 0.20,
    "campaign_risk": 0.30,
    "intent_deviation": 0.18,
    "rule_violation_score": 0.10,
}
STATIC_FUSION_VERSION = "static-fallback-v1"


def fusion_row(scores: ComponentScores | dict[str, float | None]) -> list[float]:
    """Build the fusion input vector: five scores followed by five availability flags."""
    values = scores.model_dump() if isinstance(scores, ComponentScores) else dict(scores)
    row: list[float] = []
    for name in COMPONENT_ORDER:
        value = values.get(name)
        row.append(0.0 if value is None else float(value))
    for name in COMPONENT_ORDER:
        row.append(0.0 if values.get(name) is None else 1.0)
    return row


def fusion_matrix(rows: list[ComponentScores | dict]) -> np.ndarray:
    return np.asarray([fusion_row(r) for r in rows], dtype=float)


@dataclass
class FusionOutput:
    risk_score: float
    version: str
    contributions: dict[str, float]
    used_static_fallback: bool = False


def static_fuse(scores: ComponentScores) -> FusionOutput:
    """Cold-start fusion: a weighted mean over *available* components only.

    Renormalising over available components is what keeps a missing component from
    silently dragging the score toward zero.
    """
    available = scores.available()
    if not available:
        # Nothing at all could be computed. There is no honest score to return; the caller
        # must route this to REVIEW as a degraded decision.
        return FusionOutput(
            risk_score=0.0, version=STATIC_FUSION_VERSION, contributions={},
            used_static_fallback=True,
        )
    weight_total = sum(STATIC_WEIGHTS[name] for name in available)
    contributions = {
        name: (STATIC_WEIGHTS[name] / weight_total) * value for name, value in available.items()
    }
    return FusionOutput(
        risk_score=min(1.0, max(0.0, sum(contributions.values()))),
        version=STATIC_FUSION_VERSION,
        contributions=contributions,
        used_static_fallback=True,
    )


def fuse(scores: ComponentScores, fusion_model=None) -> FusionOutput:
    """Fuse component scores with a trained model, or fall back to static weights."""
    if fusion_model is None or not getattr(fusion_model, "is_fitted", False):
        return static_fuse(scores)

    row = np.asarray([fusion_row(scores)], dtype=float)
    risk = float(fusion_model.predict(row)[0])
    raw = fusion_model.contributions(
        dict(zip(FUSION_INPUT_NAMES, fusion_row(scores), strict=True))
    )
    contributions = {name: raw.get(name, 0.0) for name in COMPONENT_ORDER}
    return FusionOutput(
        risk_score=min(1.0, max(0.0, risk)),
        version=fusion_model.version or FUSION_VERSION,
        contributions=contributions,
    )
