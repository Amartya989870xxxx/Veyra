"""Payment-centric domain entities.

Two disciplines carried over from v1 unchanged, because both were right:

*Money is ``Decimal`` end to end.* It becomes ``float`` only at the ML feature boundary,
where an amount is a statistic rather than an obligation.

*Identities arrive pre-hashed.* ``instrument_fp``, ``device_fp`` and ``ip_fp`` are opaque
fingerprints, never PANs, device serials or addresses. Veyra reasons about *reuse* - does
this instrument appear on many devices, does this device serve many accounts - and reuse
is answerable from a stable hash. Accepting the raw value would add regulatory surface for
no analytic gain, so the schema refuses values that look unhashed.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.enums import (
    DeclineSource,
    DisputeType,
    InstrumentType,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    RefundReason,
)

ID = Field(..., min_length=1, max_length=128)

_PAN_LIKE = re.compile(r"^\d{12,19}$")


class VeyraModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, use_enum_values=False)


def _reject_pan_like(value: str) -> str:
    """Refuse a fingerprint that looks like a raw card number.

    A cheap check that catches the realistic mistake - a loader passing ``card_number``
    straight through - rather than a determined caller. Being wrong here is expensive in a
    way that no metric would reveal.
    """
    if _PAN_LIKE.match(value):
        raise ValueError("fingerprint looks like a raw PAN; pass a hash, never the value")
    return value


class Merchant(VeyraModel):
    """The unit everything is scored against (ADR-001).

    ``category`` and ``size_band`` exist for the cold-start policy: a merchant with too
    little history is scored against a population baseline drawn from peers that share
    both, and the incident records ``baseline_confidence: LOW`` rather than pretending.
    """

    merchant_id: str = ID
    name: str | None = Field(default=None, max_length=200)
    category: str = Field(..., max_length=64)
    home_country: str = Field(default="IN", min_length=2, max_length=2)
    size_band: str = Field(default="unknown", max_length=32)
    onboarded_at: datetime | None = None


class Customer(VeyraModel):
    customer_id: str = ID
    created_at: datetime | None = Field(
        default=None,
        description="Account age drives family G. Absent means unknown, never new.",
    )
    home_country: str = Field(default="IN", min_length=2, max_length=2)
    segment: str = Field(default="retail", max_length=32)


class InstrumentMeta(VeyraModel):
    """What is knowable about a payment instrument without holding it.

    ``bin_hash`` rather than the BIN itself: BIN *structure* is what distinguishes an
    enumeration attack (many instruments, one issuer range) from a normal mix, and a
    salted hash preserves the equality comparisons that answer it.
    """

    brand: str | None = Field(default=None, max_length=32)
    instrument_type: InstrumentType = InstrumentType.UNKNOWN
    issuer_country: str | None = Field(default=None, min_length=2, max_length=2)
    bin_hash: str | None = Field(default=None, max_length=64)
    is_on_file: bool = Field(
        default=False,
        description=(
            "Stored credential. Separates a subscription renewal batch - every instrument "
            "on file - from card testing, where novelty is near 1.0."
        ),
    )


class Geo(VeyraModel):
    """Coarse location. Never finer than city, and never a verdict on its own.

    The geographic family is distributional: what matters is a *shift* against the
    merchant's own mix, not that a payment came from abroad (brief §8E).
    """

    country: str = Field(default="IN", min_length=2, max_length=2)
    state: str | None = Field(default=None, max_length=64)
    city: str | None = Field(default=None, max_length=64)


class PaymentAttempt(VeyraModel):
    """One attempt to take money. The atom every window aggregates over."""

    transaction_id: str = ID
    merchant_id: str = ID
    customer_id: str | None = Field(default=None, max_length=128)
    order_id: str | None = Field(default=None, max_length=128)

    instrument_fp: str = Field(..., min_length=1, max_length=128)
    instrument_meta: InstrumentMeta = Field(default_factory=InstrumentMeta)
    device_fp: str | None = Field(default=None, max_length=128)
    ip_fp: str | None = Field(default=None, max_length=128)
    geo: Geo = Field(default_factory=Geo)

    amount: Decimal = Field(..., ge=0, decimal_places=2)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    payment_method: PaymentMethod = PaymentMethod.CARD
    is_cod: bool = False
    coupon_id: str | None = Field(default=None, max_length=64)
    attempt_number: int = Field(
        default=1,
        ge=1,
        le=100,
        description="1 for a first attempt. Retries drive C.retry_rate, which is what "
        "keeps a gateway retry storm from reading as card testing.",
    )
    timestamp: datetime

    @field_validator("instrument_fp", "device_fp", "ip_fp")
    @classmethod
    def _no_raw_identifiers(cls, v: str | None) -> str | None:
        return _reject_pan_like(v) if v else v

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "examples": [
                {
                    "transaction_id": "txn_000001",
                    "merchant_id": "m_0007",
                    "customer_id": "cus_0451",
                    "instrument_fp": "if_9c2a4e1b",
                    "instrument_meta": {
                        "brand": "visa",
                        "instrument_type": "CREDIT",
                        "issuer_country": "IN",
                        "bin_hash": "bin_3f81",
                        "is_on_file": False,
                    },
                    "device_fp": "dv_71bc0f",
                    "ip_fp": "ip_5ad39c",
                    "geo": {"country": "IN", "state": "KA", "city": "Bengaluru"},
                    "amount": "1299.00",
                    "currency": "INR",
                    "payment_method": "CARD",
                    "is_cod": False,
                    "attempt_number": 1,
                    "timestamp": "2026-03-15T11:59:04Z",
                }
            ]
        },
    )


class PaymentOutcome(VeyraModel):
    """What the acquirer said. Family I's real-time half."""

    transaction_id: str = ID
    status: PaymentStatus
    decline_source: DeclineSource = DeclineSource.UNKNOWN
    failure_code: str | None = Field(default=None, max_length=64)
    timestamp: datetime


class Refund(VeyraModel):
    """Observable in near-real time, so *not* downstream-only (ADR-004).

    ``initiated_at`` is kept alongside the originating attempt so refund latency can be
    measured rather than assumed - that measurement is what keeps this honest.
    """

    refund_id: str = ID
    transaction_id: str = ID
    amount: Decimal = Field(..., ge=0, decimal_places=2)
    reason_code: RefundReason = RefundReason.CUSTOMER_REQUEST
    is_full: bool = True
    timestamp: datetime


class Dispute(VeyraModel):
    """A chargeback. **Label source only** - never a real-time feature (ADR-004).

    ``days_after_transaction`` is carried explicitly so the lag is visible in the data
    rather than buried in a timestamp difference nobody looks at.
    """

    dispute_id: str = ID
    transaction_id: str = ID
    dispute_type: DisputeType = DisputeType.FRAUD
    amount: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    days_after_transaction: int = Field(default=0, ge=0, le=180)
    timestamp: datetime


class OrderOutcome(VeyraModel):
    """Fulfilment progress. ``RTO`` is the COD-abuse signal and arrives days late."""

    order_id: str = ID
    merchant_id: str = ID
    status: OrderStatus
    timestamp: datetime
