"""Integration test for end-to-end synthetic dataset benchmark generation (Phase 2)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.schemas.enums import SplitName, WindowLabel
from data.generators.pipeline import generate_benchmark_dataset


def test_generate_benchmark_dataset_pipeline():
    """Verify that complete benchmark dataset generates clean transactions, window labels, and temporal splits."""
    start_ts = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)
    dataset = generate_benchmark_dataset(
        n_merchants=3,
        days=2,
        start_date=start_ts,
        inject_scenarios=True,
        seed=42,
    )

    assert len(dataset.merchants) == 3
    assert len(dataset.transactions) > 0
    assert len(dataset.window_labels) > 0

    # Verify temporal split boundaries
    assert dataset.train_split_end > start_ts
    assert dataset.val_split_end > dataset.train_split_end
    assert dataset.test_split_end > dataset.val_split_end

    # Check temporal split assignment helper
    assert dataset.split_for_timestamp(start_ts) == SplitName.TRAIN
    assert dataset.split_for_timestamp(dataset.train_split_end) == SplitName.VALIDATION
    assert dataset.split_for_timestamp(dataset.val_split_end) == SplitName.TEST

    # Verify window label distribution
    label_types = {w.label for w in dataset.window_labels}
    assert WindowLabel.NORMAL in label_types
