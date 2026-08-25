"""Core domain entities.

Money is ``Decimal`` end to end. It is converted to ``float`` only at the ML feature
boundary, where an amount is a statistic rather than an obligation; policy comparisons
(amount vs. delegated limit) always stay in ``Decimal``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.enums import (
    ActionType,
    ActorType,
    MerchantPolicy,
    PaymentStatus,
    RelationshipType,
    TrustTier,
)

SYNTHETIC_ID = Field(..., min_length=1, max_length=128)


class VeyraModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, use_enum_values=False)


class Merchant(VeyraModel):
    merchant_id: str = SYNTHETIC_ID
    name: str | None = Field(default=None, max_length=200)
    category: str = Field(..., max_length=64)
    risk_policy_id: str = Field(default="policy_default_v1", max_length=64)
    is_known: bool = Field(default=True, description="Present in the customer's known-merchant set")

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"merchant_id": "m_0007", "category": "grocery", "risk_policy_id": "policy_default_v1"}
            ]
        },
    )


class Customer(VeyraModel):
    customer_id: str = SYNTHETIC_ID
    created_at: datetime | None = None
    home_country: str = Field(default="IN", max_length=2)
    segment: str = Field(default="retail", max_length=32)


class Agent(VeyraModel):
    agent_id: str = SYNTHETIC_ID
    provider: str = Field(default="synthetic", max_length=64)
    application_id: str | None = Field(default=None, max_length=128)
    trust_tier: TrustTier = TrustTier.STANDARD
    created_at: datetime | None = None

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "agent_id": "agent_0042",
                    "provider": "synthetic",
                    "application_id": "app_0003",
                    "trust_tier": "standard",
                }
            ]
        },
    )


class AgentDelegation(VeyraModel):
    """A customer's bounded grant of payment authority to an agent.

    This is the authoritative authorization record. The natural-language instruction it
    was derived from is kept only as an ``IntentContract`` for semantic comparison; hard
    constraints are always read from these typed fields.
    """

    delegation_id: str = SYNTHETIC_ID
    customer_id: str = SYNTHETIC_ID
    agent_id: str = SYNTHETIC_ID
    purpose: str = Field(default="general_purchase", max_length=64)
    max_amount: Decimal = Field(..., ge=0, decimal_places=2)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    allowed_categories: list[str] = Field(default_factory=list, max_length=64)
    forbidden_categories: list[str] = Field(default_factory=list, max_length=64)
    allowed_merchants: list[str] = Field(default_factory=list, max_length=256)
    merchant_policy: MerchantPolicy = MerchantPolicy.KNOWN_OR_APPROVED
    allowed_actions: list[ActionType] = Field(default_factory=list, max_length=32)
    approval_required_above: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    issued_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def _check_window(self) -> AgentDelegation:
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        return self

    @field_validator("allowed_categories", "forbidden_categories", mode="after")
    @classmethod
    def _normalize(cls, v: list[str]) -> list[str]:
        return [c.strip().lower() for c in v if c.strip()]

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "delegation_id": "del_0001",
                    "customer_id": "cus_0001",
                    "agent_id": "agent_0042",
                    "purpose": "grocery_purchase",
                    "max_amount": "2500.00",
                    "currency": "INR",
                    "allowed_categories": ["grocery", "food"],
                    "forbidden_categories": ["alcohol"],
                    "merchant_policy": "known_or_approved",
                    "approval_required_above": "2500.00",
                    "issued_at": "2026-02-01T09:00:00Z",
                    "expires_at": "2026-03-01T09:00:00Z",
                }
            ]
        },
    )


class IntentContract(VeyraModel):
    """Structured representation of a natural-language instruction (PRD §15).

    Produced either deterministically or by the semantic layer. It is compared against
    the delegation; it never replaces it.
    """

    purpose: str = Field(..., max_length=64)
    max_amount: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    allowed_categories: list[str] = Field(default_factory=list, max_length=64)
    forbidden_categories: list[str] = Field(default_factory=list, max_length=64)
    merchant_policy: MerchantPolicy = MerchantPolicy.KNOWN_OR_APPROVED
    approval_required_above: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    valid_until: datetime | None = None
    source_text: str | None = Field(default=None, max_length=2000)


class AgentSession(VeyraModel):
    session_id: str = SYNTHETIC_ID
    agent_id: str | None = Field(default=None, max_length=128)
    customer_id: str = SYNTHETIC_ID
    actor_type: ActorType = ActorType.AGENT
    device_id: str | None = Field(default=None, max_length=128)
    network_fingerprint: str | None = Field(default=None, max_length=128)
    started_at: datetime
    ended_at: datetime | None = None


class AgentAction(VeyraModel):
    action_id: str = SYNTHETIC_ID
    agent_id: str = SYNTHETIC_ID
    session_id: str = SYNTHETIC_ID
    sequence_number: int = Field(..., ge=0, le=100_000)
    action_type: ActionType
    tool_name: str | None = Field(default=None, max_length=128)
    timestamp: datetime
    merchant_id: str | None = Field(default=None, max_length=128)
    sku_id: str | None = Field(default=None, max_length=128)
    metadata: dict = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def _bound_metadata(cls, v: dict) -> dict:
        if len(v) > 32:
            raise ValueError("action metadata is limited to 32 keys")
        return v

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "action_id": "act_000014",
                    "agent_id": "agent_0042",
                    "session_id": "sess_0009",
                    "sequence_number": 14,
                    "action_type": "REQUEST_PAYMENT",
                    "tool_name": "payment.create",
                    "timestamp": "2026-02-14T10:31:02Z",
                }
            ]
        },
    )


class Transaction(VeyraModel):
    """A payment attempt. Never carries card numbers, CVVs, OTPs or tokens."""

    transaction_id: str = SYNTHETIC_ID
    merchant_id: str = SYNTHETIC_ID
    customer_id: str = SYNTHETIC_ID
    agent_id: str | None = Field(default=None, max_length=128)
    session_id: str | None = Field(default=None, max_length=128)
    order_id: str | None = Field(default=None, max_length=128)
    delegation_id: str | None = Field(default=None, max_length=128)
    amount: Decimal = Field(..., ge=0, le=Decimal("100000000"), decimal_places=2)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    merchant_category: str = Field(..., max_length=64)
    sku_id: str | None = Field(default=None, max_length=128)
    quantity: int = Field(default=1, ge=1, le=10_000)
    coupon_id: str | None = Field(default=None, max_length=128)
    coupon_value: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    device_id: str | None = Field(default=None, max_length=128)
    network_fingerprint: str | None = Field(default=None, max_length=128)
    payment_method: str = Field(default="upi", max_length=32)
    instrument_fingerprint: str | None = Field(
        default=None, max_length=128, description="Synthetic non-reversible instrument token"
    )
    retry_count: int = Field(default=0, ge=0, le=1000)
    status: PaymentStatus = PaymentStatus.ATTEMPTED
    timestamp: datetime
    actor_type: ActorType = ActorType.HUMAN

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "transaction_id": "txn_000123",
                    "merchant_id": "m_0007",
                    "customer_id": "cus_0001",
                    "agent_id": "agent_0042",
                    "session_id": "sess_0009",
                    "amount": "1849.00",
                    "currency": "INR",
                    "merchant_category": "grocery",
                    "sku_id": "sku_0091",
                    "quantity": 1,
                    "device_id": "dev_0031",
                    "network_fingerprint": "nf_0012",
                    "retry_count": 0,
                    "timestamp": "2026-02-14T10:31:04Z",
                    "actor_type": "AGENT",
                }
            ]
        },
    )


class Order(VeyraModel):
    order_id: str = SYNTHETIC_ID
    merchant_id: str = SYNTHETIC_ID
    customer_id: str = SYNTHETIC_ID
    amount: Decimal = Field(..., ge=0, decimal_places=2)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    sku_id: str | None = Field(default=None, max_length=128)
    quantity: int = Field(default=1, ge=1, le=10_000)
    created_at: datetime


class EntityRelationship(VeyraModel):
    """An observed edge in the entity graph. Carries no secrets by construction."""

    source_type: str = Field(..., max_length=32)
    source_id: str = SYNTHETIC_ID
    target_type: str = Field(..., max_length=32)
    target_id: str = SYNTHETIC_ID
    relationship: RelationshipType
    observed_at: datetime
    weight: float = Field(default=1.0, ge=0)
