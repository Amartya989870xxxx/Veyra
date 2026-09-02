"""Typed access to the executable research matrix.

`research/matrix.yaml` and `research/features.yaml` are the single source that drives the
scenario generator (Phase 2), the feature registry (Phase 3) and the evaluation slices
(Phase 5). Reading them through one loader is what keeps those three from drifting: a
scenario added to the matrix appears everywhere, and a feature deleted from the registry
breaks every consumer loudly instead of silently producing a column of zeros.

This module also owns **the downstream barrier** (ADR-004), which is the reason it exists
in Phase 1 rather than Phase 3. Disputes, chargebacks and RTO outcomes are the strongest
available evidence that a transaction was fraudulent, and they arrive 14-90 days after the
decision has to be made. A model trained on them scores beautifully offline and cannot
run in production - and the failure is silent, because nothing errors. The metrics simply
become fiction.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from app.schemas.enums import EventType, ScenarioClass

RESEARCH_DIR = Path(__file__).resolve().parents[1] / "research"

LABEL_ONLY_EVENT_TYPES: frozenset[EventType] = frozenset({EventType.DISPUTE})
"""Event kinds that may only ever produce labels, never real-time features.

Order status is not listed: ``SHIPPED`` is observable within the hour and is legitimate
input. Its late terminal state, ``RTO``, is barred through the feature registry instead
(``I.rto_rate`` carries ``downstream_only``), because the constraint is really about *when
the value is known*, not about which event carried it.

Refunds are deliberately absent too. A merchant initiates a refund within minutes to days,
so it is genuinely observable in near-real time; ``I.refund_latency_median`` measures that
delay rather than assuming it away (ADR-004).
"""


class DownstreamLeak(AssertionError):
    """Raised when a downstream-only signal reaches a model input.

    An ``AssertionError`` subclass on purpose: this is a correctness invariant, and it
    should be as loud in a test as it is in a pipeline.
    """


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    id: str
    family: str
    description: str
    deviation_twin: bool = False
    evidence_only: bool = False
    downstream_only: bool = False

    @property
    def is_model_input(self) -> bool:
        """May this feature enter a feature vector?

        ``evidence_only`` features (raw counts, GMV) are excluded not because they leak
        but because they do not transfer across merchant sizes - a count of 500 means
        something different for a 50-order/day merchant than a 50,000-order/day one. They
        stay in the registry because a human reading an incident needs them.
        """
        return not self.downstream_only and not self.evidence_only


@dataclass(frozen=True, slots=True)
class ScenarioSpec:
    id: str
    scenario_class: ScenarioClass
    label: str
    family: str
    mechanism: str
    confusable_with: tuple[str, ...]
    discriminator: str
    features: tuple[str, ...]
    time_scale: tuple[str, ...]
    synthetic_recipe: dict
    real_data_proxy: tuple[str, ...]
    eval_metric: tuple[str, ...] = ()

    @property
    def is_attack(self) -> bool:
        return self.scenario_class is ScenarioClass.ATTACK

    @property
    def is_retrospective(self) -> bool:
        return "retrospective_label_quality" in self.eval_metric

    @property
    def forbidden_single_separators(self) -> tuple[str, ...]:
        """Features that must not separate this scenario alone (matrix check C6).

        The per-scenario half of the anti-leakage contract: the generator must keep these
        overlapping with normal traffic, and gate G1 checks that it did.
        """
        value = (self.synthetic_recipe or {}).get("forbid_single_feature_separability")
        if isinstance(value, list):
            return tuple(value)
        return ()


def _load_yaml(name: str) -> dict:
    return yaml.safe_load((RESEARCH_DIR / name).read_text())


@lru_cache(maxsize=1)
def load_features() -> dict[str, FeatureSpec]:
    raw = _load_yaml("features.yaml")
    specs = {}
    for entry in raw["features"]:
        specs[entry["id"]] = FeatureSpec(
            id=entry["id"],
            family=entry["family"],
            description=entry.get("desc", ""),
            deviation_twin=bool(entry.get("deviation_twin", False)),
            evidence_only=bool(entry.get("evidence_only", False)),
            downstream_only=bool(entry.get("downstream_only", False)),
        )
    return specs


@lru_cache(maxsize=1)
def load_families() -> dict[str, str]:
    return {k: v["name"] for k, v in _load_yaml("features.yaml")["families"].items()}


@lru_cache(maxsize=1)
def load_scenarios() -> dict[str, ScenarioSpec]:
    raw = _load_yaml("matrix.yaml")
    specs = {}
    for entry in raw["scenarios"]:
        specs[entry["id"]] = ScenarioSpec(
            id=entry["id"],
            scenario_class=ScenarioClass(entry["class"]),
            label=entry["label"],
            family=entry.get("family", ""),
            mechanism=entry.get("mechanism", "").strip(),
            confusable_with=tuple(entry.get("confusable_with") or ()),
            discriminator=entry.get("discriminator", "").strip(),
            features=tuple(entry.get("features") or ()),
            time_scale=tuple(entry.get("time_scale") or ()),
            synthetic_recipe=entry.get("synthetic_recipe") or {},
            real_data_proxy=tuple(entry.get("real_data_proxy") or ()),
            eval_metric=tuple(entry.get("eval_metric") or ()),
        )
    return specs


def downstream_only_ids() -> frozenset[str]:
    """Features whose value is not known when the decision must be made."""
    return frozenset(f.id for f in load_features().values() if f.downstream_only)


def model_input_ids() -> frozenset[str]:
    """Every feature permitted to enter a feature vector."""
    return frozenset(f.id for f in load_features().values() if f.is_model_input)


def assert_no_downstream(feature_names: object) -> None:
    """The barrier. Call it wherever a feature vector is assembled.

    Deviation twins are checked too: ``I.dispute_rate_dev`` leaks exactly as much as
    ``I.dispute_rate`` does, and the ``_dev`` suffix is precisely the kind of detail that
    slips past a code review.
    """
    if isinstance(feature_names, str) or not hasattr(feature_names, "__iter__"):
        raise TypeError("feature_names must be an iterable of feature ids")

    banned = downstream_only_ids()
    leaked = sorted(
        name
        for name in feature_names
        if name in banned or (name.endswith("_dev") and name[: -len("_dev")] in banned)
    )
    if leaked:
        raise DownstreamLeak(
            "downstream-only signals reached a model input: "
            f"{leaked}. These are known 14-90 days after the decision (ADR-004); they may "
            "label a window but never feed one. If this is an offline analysis, name it "
            "explicitly rather than routing it through the feature path."
        )
