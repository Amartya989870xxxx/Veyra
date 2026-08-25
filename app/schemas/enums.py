"""Closed vocabularies shared by the API, the ORM and the evaluation pipeline."""

from __future__ import annotations

from enum import StrEnum


class EventType(StrEnum):
    TRANSACTION_ATTEMPT = "TRANSACTION_ATTEMPT"
    PAYMENT_RESULT = "PAYMENT_RESULT"
    AGENT_ACTION = "AGENT_ACTION"
    SESSION_STARTED = "SESSION_STARTED"
    DELEGATION_CREATED = "DELEGATION_CREATED"
    ORDER_CREATED = "ORDER_CREATED"


class ActionType(StrEnum):
    """Agent action trajectory vocabulary.

    ``REQUEST_PAYMENT``/``RETRY_PAYMENT`` are the risk-bearing terminals; everything
    before them forms the trajectory Tyche reasons about.
    """

    SEARCH = "SEARCH"
    VIEW_PRODUCT = "VIEW_PRODUCT"
    COMPARE_PRICES = "COMPARE_PRICES"
    ADD_TO_CART = "ADD_TO_CART"
    APPLY_COUPON = "APPLY_COUPON"
    AUTHENTICATE = "AUTHENTICATE"
    CHECKOUT = "CHECKOUT"
    REQUEST_PAYMENT = "REQUEST_PAYMENT"
    RETRY_PAYMENT = "RETRY_PAYMENT"
    CANCEL = "CANCEL"
    TOOL_CALL = "TOOL_CALL"


class ActorType(StrEnum):
    HUMAN = "HUMAN"
    AGENT = "AGENT"


class TrustTier(StrEnum):
    UNTRUSTED = "untrusted"
    STANDARD = "standard"
    TRUSTED = "trusted"
    VERIFIED = "verified"


class PaymentStatus(StrEnum):
    ATTEMPTED = "ATTEMPTED"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Decision(StrEnum):
    ALLOW = "ALLOW"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EvidenceDirection(StrEnum):
    """Whether a piece of evidence pushed risk up, down, or was merely contextual."""

    INCREASES_RISK = "increases_risk"
    DECREASES_RISK = "decreases_risk"
    NEUTRAL = "neutral"


class SignalSource(StrEnum):
    RULE_ENGINE = "rule_engine"
    TRANSACTION_ENGINE = "transaction_engine"
    BEHAVIOR_ENGINE = "behavior_engine"
    GRAPH_ENGINE = "graph_engine"
    INTENT_ENGINE = "intent_engine"
    TEMPORAL_ENGINE = "temporal_engine"
    ANOMALY_MODEL = "anomaly_model"
    SEMANTIC_ENGINE = "semantic_engine"
    POLICY_ENGINE = "policy_engine"


class ComponentStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class DecisionStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"


class LabelClass(StrEnum):
    """Ground-truth class in the synthetic benchmark. Never inferred at runtime."""

    LEGIT_HUMAN = "LEGIT_HUMAN"
    LEGIT_AGENT = "LEGIT_AGENT"
    SUSPICIOUS_AUTOMATION = "SUSPICIOUS_AUTOMATION"
    COORDINATED_ABUSE = "COORDINATED_ABUSE"

    @property
    def is_abusive(self) -> bool:
        return self in (LabelClass.SUSPICIOUS_AUTOMATION, LabelClass.COORDINATED_ABUSE)


class SplitName(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    HOLDOUT = "holdout"


class CaseStatus(StrEnum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    CONFIRMED_ABUSE = "confirmed_abuse"
    FALSE_POSITIVE = "false_positive"
    CLOSED = "closed"


class MerchantPolicy(StrEnum):
    ANY = "any"
    KNOWN_OR_APPROVED = "known_or_approved"
    ALLOWLIST_ONLY = "allowlist_only"


class RelationshipType(StrEnum):
    USES_DEVICE = "USES_DEVICE"
    USES_NETWORK = "USES_NETWORK"
    OPERATED_BY_AGENT = "OPERATED_BY_AGENT"
    IN_SESSION = "IN_SESSION"
    PAID_MERCHANT = "PAID_MERCHANT"
    PURCHASED_SKU = "PURCHASED_SKU"
    REDEEMED_COUPON = "REDEEMED_COUPON"
    MADE_TRANSACTION = "MADE_TRANSACTION"
