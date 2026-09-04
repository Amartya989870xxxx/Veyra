"""The demo scoring path's model lifecycle (Part 1A).

Veyra has three scoring paths, and this module is what makes the third one honest:

1. **Production/serving** (`app/serving/scoring_service.py`) — an intentionally unfitted
   `VeyraFusionDetector` today; no model is persisted anywhere in the repository, so it
   falls back to a heuristic. That gap is real and is not something this module hides or
   papers over — see its own docstring.
2. **Offline evaluation** (`app/evaluation/runner.py`, `scripts/run_experiment.py`) — the
   temporally-split, multi-seed benchmark. Unchanged by this module.
3. **Demo** (`app/api/v2/demo.py`) — this module. It fits a real `VeyraFusionDetector` on
   a real synthetic corpus, exactly once per process, and every `/v2/demo/simulate` call
   after that scores freshly generated traffic with the *same* fitted detector. The
   requested scenario's ground-truth attack label is never read by this class and never
   reaches `score()` — see `app/api/v2/demo.py` for where that separation is enforced.

Temporal integrity, adapted for a demo rather than a chronological benchmark
--------------------------------------------------------------------------
The offline evaluation's TRAIN/VALIDATION/TEST discipline doesn't map directly onto "the
user just clicked Run" — there is no held-out future to score once. What *does* transfer,
and what this class preserves, is the actual invariant that discipline protects: **the
model must never be fit on the data it is about to score.**

That is guaranteed structurally, not by hoping seeds don't collide:

- Training data is drawn from a fixed historical window, `TRAINING_START` through
  `TRAINING_START + TRAINING_DAYS`, ending 2026-02-26 — a full week before the earliest
  `now` any demo request uses (2026-03-02, hardcoded in `app/api/v2/demo.py`).
- Every `/v2/demo/simulate` call generates its own transactions *after* training has
  already completed and been frozen, for a merchant profile the training corpus never
  saw (a fresh `generate_merchant_population(n_merchants=1, seed=req.seed)` call, not
  one of the `TRAINING_MERCHANTS` profiles built here).

Because the two time ranges never overlap, a demo window cannot be part of the training
corpus regardless of what seed a request happens to pass.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.decision.operating_point import OperatingThresholds, choose_operating_thresholds
from app.evaluation.indexing import TransactionWindowIndex
from app.features.baselines import BaselineEngine, fit_baselines_from_window_history
from app.features.engine import FeatureEngine
from app.models_ml.fusion import VeyraFusionDetector
from app.schemas.enums import SplitName, WindowLabel
from data.generators.pipeline import generate_benchmark_dataset
from data.generators.timeline import AnnotatedTransaction

MODEL_NAME = "veyra_fusion_demo"
MODEL_VERSION = "demo-1"

TRAINING_SEED = 20260226
"""A fixed constant, independent of any request-supplied seed. Even if a caller's
`req.seed` happened to equal this value, TRAINING_START (below) is what actually
prevents overlap — the seed is fixed for reproducibility, not as the safety mechanism."""

TRAINING_START = datetime(2026, 2, 16, 0, 0, 0, tzinfo=UTC)
"""A **Monday** 00:00, paired with `TRAINING_DAYS = 7` below so the corpus covers all 168
hour-of-week baseline buckets. This is not cosmetic: baselines are keyed by
`(merchant, feature, window_size, hour_of_week)`, so a corpus spanning only part of a
week leaves the demo window's own bucket unfitted, the category fallback misses, and
every `_dev` twin silently collapses to `(value - 0)/1` — a duplicate of its raw feature.
That is exactly the inert-baseline failure `research/BENCHMARK_RESULTS.md` §6 documents,
and covering the full week is what prevents it here."""

TRAINING_DAYS = 7
TRAINING_MERCHANTS = 1
TRAINING_INJECTIONS_PER_SPLIT = 3
TRAINING_HARD_NEGATIVE_RATIO = 0.40
"""One merchant over a full week keeps the fit to roughly the same cost as the
two-merchant/three-day corpus it replaced, while buying complete hour-of-week coverage.
This model exists to make the demo honest, not to be the most statistically powerful
detector in the repository — that job belongs to `scripts/run_experiment.py`."""


class DemoModelUntrained(RuntimeError):
    """Raised if `score()` is somehow reached before training. Should be unreachable —
    every public method routes through `ensure_trained()` first."""


def _monotonic(t: OperatingThresholds) -> OperatingThresholds:
    """Force alert <= review <= restrict for the demo path only.

    `choose_operating_thresholds` derives the outer tiers by offsetting the chosen review
    threshold and then clamping: `theta_alert = max(0.15, review - 0.20)`. When the
    expected-loss sweep picks a review threshold below 0.35 — which this demo corpus
    does, because its validation split is small and cheap — the clamp pushes `theta_alert`
    *above* `theta_review`. `DecisionPolicy.evaluate` tests restrict, then review, then
    alert, so an inverted pair makes the ALERT tier unreachable: anything clearing the
    alert bar has already cleared review.

    This is a pre-existing property of `app/decision/operating_point.py`, which the
    offline evaluation harness also consumes. It is deliberately **not** fixed there:
    changing how thresholds are derived would change the published benchmark's
    methodology, which is out of scope for demo work. The correction is applied here,
    where it only affects the demo path, and the upstream behaviour is left for a
    decision that can be made against the benchmark rather than around it.
    """
    ordered = sorted((t.theta_alert, t.theta_review, t.theta_restrict))
    return OperatingThresholds(
        theta_alert=ordered[0],
        theta_review=ordered[1],
        theta_restrict=ordered[2],
        expected_loss=t.expected_loss,
        review_rate=t.review_rate,
    )


@dataclass(frozen=True, slots=True)
class DemoModelInfo:
    model_name: str
    model_version: str
    trained_at: datetime
    training_seed: int
    training_window_start: datetime
    training_window_end: datetime
    training_transactions: int
    training_windows: int
    training_positive_windows: int
    thresholds: OperatingThresholds
    train_duration_ms: float


def _extract_split(
    labels,
    engine: FeatureEngine,
    index: TransactionWindowIndex,
) -> tuple[list[dict[str, float]], list[int]]:
    X: list[dict[str, float]] = []
    y: list[int] = []
    for w in labels:
        txns: list[AnnotatedTransaction] = index.slice(
            merchant_id=w.merchant_id,
            start=w.window_end - w.window_size.delta,
            end=w.window_end,
        )
        vec = engine.extract_window_features(
            merchant_id=w.merchant_id,
            window_size=w.window_size,
            window_end=w.window_end,
            transactions=txns,
        )
        X.append(vec.model_features)
        y.append(1 if w.label is WindowLabel.FRAUD_SPIKE else 0)
    return X, y


class DemoModelService:
    """Fits `VeyraFusionDetector` once, on first use, and caches it for the process
    lifetime. Thread-safe: FastAPI can serve concurrent requests, and only one of them
    should pay the training cost.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._detector: VeyraFusionDetector | None = None
        self._baseline_engine: BaselineEngine | None = None
        self._info: DemoModelInfo | None = None

    @property
    def is_ready(self) -> bool:
        return self._detector is not None

    def ensure_trained(self) -> tuple[DemoModelInfo, bool]:
        """Return `(info, trained_this_call)`. Trains on the first call across the whole
        process; every call after that reuses the cached detector and baselines."""
        if self._info is not None:
            return self._info, False
        with self._lock:
            if self._info is not None:  # another thread won the race while we waited
                return self._info, False
            self._train()
            assert self._info is not None
            return self._info, True

    def _train(self) -> None:
        t0 = time.perf_counter()
        dataset = generate_benchmark_dataset(
            n_merchants=TRAINING_MERCHANTS,
            days=TRAINING_DAYS,
            start_date=TRAINING_START,
            seed=TRAINING_SEED,
            injections_per_split_per_merchant=TRAINING_INJECTIONS_PER_SPLIT,
            hard_negative_ratio=TRAINING_HARD_NEGATIVE_RATIO,
        )

        train_labels = [
            w for w in dataset.window_labels
            if dataset.split_for_timestamp(w.window_end) == SplitName.TRAIN
        ]
        val_labels = [
            w for w in dataset.window_labels
            if dataset.split_for_timestamp(w.window_end) == SplitName.VALIDATION
        ]

        index = TransactionWindowIndex(dataset.transactions)

        # Pass 1: raw TRAIN features from an unfitted engine — the only input to fitting.
        raw_engine = FeatureEngine()
        X_train_raw, _ = _extract_split(train_labels, raw_engine, index)

        baseline_engine = fit_baselines_from_window_history(
            [
                {
                    "merchant_id": w.merchant_id,
                    "window_size": w.window_size.value,
                    "window_end": w.window_end,
                    "features": {k: v for k, v in feats.items() if not k.endswith("_dev")},
                }
                for w, feats in zip(train_labels, X_train_raw, strict=False)
            ]
        )

        # Pass 2: TRAIN transformed in-sample; VALIDATION through the strict engine —
        # the same temporal contract app/evaluation/runner.py uses.
        train_engine = FeatureEngine(baseline_engine=baseline_engine.with_in_fit_period_use(True))
        scoring_engine = FeatureEngine(baseline_engine=baseline_engine)

        X_train, y_train = _extract_split(train_labels, train_engine, index)
        X_val, y_val = _extract_split(val_labels, scoring_engine, index)

        n_positive = sum(y_train) + sum(y_val)
        if sum(y_train) == 0 or (len(set(y_train)) < 2):
            # A gradient-boosted classifier needs both classes to fit at all. This would
            # mean the fixed training seed/window produced a degenerate split — a
            # configuration bug, not a runtime condition to paper over with a fallback.
            raise RuntimeError(
                "Demo model training corpus produced no FRAUD_SPIKE windows in TRAIN "
                f"(seed={TRAINING_SEED}, start={TRAINING_START.isoformat()}, "
                f"days={TRAINING_DAYS}). Increase TRAINING_MERCHANTS or "
                "TRAINING_INJECTIONS_PER_SPLIT rather than scoring with an unfit model."
            )

        detector = VeyraFusionDetector(name=MODEL_NAME)
        detector.fit(X_train, y_train)

        if X_val:
            val_probs = detector.predict_proba(X_val)
            thresholds = _monotonic(choose_operating_thresholds(y_true=y_val, y_prob=val_probs))
        else:
            thresholds = OperatingThresholds()

        train_ms = (time.perf_counter() - t0) * 1000.0

        self._detector = detector
        self._baseline_engine = baseline_engine
        self._info = DemoModelInfo(
            model_name=MODEL_NAME,
            model_version=MODEL_VERSION,
            trained_at=datetime.now(UTC),
            training_seed=TRAINING_SEED,
            training_window_start=TRAINING_START,
            training_window_end=TRAINING_START + timedelta(days=TRAINING_DAYS),
            training_transactions=len(dataset.transactions),
            training_windows=len(train_labels) + len(val_labels),
            training_positive_windows=n_positive,
            thresholds=thresholds,
            train_duration_ms=train_ms,
        )

    def feature_engine_for_scoring(self) -> FeatureEngine:
        """A `FeatureEngine` wired to the fitted, frozen baselines — the same ones the
        detector was trained against. Must be used to score demo windows; scoring with a
        differently-baselined engine would feed the detector deviation twins it was never
        trained on."""
        self.ensure_trained()
        assert self._baseline_engine is not None
        return FeatureEngine(baseline_engine=self._baseline_engine)

    def score(self, feature_vectors: list[dict[str, float]]) -> list[float]:
        self.ensure_trained()
        if self._detector is None:
            raise DemoModelUntrained("scored before training completed")
        return [float(p) for p in self._detector.predict_proba(feature_vectors)]

    @property
    def thresholds(self) -> OperatingThresholds:
        info, _ = self.ensure_trained()
        return info.thresholds

    @property
    def info(self) -> DemoModelInfo:
        info, _ = self.ensure_trained()
        return info


_singleton: DemoModelService | None = None
_singleton_lock = threading.Lock()


def get_demo_model_service() -> DemoModelService:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = DemoModelService()
    return _singleton


def reset_demo_model_service() -> None:
    """Test-only: drop the cached singleton so a test can observe a fresh training call."""
    global _singleton
    with _singleton_lock:
        _singleton = None
