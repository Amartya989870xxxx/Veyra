#!/usr/bin/env python3
"""Measure how separable the synthetic data is, feature by feature.

This is the evidence behind the "why is Fusion so strong?" answer in
research/BENCHMARK_RESULTS.md, made reproducible so a reviewer does not have to take the
claim on trust.

It reports, for a generated dataset:
  * the univariate ROC-AUC of every single feature against the window label
  * the class-conditional distribution of the strongest features
  * how much the two classes actually overlap on those features

A feature approaching 1.0 univariate AUC means the generator, not the model, is doing the
work: no ensemble is needed to separate classes that one column already separates. That
is a property of synthetic data and a limit on what the benchmark can claim, which is
why it is measured and published rather than left implicit.

Usage:
    PYTHONPATH=. python scripts/audit_feature_separability.py [--merchants 3] [--days 3]
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

import numpy as np
from sklearn.metrics import roc_auc_score

from app.evaluation.indexing import TransactionWindowIndex
from app.features.engine import FeatureEngine
from app.schemas.enums import WindowLabel
from data.generators.pipeline import generate_benchmark_dataset


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--merchants", type=int, default=3)
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--injections", type=int, default=3)
    parser.add_argument("--top", type=int, default=12)
    args = parser.parse_args()

    dataset = generate_benchmark_dataset(
        n_merchants=args.merchants,
        days=args.days,
        start_date=datetime(2026, 3, 1, tzinfo=UTC),
        inject_scenarios=True,
        seed=args.seed,
        injections_per_split_per_merchant=args.injections,
    )

    index = TransactionWindowIndex(dataset.transactions)
    # Deliberately unfitted: this audit asks what the *raw* generated signal looks like,
    # independent of any baseline normalisation.
    engine = FeatureEngine()

    X, y = [], []
    for w in dataset.window_labels:
        txns = index.slice(w.merchant_id, w.window_end - w.window_size.delta, w.window_end)
        if not txns:
            continue
        vec = engine.extract_window_features(w.merchant_id, w.window_size, w.window_end, txns)
        X.append(vec.all_features)
        y.append(1 if w.label is WindowLabel.FRAUD_SPIKE else 0)

    y_arr = np.array(y)
    print(f"windows={len(y_arr):,}  positives={int(y_arr.sum()):,}  base rate={y_arr.mean():.3%}")
    if y_arr.sum() == 0:
        print("no positive windows — nothing to measure")
        return 1

    aucs = []
    for key in sorted(X[0].keys()):
        col = np.array([row.get(key, 0.0) for row in X])
        if np.std(col) < 1e-12:
            continue
        auc = roc_auc_score(y_arr, col)
        aucs.append((max(auc, 1.0 - auc), key))
    aucs.sort(reverse=True)

    print(f"\nTop {args.top} single-feature AUCs (1.0 = this column alone separates the classes):")
    for auc, key in aucs[: args.top]:
        print(f"  {auc:.4f}  {key}")

    all_aucs = [a for a, _ in aucs]
    print(f"\nmax={max(all_aucs):.4f}  median={np.median(all_aucs):.4f}  n_features={len(all_aucs)}")

    print("\nClass overlap on the strongest feature:")
    top_key = aucs[0][1]
    pos = np.array([row.get(top_key, 0.0) for row, lab in zip(X, y) if lab == 1])
    neg = np.array([row.get(top_key, 0.0) for row, lab in zip(X, y) if lab == 0])
    print(f"  {top_key}")
    print(f"    attack : mean={pos.mean():.3f}  p05={np.percentile(pos,5):.3f}  p95={np.percentile(pos,95):.3f}")
    print(f"    legit  : mean={neg.mean():.3f}  p05={np.percentile(neg,5):.3f}  p95={np.percentile(neg,95):.3f}")
    overlap = float(((neg >= np.percentile(pos, 5)) & (neg <= np.percentile(pos, 95))).mean())
    print(f"    share of legitimate windows inside the attack p05-p95 band: {overlap:.1%}")
    print(
        "\nReading: a low overlap share on a near-1.0 AUC feature means the generator "
        "places the two classes in almost disjoint regions of that feature. Real traffic "
        "overlaps far more, so treat headline scores as an upper bound."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
