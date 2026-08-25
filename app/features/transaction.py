"""Transaction-level features (PRD §13.1).

These are the features a conventional, agent-unaware payment risk model would have. They
form the ``txn_ml`` baseline on their own, which is what makes the central experiment a
clean ablation: Veyra is these features *plus* behaviour, authorization, graph and
temporal signals.
"""

from __future__ import annotations

import math

from app.features.baselines import DEFAULT_BASELINES, Baselines
from app.features.context import RiskContext
from app.features.util import log1p_amount, safe_div

# Categories with a structurally higher resale/abuse value. Not a verdict on the category:
# a single flag among seventy features, and legitimate purchases in them are common.
ELEVATED_RISK_CATEGORIES = {"gift_cards", "gaming", "electronics", "travel", "alcohol"}

TRANSACTION_FEATURE_NAMES = [
    "txn_amount_log",
    "txn_amount_zscore",
    "txn_amount_ratio_customer_mean",
    "txn_amount_ratio_customer_max",
    "txn_amount_ratio_category_median",
    "txn_retry_count",
    "txn_is_retry",
    "txn_quantity",
    "txn_quantity_log",
    "txn_has_coupon",
    "txn_coupon_value_log",
    "txn_coupon_ratio",
    "txn_hour_sin",
    "txn_hour_cos",
    "txn_is_night",
    "txn_is_weekend",
    "txn_is_agent_initiated",
    "txn_customer_txn_count_log",
    "txn_customer_is_new",
    "txn_customer_account_age_hours",
    "txn_customer_failure_rate",
    "txn_customer_distinct_merchants",
    "txn_customer_distinct_devices",
    "txn_category_elevated_risk",
    "txn_status_failed",
    "txn_method_is_card_token",
]


def transaction_features(ctx: RiskContext, baselines: Baselines | None = None) -> dict[str, float]:
    baselines = baselines or DEFAULT_BASELINES
    txn = ctx.transaction
    history = ctx.customer_history

    std = history.std_amount
    zscore = safe_div(txn.amount - history.mean_amount, std) if history.transaction_count >= 3 else 0.0
    category_median = baselines.amount_median_for(txn.merchant_category)

    hour = txn.timestamp.hour
    age_hours = history.age_seconds / 3600.0

    return {
        "txn_amount_log": log1p_amount(txn.amount),
        # Clamped: a first-ever purchase can produce an arbitrarily large z-score, and an
        # unbounded feature lets one outlier dominate a linear model.
        "txn_amount_zscore": max(-10.0, min(10.0, zscore)),
        "txn_amount_ratio_customer_mean": min(
            50.0, safe_div(txn.amount, history.mean_amount, default=1.0)
        ),
        "txn_amount_ratio_customer_max": min(
            50.0, safe_div(txn.amount, history.max_amount, default=1.0)
        ),
        "txn_amount_ratio_category_median": min(
            50.0, safe_div(txn.amount, category_median, default=1.0)
        ),
        "txn_retry_count": float(min(txn.retry_count, 50)),
        "txn_is_retry": 1.0 if txn.retry_count > 0 else 0.0,
        "txn_quantity": float(min(txn.quantity, 1000)),
        "txn_quantity_log": math.log1p(txn.quantity),
        "txn_has_coupon": 1.0 if txn.coupon_id else 0.0,
        "txn_coupon_value_log": log1p_amount(txn.coupon_value),
        "txn_coupon_ratio": min(1.0, safe_div(txn.coupon_value, txn.amount)),
        # Hour as a circle: 23:00 and 00:00 are adjacent, which a raw integer hides.
        "txn_hour_sin": math.sin(2 * math.pi * hour / 24.0),
        "txn_hour_cos": math.cos(2 * math.pi * hour / 24.0),
        "txn_is_night": 1.0 if hour < 6 or hour >= 23 else 0.0,
        "txn_is_weekend": 1.0 if txn.timestamp.weekday() >= 5 else 0.0,
        "txn_is_agent_initiated": 1.0 if txn.actor_type == "AGENT" else 0.0,
        "txn_customer_txn_count_log": math.log1p(history.transaction_count),
        "txn_customer_is_new": 1.0 if history.transaction_count == 0 else 0.0,
        "txn_customer_account_age_hours": min(24 * 60.0, age_hours),
        "txn_customer_failure_rate": safe_div(history.failed_count, history.transaction_count),
        "txn_customer_distinct_merchants": float(min(history.distinct_merchants, 100)),
        "txn_customer_distinct_devices": float(min(history.distinct_devices, 50)),
        "txn_category_elevated_risk": 1.0 if txn.merchant_category in ELEVATED_RISK_CATEGORIES else 0.0,
        "txn_status_failed": 1.0 if txn.status == "FAILED" else 0.0,
        "txn_method_is_card_token": 1.0 if txn.payment_method == "card_token" else 0.0,
    }
