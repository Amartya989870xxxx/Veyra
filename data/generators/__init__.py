"""Veyra v2 synthetic benchmark data generator package (Phase 2)."""

from data.generators.injection import inject_scenario_into_timeline
from data.generators.lifting import ScoredWindowLabel, compute_label_sensitivity, lift_labels_to_windows
from data.generators.pipeline import SyntheticDataset, generate_benchmark_dataset
from data.generators.population import MerchantProfile, generate_merchant_population
from data.generators.recipes import SCENARIO_RECIPES
from data.generators.timeline import AnnotatedTransaction, generate_organic_timeline

__all__ = [
    "MerchantProfile",
    "generate_merchant_population",
    "AnnotatedTransaction",
    "generate_organic_timeline",
    "SCENARIO_RECIPES",
    "inject_scenario_into_timeline",
    "ScoredWindowLabel",
    "lift_labels_to_windows",
    "compute_label_sensitivity",
    "SyntheticDataset",
    "generate_benchmark_dataset",
]
