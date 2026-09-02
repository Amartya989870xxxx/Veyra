"""Tests enforcing ADR-004: downstream outcomes are label sources ONLY.

Disputes, chargebacks, and RTO events arrive days or weeks after live payment decisions.
Any model trained with downstream-only features or receiving downstream events as real-time
model features suffers from catastrophic temporal leakage.
"""

from __future__ import annotations

import pytest

from app.registry import (
    LABEL_ONLY_EVENT_TYPES,
    DownstreamLeak,
    assert_no_downstream,
    downstream_only_ids,
    load_features,
    load_scenarios,
    model_input_ids,
)
from app.schemas.enums import EventType


def test_dispute_is_label_only_event():
    """ADR-004: Dispute events must be marked as label-only."""
    assert EventType.DISPUTE in LABEL_ONLY_EVENT_TYPES
    assert EventType.PAYMENT_ATTEMPT not in LABEL_ONLY_EVENT_TYPES
    assert EventType.PAYMENT_RESULT not in LABEL_ONLY_EVENT_TYPES


def test_downstream_only_features_cannot_be_model_inputs():
    """Features tagged downstream_only must report is_model_input == False."""
    features = load_features()
    downstream = [f for f in features.values() if f.downstream_only]
    assert len(downstream) > 0, "Expected at least one downstream_only feature in registry"

    for f in downstream:
        assert not f.is_model_input, f"Feature {f.id} is downstream_only but marked as model input"


def test_evidence_only_features_cannot_be_model_inputs():
    """Features tagged evidence_only (raw counts/GMV) must not enter model feature vectors."""
    features = load_features()
    evidence = [f for f in features.values() if f.evidence_only]
    assert len(evidence) > 0, "Expected evidence_only features in registry"

    for f in evidence:
        assert not f.is_model_input, f"Feature {f.id} is evidence_only but marked as model input"


def test_realtime_scenarios_do_not_reference_downstream_only_features():
    """Matrix check C7: Real-time attack/benign scenarios must not use downstream-only features."""
    features = load_features()
    downstream_ids = {f.id for f in features.values() if f.downstream_only}
    scenarios = load_scenarios()

    for sc in scenarios.values():
        used_downstream = set(sc.features) & downstream_ids
        if used_downstream and not sc.is_retrospective:
            pytest.fail(
                f"Real-time scenario '{sc.id}' references downstream-only features: {used_downstream}. "
                "This violates ADR-004 and matrix check C7."
            )


def test_assert_no_downstream_barrier_raises_on_leak():
    """assert_no_downstream must raise DownstreamLeak if downstream features (or _dev twins) are passed."""
    downstream = downstream_only_ids()
    assert len(downstream) > 0

    valid_features = list(model_input_ids())[:5]
    # Valid features pass without error
    assert_no_downstream(valid_features)

    # Adding a downstream feature must raise DownstreamLeak
    sample_downstream = next(iter(downstream))
    with pytest.raises(DownstreamLeak, match="downstream-only signals reached a model input"):
        assert_no_downstream(valid_features + [sample_downstream])

    # Adding a downstream _dev twin must also raise DownstreamLeak
    with pytest.raises(DownstreamLeak, match="downstream-only signals reached a model input"):
        assert_no_downstream(valid_features + [f"{sample_downstream}_dev"])
