"""Veyra v2 Feature and Baseline Engine package (Phase 3)."""

from app.features.aggregator import WindowAgg, compute_window_features_dict
from app.features.baselines import (
    BaselineEngine,
    BaselineProfile,
    compute_median_and_mad,
    fit_baselines_from_window_history,
)
from app.features.engine import FeatureEngine, WindowFeatureVector

__all__ = [
    "WindowAgg",
    "compute_window_features_dict",
    "BaselineEngine",
    "BaselineProfile",
    "compute_median_and_mad",
    "fit_baselines_from_window_history",
    "FeatureEngine",
    "WindowFeatureVector",
]
