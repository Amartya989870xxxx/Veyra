"""Training pipeline for the Veyra model bundle.

Protocol, in order, and the reason for each step:

1. **Component models fit on train.** Three estimators on three disjoint feature slices.
2. **Out-of-fold component scores on train, with grouped folds.** Fitting the fusion layer
   on in-sample component predictions would show it over-confident inputs it will never see
   at inference; grouped folds additionally stop a campaign from appearing on both sides of
   a fold boundary.
3. **Fusion fit on those out-of-fold scores.**
4. **Baseline 2 fit on train**, same estimator and seed.

The validation split is used afterwards, by the runner, to choose operating points. The
holdout is touched exactly once, for reporting.
"""

from __future__ import annotations

import numpy as np

from app.core.logging import get_logger
from app.evaluation.detectors import intent_deviations, rule_scores
from app.evaluation.scoring import FeatureFrame
from app.features.engine import COMPONENT_FEATURES, TRANSACTION_ONLY_FEATURES
from app.risk.fusion import COMPONENT_ORDER, fusion_matrix
from app.risk.models import ComponentModel, FusionModel, ModelBundle, out_of_fold_scores
from app.risk.rules import RuleEngine

log = get_logger(__name__)


def train_bundle(
    train: FeatureFrame,
    seed: int = 42,
    dataset_id: str | None = None,
    rule_engine: RuleEngine | None = None,
) -> ModelBundle:
    rule_engine = rule_engine or RuleEngine()
    bundle = ModelBundle(seed=seed, dataset_id=dataset_id)

    # 1 + 2: fit each component and collect grouped out-of-fold predictions for the fusion.
    oof: dict[str, np.ndarray] = {}
    for name, feature_names in COMPONENT_FEATURES.items():
        matrix = train.select(feature_names)
        model = ComponentModel(name=name, feature_names=list(feature_names), seed=seed)
        model.fit(matrix, train.labels)
        bundle.components[name] = model
        oof[name] = out_of_fold_scores(matrix, train.labels, train.group_ids, seed=seed)
        log.info(
            "component_trained",
            extra={"component": name, "features": len(feature_names), "rows": len(train)},
        )

    # Deterministic components need no fitting and are identical in and out of sample.
    oof["rule_violation_score"] = rule_scores(train, rule_engine)
    oof["intent_deviation"] = intent_deviations(train)

    # 3: fusion over out-of-fold component scores plus availability flags.
    rows = [
        {
            name: (None if np.isnan(oof[name][i]) else float(oof[name][i]))
            for name in COMPONENT_ORDER
        }
        for i in range(len(train))
    ]
    fusion_inputs = fusion_matrix(rows)
    from app.risk.fusion import FUSION_INPUT_NAMES

    bundle.fusion = FusionModel().fit(fusion_inputs, train.labels, FUSION_INPUT_NAMES)
    log.info("fusion_trained", extra={"weights": bundle.fusion.weights()})

    # 4: transaction-only baseline, same estimator and seed.
    baseline = ComponentModel(
        name="baseline_txn_only", feature_names=list(TRANSACTION_ONLY_FEATURES), seed=seed
    )
    baseline.fit(train.select(TRANSACTION_ONLY_FEATURES), train.labels)
    bundle.baseline_txn_only = baseline

    return bundle
