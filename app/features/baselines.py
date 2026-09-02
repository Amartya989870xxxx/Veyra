"""Robust baseline engine and deviation twin calculations (Phase 3.2 & ADR-002).

Computes robust location (Median) and robust scale (MAD) per merchant, feature,
window size, and hour of week (0..167). Outliers and past fraud spikes cannot poison
MAD, ensuring that the metric designed to catch spikes is not desensitized by them.

Also provides category-level cold-start population baselines.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Sequence

from app.models.entities import BaselineStoreRow
from app.registry import load_features
from app.schemas.enums import BaselineConfidence
from app.windows import WindowSize

MAD_NORMAL_CONSISTENCY_CONSTANT = 1.4826


class BaselineLeak(AssertionError):
    """Raised when a baseline fitted on data from a window's future is applied to it.

    An ``AssertionError`` subclass for the same reason as ``DownstreamLeak`` in
    ``app/registry.py``: this is a correctness invariant, and a violation must be as
    loud in a test as it is in a pipeline. A baseline whose fit period extends past the
    window being scored encodes the future into the "normal" it compares against — the
    metrics look better and the detector cannot run in production, which is exactly the
    failure mode ADR-004 exists to prevent, one layer down.
    """


@dataclass(frozen=True, slots=True)
class BaselineProfile:
    expected_median: float
    variability_mad: float
    sample_count: int
    confidence: BaselineConfidence
    fit_period_start: datetime | None = None
    fit_period_end: datetime | None = None
    """Bounds of the history this profile was fitted on.

    Recorded so the temporal guard in ``compute_deviation_twin`` can refuse to apply a
    baseline to a window that precedes the end of its own fit period. ``None`` means the
    fit period is unknown (hand-constructed profiles in tests), and the guard is skipped
    rather than guessing.
    """


def compute_median_and_mad(values: Sequence[float]) -> tuple[float, float]:
    """Compute sample Median and Median Absolute Deviation (MAD)."""
    if not values:
        return 0.0, 1.0

    med = float(statistics.median(values))
    abs_deviations = [abs(v - med) for v in values]
    raw_mad = float(statistics.median(abs_deviations))

    # Scale by 1.4826 to match standard deviation under normal distribution
    mad = max(1e-4, raw_mad * MAD_NORMAL_CONSISTENCY_CONSTANT)
    return med, mad


class BaselineEngine:
    """Manages versioned merchant baselines and computes deviation twins."""

    def __init__(
        self,
        merchant_baselines: dict[tuple[str, str, str, int], BaselineProfile] | None = None,
        category_baselines: dict[tuple[str, str, str, int], BaselineProfile] | None = None,
        merchant_categories: dict[str, str] | None = None,
        allow_in_fit_period_use: bool = False,
    ) -> None:
        self._baselines = merchant_baselines or {}
        self._category_baselines = category_baselines or {}
        self._merchant_categories = merchant_categories or {}
        self.allow_in_fit_period_use = allow_in_fit_period_use
        """Permit applying a baseline to a window inside its own fit period.

        False everywhere it matters — validation, test, and production scoring — so a
        baseline can only ever be applied *forward* in time. Set True for exactly one
        purpose: transforming the training windows the baseline was itself fitted on,
        which is standard in-sample normalisation (the same thing fitting a scaler on
        TRAIN and transforming TRAIN does) and is confined to model fitting. It never
        touches a number that is reported as held-out performance.
        """

    def with_in_fit_period_use(self, allowed: bool) -> "BaselineEngine":
        """A view over the same fitted profiles with a different in-sample policy."""
        return BaselineEngine(
            merchant_baselines=self._baselines,
            category_baselines=self._category_baselines,
            merchant_categories=self._merchant_categories,
            allow_in_fit_period_use=allowed,
        )

    def __len__(self) -> int:
        return len(self._baselines)

    @property
    def is_fitted(self) -> bool:
        return bool(self._baselines) or bool(self._category_baselines)

    def get_baseline(
        self,
        merchant_id: str,
        feature_id: str,
        window_size: WindowSize | str,
        hour_of_week: int,
    ) -> BaselineProfile:
        w_str = window_size.value if isinstance(window_size, WindowSize) else str(window_size)
        key = (merchant_id, feature_id, w_str, hour_of_week)

        if key in self._baselines:
            return self._baselines[key]

        # Cold-start fallback: category population baseline
        category = self._merchant_categories.get(merchant_id, "retail")
        cat_key = (category, feature_id, w_str, hour_of_week)
        if cat_key in self._category_baselines:
            cat_b = self._category_baselines[cat_key]
            return BaselineProfile(
                expected_median=cat_b.expected_median,
                variability_mad=cat_b.variability_mad,
                sample_count=cat_b.sample_count,
                confidence=BaselineConfidence.LOW,
            )

        # Default fallback if no prior history exists
        return BaselineProfile(
            expected_median=0.0,
            variability_mad=1.0,
            sample_count=0,
            confidence=BaselineConfidence.LOW,
        )

    def compute_deviation_twin(
        self,
        merchant_id: str,
        feature_id: str,
        value: float,
        window_size: WindowSize | str,
        hour_of_week: int,
        window_end: datetime | None = None,
    ) -> tuple[float, BaselineConfidence]:
        """Compute deviation twin: f_dev = (f - median) / max(MAD, 1e-4).

        Pass ``window_end`` to enable the temporal guard. It is optional only for
        backwards compatibility with callers that predate the guard; the feature engine
        always supplies it, so every deviation twin computed in the real pipeline is
        checked.
        """
        baseline = self.get_baseline(merchant_id, feature_id, window_size, hour_of_week)

        if (
            window_end is not None
            and baseline.fit_period_end is not None
            and baseline.fit_period_end > window_end
            and not self.allow_in_fit_period_use
        ):
            raise BaselineLeak(
                f"baseline for {merchant_id}/{feature_id} was fitted on history ending "
                f"{baseline.fit_period_end.isoformat()}, which is after the window ending "
                f"{window_end.isoformat()} it is being applied to. That baseline encodes "
                "the window's own future. Fit on TRAIN only and freeze before scoring "
                "validation/test, or pass allow_in_fit_period_use=True if this is the "
                "in-sample transform of the training set itself."
            )

        dev = (value - baseline.expected_median) / max(1e-4, baseline.variability_mad)
        return float(dev), baseline.confidence


def fit_baselines_from_window_history(
    historical_window_features: Sequence[dict],
    merchant_categories: dict[str, str] | None = None,
) -> BaselineEngine:
    """Fit robust baselines from a training history of window features.

    Each record in historical_window_features:
        {"merchant_id": str, "window_size": str, "window_end": datetime, "features": dict[str, float]}
    """
    # Group observations by (merchant_id, feature_id, window_size, hour_of_week)
    grouped: dict[tuple[str, str, str, int], list[float]] = defaultdict(list)
    cat_grouped: dict[tuple[str, str, str, int], list[float]] = defaultdict(list)

    merchant_cats = merchant_categories or {}

    for record in historical_window_features:
        m_id = record["merchant_id"]
        w_size = record["window_size"]
        w_end: datetime = record["window_end"]
        features_dict: dict[str, float] = record["features"]

        # Hour of week: 0..167
        how = w_end.weekday() * 24 + w_end.hour
        cat = merchant_cats.get(m_id, "retail")

        for f_id, val in features_dict.items():
            grouped[(m_id, f_id, w_size, how)].append(float(val))
            cat_grouped[(cat, f_id, w_size, how)].append(float(val))

    # Bounds of the history actually consumed. Stamped onto every profile so the
    # temporal guard can later prove a baseline was not fitted on a window's future.
    window_ends = [record["window_end"] for record in historical_window_features]
    fit_start = min(window_ends) if window_ends else None
    fit_end = max(window_ends) if window_ends else None

    baselines: dict[tuple[str, str, str, int], BaselineProfile] = {}
    for key, values in grouped.items():
        med, mad = compute_median_and_mad(values)
        count = len(values)
        conf = BaselineConfidence.HIGH if count >= 20 else (BaselineConfidence.MEDIUM if count >= 5 else BaselineConfidence.LOW)
        baselines[key] = BaselineProfile(
            expected_median=med,
            variability_mad=mad,
            sample_count=count,
            confidence=conf,
            fit_period_start=fit_start,
            fit_period_end=fit_end,
        )

    cat_baselines: dict[tuple[str, str, str, int], BaselineProfile] = {}
    for key, values in cat_grouped.items():
        med, mad = compute_median_and_mad(values)
        cat_baselines[key] = BaselineProfile(
            expected_median=med,
            variability_mad=mad,
            sample_count=len(values),
            confidence=BaselineConfidence.MEDIUM,
            fit_period_start=fit_start,
            fit_period_end=fit_end,
        )

    return BaselineEngine(
        merchant_baselines=baselines,
        category_baselines=cat_baselines,
        merchant_categories=merchant_cats,
    )


def build_baseline_engine_from_rows(
    rows: Sequence[BaselineStoreRow],
    merchant_categories: dict[str, str] | None = None,
) -> BaselineEngine:
    """Rehydrate a frozen `BaselineEngine` from persisted `baseline_store` rows.

    This is the "apply unchanged" half of the contract: fitting happens once, offline,
    on training history; scoring loads those frozen parameters and never recomputes
    them. `fit_period_end` round-trips through the database so the temporal guard stays
    armed after a reload — a baseline that was fitted on the future is still rejected
    when it comes back out of storage.
    """
    profiles: dict[tuple[str, str, str, int], BaselineProfile] = {}
    for row in rows:
        try:
            confidence = BaselineConfidence(row.confidence)
        except ValueError:
            confidence = BaselineConfidence.LOW
        profiles[(row.merchant_id, row.feature_id, row.window_size, int(row.hour_of_week))] = (
            BaselineProfile(
                expected_median=float(row.expected_median),
                variability_mad=float(row.variability_mad),
                sample_count=int(row.sample_count or 0),
                confidence=confidence,
                fit_period_start=row.fit_period_start,
                fit_period_end=row.fit_period_end,
            )
        )
    return BaselineEngine(
        merchant_baselines=profiles,
        merchant_categories=merchant_categories or {},
        allow_in_fit_period_use=False,
    )


def baseline_rows_from_engine(
    engine: BaselineEngine,
    version: int = 1,
) -> list[dict]:
    """Flatten a fitted engine into `BaselineStoreRepository.save_baseline` kwargs.

    Returned as plain dicts rather than ORM rows so this module stays free of session
    handling; the caller owns the transaction.
    """
    payload: list[dict] = []
    for (merchant_id, feature_id, window_size, hour_of_week), profile in engine._baselines.items():
        payload.append(
            {
                "merchant_id": merchant_id,
                "feature_id": feature_id,
                "window_size": window_size,
                "hour_of_week": hour_of_week,
                "expected_median": profile.expected_median,
                "variability_mad": profile.variability_mad,
                "sample_count": profile.sample_count,
                "confidence": profile.confidence,
                "version": version,
                "fit_period_start": profile.fit_period_start,
                "fit_period_end": profile.fit_period_end,
            }
        )
    return payload


# Backward-compatible alias
Baselines = BaselineEngine

