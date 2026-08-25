"""Authorization / delegated-intent features and deterministic constraint checks (PRD §13.3, §15).

Everything in this module is deterministic. The optional semantic layer may later add a
*mismatch score* on top, but it can never relax a constraint decided here: hard limits are
evaluated in ``Decimal``-equivalent float comparisons against the typed delegation, not
against anything a model produced.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.features.context import RiskContext
from app.features.util import safe_div

AUTHORIZATION_FEATURE_NAMES = [
    "auth_present",
    "auth_amount_within_max",
    "auth_amount_ratio_to_max",
    "auth_amount_over_max",
    "auth_category_allowed",
    "auth_category_forbidden",
    "auth_merchant_allowed",
    "auth_active",
    "auth_expired",
    "auth_not_yet_valid",
    "auth_age_days",
    "auth_time_to_expiry_days",
    "auth_requires_approval",
    "auth_agent_matches",
    "auth_customer_matches",
    "auth_currency_matches",
    "auth_violation_count",
    "auth_hard_violation",
]


@dataclass(frozen=True)
class AuthorizationViolation:
    """A hard constraint breach. These can bypass score thresholds in the policy engine."""

    code: str
    detail: str
    observed_value: float | None = None
    expected_value: float | None = None
    hard: bool = True


def check_authorization(ctx: RiskContext) -> list[AuthorizationViolation]:
    """Deterministic constraint evaluation. Returns every violation found, in a stable order."""
    delegation = ctx.delegation
    txn = ctx.transaction
    if delegation is None:
        return []

    violations: list[AuthorizationViolation] = []

    if txn.timestamp > delegation.expires_at:
        violations.append(
            AuthorizationViolation(
                code="delegation_expired",
                detail=(
                    f"delegation expired at {delegation.expires_at.isoformat()}, "
                    f"transaction at {txn.timestamp.isoformat()}"
                ),
                observed_value=(txn.timestamp - delegation.expires_at).total_seconds(),
                expected_value=0.0,
            )
        )
    if txn.timestamp < delegation.issued_at:
        violations.append(
            AuthorizationViolation(
                code="delegation_not_yet_valid",
                detail=f"delegation is not valid until {delegation.issued_at.isoformat()}",
            )
        )

    category = txn.merchant_category.lower()
    if category in {c.lower() for c in delegation.forbidden_categories}:
        violations.append(
            AuthorizationViolation(
                code="forbidden_category",
                detail=f"category '{category}' is explicitly forbidden by the delegation",
            )
        )
    elif delegation.allowed_categories and category not in {
        c.lower() for c in delegation.allowed_categories
    }:
        violations.append(
            AuthorizationViolation(
                code="category_not_allowed",
                detail=(
                    f"category '{category}' is outside the delegated set "
                    f"{sorted(delegation.allowed_categories)}"
                ),
                hard=False,
            )
        )

    if txn.amount > delegation.max_amount:
        violations.append(
            AuthorizationViolation(
                code="amount_exceeds_delegation",
                detail=(
                    f"amount {txn.amount:.2f} exceeds delegated maximum "
                    f"{delegation.max_amount:.2f}"
                ),
                observed_value=txn.amount,
                expected_value=delegation.max_amount,
            )
        )

    if delegation.merchant_policy == "allowlist_only" and delegation.allowed_merchants:
        if txn.merchant_id not in delegation.allowed_merchants:
            violations.append(
                AuthorizationViolation(
                    code="merchant_not_allowlisted",
                    detail=f"merchant {txn.merchant_id} is not on the delegation allowlist",
                )
            )

    if txn.currency.upper() != delegation.currency.upper():
        violations.append(
            AuthorizationViolation(
                code="currency_mismatch",
                detail=f"transaction currency {txn.currency} != delegated {delegation.currency}",
            )
        )

    if txn.agent_id and delegation.agent_id and txn.agent_id != delegation.agent_id:
        violations.append(
            AuthorizationViolation(
                code="agent_mismatch",
                detail=f"agent {txn.agent_id} is not the delegated agent {delegation.agent_id}",
            )
        )
    if txn.customer_id != delegation.customer_id:
        violations.append(
            AuthorizationViolation(
                code="customer_mismatch",
                detail=f"delegation belongs to {delegation.customer_id}, not {txn.customer_id}",
            )
        )

    if (
        delegation.approval_required_above is not None
        and txn.amount > delegation.approval_required_above
    ):
        violations.append(
            AuthorizationViolation(
                code="approval_required",
                detail=(
                    f"amount {txn.amount:.2f} is above the approval threshold "
                    f"{delegation.approval_required_above:.2f} and no approval is recorded"
                ),
                observed_value=txn.amount,
                expected_value=delegation.approval_required_above,
                hard=False,
            )
        )

    return violations


def authorization_features(
    ctx: RiskContext, violations: list[AuthorizationViolation] | None = None
) -> dict[str, float]:
    delegation = ctx.delegation
    txn = ctx.transaction
    violations = check_authorization(ctx) if violations is None else violations

    if delegation is None:
        # No delegation supplied. That is not itself a violation — plenty of transactions
        # are not agent-delegated — so the flags stay neutral and `auth_present` says why.
        features = dict.fromkeys(AUTHORIZATION_FEATURE_NAMES, 0.0)
        features["auth_present"] = 0.0
        features["auth_active"] = 0.0
        return features

    codes = {v.code for v in violations}
    age_days = (txn.timestamp - delegation.issued_at).total_seconds() / 86400.0
    to_expiry_days = (delegation.expires_at - txn.timestamp).total_seconds() / 86400.0
    expired = "delegation_expired" in codes
    not_yet = "delegation_not_yet_valid" in codes

    return {
        "auth_present": 1.0,
        "auth_amount_within_max": 0.0 if txn.amount > delegation.max_amount else 1.0,
        "auth_amount_ratio_to_max": min(
            50.0, safe_div(txn.amount, delegation.max_amount, default=1.0)
        ),
        "auth_amount_over_max": max(0.0, txn.amount - delegation.max_amount),
        "auth_category_allowed": 0.0 if "category_not_allowed" in codes else 1.0,
        "auth_category_forbidden": 1.0 if "forbidden_category" in codes else 0.0,
        "auth_merchant_allowed": 0.0 if "merchant_not_allowlisted" in codes else 1.0,
        "auth_active": 0.0 if (expired or not_yet) else 1.0,
        "auth_expired": 1.0 if expired else 0.0,
        "auth_not_yet_valid": 1.0 if not_yet else 0.0,
        "auth_age_days": max(-365.0, min(365.0, age_days)),
        "auth_time_to_expiry_days": max(-365.0, min(365.0, to_expiry_days)),
        "auth_requires_approval": 1.0 if "approval_required" in codes else 0.0,
        "auth_agent_matches": 0.0 if "agent_mismatch" in codes else 1.0,
        "auth_customer_matches": 0.0 if "customer_mismatch" in codes else 1.0,
        "auth_currency_matches": 0.0 if "currency_mismatch" in codes else 1.0,
        "auth_violation_count": float(len(violations)),
        "auth_hard_violation": 1.0 if any(v.hard for v in violations) else 0.0,
    }
