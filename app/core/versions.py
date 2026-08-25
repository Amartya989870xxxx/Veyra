"""Version constants.

Every risk decision persists these so it can be reconstructed later (PRD §7 Principle 7).
Bump a version whenever the corresponding logic changes in a way that would alter output.
"""

SCHEMA_VERSION = "1.0"
"""Canonical event/contract schema version accepted by the ingestion layer."""

POLICY_VERSION = "risk-policy-v1"
"""Decision policy (thresholds + hard rules) version."""

FEATURE_VERSION = "features-v1"
"""Feature engine version. Bump when a feature definition changes."""

RULES_VERSION = "rules-v1"
"""Deterministic rule pack version."""

GRAPH_VERSION = "graph-networkx-v1"
"""Graph engine implementation version."""

FUSION_VERSION = "fusion-lr-v1"
"""Risk fusion model family version."""

APP_VERSION = "0.1.0"
