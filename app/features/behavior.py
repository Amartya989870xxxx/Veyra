"""Agent behaviour features (PRD §13.2).

The central claim these features exist to test is that *how the agent got to the payment*
carries risk information the payment itself does not. The most important feature here is
``beh_action_gap_cv``: legitimate automation is fast but jittered, scripted abuse is fast
and metronomic. Speed alone is deliberately not a risk signal — several legitimate
scenarios in the benchmark are faster than the abusive ones.
"""

from __future__ import annotations

import math

from app.features.context import ActionView, RiskContext
from app.features.util import coefficient_of_variation, entropy, gaps, repeat_gap_ratio, safe_div

PAYMENT_ACTIONS = {"REQUEST_PAYMENT", "RETRY_PAYMENT"}
BROWSE_ACTIONS = {"SEARCH", "VIEW_PRODUCT", "COMPARE_PRICES", "ADD_TO_CART", "TOOL_CALL"}

BEHAVIOR_FEATURE_NAMES = [
    "beh_has_agent",
    "beh_actions_in_session",
    "beh_actions_per_minute",
    "beh_session_duration_s",
    "beh_payment_actions",
    "beh_payment_action_ratio",
    "beh_payments_per_minute",
    "beh_retry_actions",
    "beh_browse_actions",
    "beh_browse_ratio",
    "beh_prepayment_actions",
    "beh_distinct_action_types",
    "beh_action_type_entropy",
    "beh_action_gap_mean",
    "beh_action_gap_cv",
    "beh_action_gap_repeat_ratio",
    "beh_merchant_switches",
    "beh_merchant_switch_rate",
    "beh_sku_switches",
    "beh_sequence_length",
    "beh_agent_txn_count_log",
    "beh_agent_distinct_customers",
    "beh_agent_customers_per_session",
    "beh_agent_failure_rate",
    "beh_agent_rate_deviation",
    "beh_agent_is_new",
]


def _empty() -> dict[str, float]:
    features = dict.fromkeys(BEHAVIOR_FEATURE_NAMES, 0.0)
    features["beh_has_agent"] = 0.0
    return features


def behavior_features(ctx: RiskContext) -> dict[str, float]:
    txn = ctx.transaction
    actions: list[ActionView] = ctx.actions
    agent = ctx.agent_history

    if not txn.agent_id:
        # A human-initiated transaction has no agent trajectory. Zeros here mean "no agent",
        # which `beh_has_agent` disambiguates from "an agent that did nothing".
        return _empty()

    features = _empty()
    features["beh_has_agent"] = 1.0

    if actions:
        timestamps = [a.timestamp for a in actions]
        duration = max(1e-6, (max(timestamps) - min(timestamps)).total_seconds())
        gap_series = gaps(timestamps)
        payment_actions = [a for a in actions if a.action_type in PAYMENT_ACTIONS]
        retry_actions = [a for a in actions if a.action_type == "RETRY_PAYMENT"]
        browse_actions = [a for a in actions if a.action_type in BROWSE_ACTIONS]

        types = [a.action_type for a in actions]
        type_counts = [types.count(t) for t in set(types)]

        merchants = [a.merchant_id for a in actions if a.merchant_id]
        merchant_switches = sum(
            1 for i in range(1, len(merchants)) if merchants[i] != merchants[i - 1]
        )
        skus = [a.sku_id for a in actions if a.sku_id]
        sku_switches = sum(1 for i in range(1, len(skus)) if skus[i] != skus[i - 1])

        # Actions that happened before the first payment request: the discovery trajectory.
        first_payment_index = next(
            (i for i, a in enumerate(actions) if a.action_type in PAYMENT_ACTIONS), len(actions)
        )

        features.update(
            {
                "beh_actions_in_session": float(len(actions)),
                "beh_actions_per_minute": len(actions) / (duration / 60.0),
                "beh_session_duration_s": duration,
                "beh_payment_actions": float(len(payment_actions)),
                "beh_payment_action_ratio": safe_div(len(payment_actions), len(actions)),
                "beh_payments_per_minute": len(payment_actions) / (duration / 60.0),
                "beh_retry_actions": float(len(retry_actions)),
                "beh_browse_actions": float(len(browse_actions)),
                "beh_browse_ratio": safe_div(len(browse_actions), len(actions)),
                "beh_prepayment_actions": float(first_payment_index),
                "beh_distinct_action_types": float(len(set(types))),
                "beh_action_type_entropy": entropy(type_counts),
                "beh_action_gap_mean": (
                    sum(gap_series) / len(gap_series) if gap_series else 0.0
                ),
                "beh_action_gap_cv": coefficient_of_variation(gap_series),
                "beh_action_gap_repeat_ratio": repeat_gap_ratio(gap_series),
                "beh_merchant_switches": float(merchant_switches),
                "beh_merchant_switch_rate": safe_div(merchant_switches, max(1, len(merchants) - 1)),
                "beh_sku_switches": float(sku_switches),
                "beh_sequence_length": float(actions[-1].sequence_number + 1),
            }
        )

    observed_rate = features["beh_actions_per_minute"]
    features.update(
        {
            "beh_agent_txn_count_log": math.log1p(agent.transaction_count),
            "beh_agent_distinct_customers": float(min(agent.distinct_customers, 500)),
            "beh_agent_customers_per_session": safe_div(
                agent.distinct_customers, max(1, agent.session_count)
            ),
            "beh_agent_failure_rate": safe_div(agent.failed_count, agent.transaction_count),
            # How far this session deviates from what this agent normally does. An agent
            # that is always fast is not suspicious for being fast again.
            "beh_agent_rate_deviation": (
                min(20.0, safe_div(observed_rate, agent.mean_actions_per_minute, default=0.0))
                if agent.mean_actions_per_minute > 0
                else 0.0
            ),
            "beh_agent_is_new": 1.0 if agent.transaction_count == 0 else 0.0,
        }
    )
    return features
