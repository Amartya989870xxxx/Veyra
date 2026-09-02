"""Closed vocabularies shared by the API, the ORM, the generator and the evaluator.

This is the v2 vocabulary. The v1 agent-commerce terms (``ActionType``, ``ActorType``,
``TrustTier``) are gone entirely rather than deprecated: the two vocabularies describe
different problems, and a codebase carrying both invites a feature built on the wrong
one. v1 remains recoverable at tag ``v1-agent-commerce``.
"""

from __future__ import annotations

from enum import StrEnum


class EventType(StrEnum):
    """The five event kinds Veyra ingests.

    Deliberately small. Every signal the system reasons about is derivable from a payment
    attempt, what happened to it, and what happened to the order afterwards.
    """

    PAYMENT_ATTEMPT = "PAYMENT_ATTEMPT"
    PAYMENT_RESULT = "PAYMENT_RESULT"
    REFUND = "REFUND"
    DISPUTE = "DISPUTE"
    ORDER_STATUS = "ORDER_STATUS"


class PaymentStatus(StrEnum):
    ATTEMPTED = "ATTEMPTED"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def is_failure(self) -> bool:
        return self in (PaymentStatus.FAILED, PaymentStatus.CANCELLED)


class DeclineSource(StrEnum):
    """Who refused the payment.

    Matters because it discriminates card testing from a gateway retry storm: an attacker
    probing stolen numbers collects *issuer* declines spread across codes, while a retry
    storm collects gateway/network errors on a small reused instrument set
    (``card_testing_burst`` vs ``gateway_retry_storm`` in the matrix).
    """

    ISSUER = "ISSUER"
    GATEWAY = "GATEWAY"
    NETWORK = "NETWORK"
    MERCHANT = "MERCHANT"
    UNKNOWN = "UNKNOWN"


class PaymentMethod(StrEnum):
    CARD = "CARD"
    UPI = "UPI"
    NETBANKING = "NETBANKING"
    WALLET = "WALLET"
    EMI = "EMI"
    COD = "COD"
    PAY_LATER = "PAY_LATER"


class InstrumentType(StrEnum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"
    PREPAID = "PREPAID"
    UNKNOWN = "UNKNOWN"


class OrderStatus(StrEnum):
    """Fulfilment outcomes.

    ``RTO`` (return to origin) is the COD abuse signal. Like a dispute it arrives days
    later, which is why it is barred from real-time features by ADR-004.
    """

    CREATED = "CREATED"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    RTO = "RTO"


class DisputeType(StrEnum):
    FRAUD = "FRAUD"
    SERVICE = "SERVICE"
    PROCESSING = "PROCESSING"
    AUTHORIZATION = "AUTHORIZATION"


class RefundReason(StrEnum):
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"
    ITEM_NOT_RECEIVED = "ITEM_NOT_RECEIVED"
    ITEM_DEFECTIVE = "ITEM_DEFECTIVE"
    DUPLICATE_CHARGE = "DUPLICATE_CHARGE"
    MERCHANT_INITIATED = "MERCHANT_INITIATED"
    FRAUD_SUSPECTED = "FRAUD_SUSPECTED"


class ScenarioClass(StrEnum):
    """What a generated or observed incident *is*, per ``research/matrix.yaml``."""

    BASELINE = "baseline"
    LEGITIMATE = "legitimate"
    ATTACK = "attack"
    MIXED = "mixed"


class WindowLabel(StrEnum):
    """Ground truth for a scored window. Three classes, not two.

    ``LEGIT_SPIKE`` is separated from ``NORMAL`` because "did not fire on a flash sale"
    and "did not fire on a quiet Tuesday" are entirely different achievements. Collapsing
    them into one negative class hides the only false-positive number that matters
    (ADR-003, brief §12).
    """

    NORMAL = "NORMAL"
    LEGIT_SPIKE = "LEGIT_SPIKE"
    FRAUD_SPIKE = "FRAUD_SPIKE"

    @property
    def is_positive(self) -> bool:
        return self is WindowLabel.FRAUD_SPIKE


class ActionTier(StrEnum):
    """What the system does about an incident (ADR-006).

    Four tiers rather than a binary, and the strongest one *recommends* a control rather
    than applying it. A prototype must not silently decline live payments.
    """

    OBSERVE = "OBSERVE"
    ALERT = "ALERT"
    REVIEW = "REVIEW"
    RESTRICT = "RESTRICT"


class IncidentStatus(StrEnum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"
    CLOSED = "CLOSED"

    @property
    def is_terminal(self) -> bool:
        return self is IncidentStatus.CLOSED


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class BaselineConfidence(StrEnum):
    """How much history the merchant baseline was fit on.

    Recorded on every incident. A new merchant scored against six hours of history
    produces confident nonsense, and the honest response is to say so rather than to
    suppress the alert or pretend the baseline is solid (roadmap §3.2).
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class SplitName(StrEnum):
    """Temporal splits. Never random — a random split puts 11:59 in train and 12:00 in
    test, landing the same incident on both sides (brief §25)."""

    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class ComponentStatus(StrEnum):
    """v1's degradation vocabulary, kept deliberately.

    A component that cannot run reports ``UNAVAILABLE`` and is excluded from fusion. It
    never substitutes a neutral value, because a fabricated 0.5 is indistinguishable from
    a real 0.5 downstream.
    """

    OK = "ok"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class EntityKind(StrEnum):
    """Node types in the relationship graph (brief §16)."""

    MERCHANT = "merchant"
    CUSTOMER = "customer"
    INSTRUMENT = "instrument"
    DEVICE = "device"
    NETWORK = "network"
    ADDRESS = "address"
