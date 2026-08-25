"""Intent / delegation assessment.

Produces the ``intent_deviation`` component. Two layers, in strict precedence order:

1. **Deterministic.** Typed delegation constraints and, where present, the parsed intent
   contract. This layer alone is sufficient; the system is fully functional without an
   API key.
2. **Semantic (optional).** May *raise* the deviation when a model detects an inconsistency
   the typed constraints cannot express. It can never lower it below the deterministic
   value, and a failed or low-confidence verdict is recorded as degraded, never as 0.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.logging import get_logger
from app.features.authorization import AuthorizationViolation
from app.features.context import RiskContext
from app.intent.base import SemanticResult
from app.intent.parser import parse_instruction
from app.schemas.entities import IntentContract, Transaction
from app.schemas.enums import ComponentStatus, EvidenceDirection, Severity, SignalSource
from app.schemas.risk import RiskEvidence

log = get_logger(__name__)

# Deviation weight per violation code. The overall deviation is the MAX, not the sum: one
# hard breach already means "fully inconsistent with the authorization", and summing would
# let three soft findings outrank an expired delegation.
VIOLATION_WEIGHTS: dict[str, float] = {
    "delegation_expired": 1.0,
    "forbidden_category": 1.0,
    "customer_mismatch": 1.0,
    "delegation_not_yet_valid": 0.9,
    "agent_mismatch": 0.9,
    "currency_mismatch": 0.8,
    "merchant_not_allowlisted": 0.7,
    "category_not_allowed": 0.6,
    "amount_exceeds_delegation": 0.75,
    "approval_required": 0.30,
}

SEMANTIC_MAX_CONTRIBUTION = 0.8
"""A semantic verdict alone can never push deviation above this. Hard breaches are
deterministic; a language model's opinion is not allowed to be maximally damning."""


@dataclass
class IntentAssessment:
    deviation: float | None
    status: ComponentStatus
    violations: list[AuthorizationViolation] = field(default_factory=list)
    semantic: SemanticResult | None = None
    evidence: list[RiskEvidence] = field(default_factory=list)
    intent_contract: IntentContract | None = None
    detail: str | None = None


def contract_deviation(transaction: Transaction, contract: IntentContract) -> tuple[float, list[str]]:
    """Soft deviation against a parsed natural-language intent contract.

    Weaker than a typed delegation by design: this came from keyword parsing of free text,
    so it informs the score without ever being treated as an authorization breach.
    """
    reasons: list[str] = []
    deviation = 0.0
    category = transaction.merchant_category.lower()

    if category in {c.lower() for c in contract.forbidden_categories}:
        deviation = max(deviation, 0.85)
        reasons.append(f"category '{category}' was explicitly excluded in the instruction")
    elif contract.allowed_categories and category not in {
        c.lower() for c in contract.allowed_categories
    }:
        deviation = max(deviation, 0.5)
        reasons.append(
            f"category '{category}' is outside the instruction's stated categories "
            f"{sorted(contract.allowed_categories)}"
        )

    if contract.max_amount is not None and transaction.amount > contract.max_amount:
        over = float(transaction.amount) / max(1.0, float(contract.max_amount))
        deviation = max(deviation, min(0.9, 0.45 + 0.25 * over))
        reasons.append(
            f"amount {transaction.amount} exceeds the stated cap {contract.max_amount}"
        )

    return deviation, reasons


class IntentService:
    """Deterministic-first intent assessment with an optional semantic layer."""

    def __init__(self, verifier=None) -> None:
        from app.intent.providers import build_semantic_verifier

        self.verifier = verifier or build_semantic_verifier()

    async def assess(
        self,
        ctx: RiskContext,
        transaction: Transaction,
        violations: list[AuthorizationViolation],
        instruction_text: str | None = None,
        intent_contract: IntentContract | None = None,
        use_semantic: bool = True,
    ) -> IntentAssessment:
        evidence: list[RiskEvidence] = []

        contract = intent_contract or parse_instruction(instruction_text)
        has_delegation = ctx.delegation is not None

        if not has_delegation and contract is None:
            # Nothing to compare against. This is a genuinely unavailable component, and
            # saying so is the whole point — a 0.0 here would read as "verified compliant".
            return IntentAssessment(
                deviation=None,
                status=ComponentStatus.UNAVAILABLE,
                detail="no delegation or instruction supplied",
            )

        deterministic = 0.0
        if violations:
            deterministic = max(VIOLATION_WEIGHTS.get(v.code, 0.5) for v in violations)
            for violation in violations:
                evidence.append(
                    RiskEvidence(
                        signal=violation.code,
                        observed=violation.detail,
                        observed_value=violation.observed_value,
                        expected_value=violation.expected_value,
                        severity=Severity.CRITICAL if violation.hard else Severity.MEDIUM,
                        source=SignalSource.INTENT_ENGINE,
                        direction=EvidenceDirection.INCREASES_RISK,
                    )
                )

        if contract is not None:
            contract_score, reasons = contract_deviation(transaction, contract)
            deterministic = max(deterministic, contract_score)
            for reason in reasons:
                evidence.append(
                    RiskEvidence(
                        signal="instruction_mismatch",
                        observed=reason,
                        severity=Severity.MEDIUM,
                        source=SignalSource.INTENT_ENGINE,
                        direction=EvidenceDirection.INCREASES_RISK,
                    )
                )

        if has_delegation and not violations and deterministic == 0.0:
            evidence.append(
                RiskEvidence(
                    signal="intent_alignment",
                    observed=(
                        "transaction amount, category and merchant are all within the active "
                        "delegation"
                    ),
                    severity=Severity.INFO,
                    source=SignalSource.INTENT_ENGINE,
                    direction=EvidenceDirection.DECREASES_RISK,
                )
            )

        semantic: SemanticResult | None = None
        status = ComponentStatus.OK
        if use_semantic and instruction_text:
            semantic = await self.verifier.verify_intent(
                transaction=transaction,
                intent=contract,
                instruction_text=instruction_text,
                action_types=[a.action_type for a in ctx.actions],
            )
            if semantic.ok and semantic.verdict is not None:
                verdict = semantic.verdict
                if verdict.usable:
                    semantic_component = verdict.mismatch_score * SEMANTIC_MAX_CONTRIBUTION
                    # MAX, never replace: the semantic layer can only add concern.
                    deterministic = max(deterministic, semantic_component)
                    if verdict.mismatch_reasons:
                        evidence.append(
                            RiskEvidence(
                                signal="semantic_intent_mismatch",
                                observed="; ".join(verdict.mismatch_reasons)[:500],
                                observed_value=verdict.mismatch_score,
                                expected_value=0.0,
                                severity=(
                                    Severity.HIGH if verdict.mismatch_score >= 0.6
                                    else Severity.MEDIUM
                                ),
                                source=SignalSource.SEMANTIC_ENGINE,
                                direction=EvidenceDirection.INCREASES_RISK,
                            )
                        )
                else:
                    status = ComponentStatus.DEGRADED
                    evidence.append(
                        RiskEvidence(
                            signal="semantic_verdict_unusable",
                            observed=(
                                "semantic verdict was ambiguous or low-confidence and was "
                                "excluded from the score"
                            ),
                            severity=Severity.INFO,
                            source=SignalSource.SEMANTIC_ENGINE,
                            direction=EvidenceDirection.NEUTRAL,
                        )
                    )
            elif semantic.error_code and semantic.error_code != "semantic_disabled":
                status = ComponentStatus.DEGRADED
                evidence.append(
                    RiskEvidence(
                        signal="semantic_engine_degraded",
                        observed=(
                            f"semantic verification unavailable ({semantic.error_code}); "
                            "deterministic checks only"
                        ),
                        severity=Severity.INFO,
                        source=SignalSource.SEMANTIC_ENGINE,
                        direction=EvidenceDirection.NEUTRAL,
                    )
                )

        return IntentAssessment(
            deviation=min(1.0, deterministic),
            status=status,
            violations=violations,
            semantic=semantic,
            evidence=evidence,
            intent_contract=contract,
        )
