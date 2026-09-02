"""Explanations and visual evidence package for Veyra v2 (Phase 6)."""

from app.explanations.generator import generate_incident_narrative
from app.explanations.visual_evidence import (
    build_entity_graph_payload,
    build_top_feature_deviations,
)

__all__ = [
    "generate_incident_narrative",
    "build_top_feature_deviations",
    "build_entity_graph_payload",
]
