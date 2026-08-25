"""Risk request/response contracts, evidence model, and component score container."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.versions import POLICY_VERSION, SCHEMA_VERSION
from app.schemas.entities import AgentAction, AgentDelegation, IntentContract, Transaction
from app.schemas.enums import (
    ComponentStatus,
    Decision,
    DecisionStatus,
    EvidenceDirection,
    Severity,
    SignalSource,
    TrustTier,
)


class RiskEvidence(BaseModel):
    """One machine-readable reason. Never model chain-of-thought (PRD §7 Principle 8)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "signal": "shared_device_cluster",
                    "observed": "17 customer accounts share the same device fingerprint",
                    "observed_value": 17.0,
                    "expected_value": 1.0,
                    "severity": "high",
                    "source": "graph_engine",
                    "direction": "increases_risk",
                    "contribution": 0.31,
                }
            ]
        },
    )

    signal: str = Field(..., max_length=64)
    observed: str = Field(..., max_length=500, description="Human-readable observation")
    observed_value: float | None = None
    expected_value: float | None = Field(
        default=None, description="Baseline this observation is compared against, when one exists"
    )
    severity: Severity = Severity.INFO
    source: SignalSource
    direction: EvidenceDirection = EvidenceDirection.INCREASES_RISK
    contribution: float | None = Field(
        default=None, description="Signed contribution to the fused score, when attributable"
    )


class ComponentScores(BaseModel):
    """Uncombined component scores, persisted for auditability (PRD §17).

    ``None`` means the component genuinely could not produce a score. It is never
    replaced with a default, because a fabricated 0.0 is indistinguishable from
    "confidently safe" downstream.
    """

    model_config = ConfigDict(extra="forbid")

    transaction_risk: float | None = Field(default=None, ge=0, le=1)
    behavior_risk: float | None = Field(default=None, ge=0, le=1)
    campaign_risk: float | None = Field(default=None, ge=0, le=1)
    intent_deviation: float | None = Field(default=None, ge=0, le=1)
    rule_violation_score: float | None = Field(default=None, ge=0, le=1)

    def available(self) -> dict[str, float]:
        return {k: v for k, v in self.model_dump().items() if v is not None}

    def missing(self) -> list[str]:
        return [k for k, v in self.model_dump().items() if v is None]


class ComponentHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component: str
    status: ComponentStatus
    detail: str | None = Field(default=None, max_length=300)
    error_code: str | None = Field(default=None, max_length=64)


class AgentContext(BaseModel):
    """Agent-side context supplied with a risk request."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str | None = Field(default=None, max_length=128)
    session_id: str | None = Field(default=None, max_length=128)
    provider: str | None = Field(default=None, max_length=64)
    trust_tier: TrustTier | None = None
    session_started_at: datetime | None = None
    actions_in_session: int | None = Field(default=None, ge=0, le=1_000_000)


class AuthorizationContext(BaseModel):
    """Delegation plus the natural-language intent it was derived from, if any."""

    model_config = ConfigDict(extra="forbid")

    delegation: AgentDelegation | None = None
    intent_contract: IntentContract | None = None
    instruction_text: str | None = Field(
        default=None, max_length=2000, description="Raw user instruction; treated as untrusted data"
    )


class RiskEvaluateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "transaction": Transaction.model_config["json_schema_extra"]["examples"][0],
                    "agent_context": {
                        "agent_id": "agent_0042",
                        "session_id": "sess_0009",
                        "trust_tier": "standard",
                    },
                    "authorization": {
                        "delegation": AgentDelegation.model_config["json_schema_extra"]["examples"][0]
                    },
                    "event_trace": [
                        AgentAction.model_config["json_schema_extra"]["examples"][0]
                    ],
                }
            ]
        },
    )

    transaction: Transaction
    agent_context: AgentContext | None = None
    authorization: AuthorizationContext | None = None
    event_trace: list[AgentAction] = Field(default_factory=list, max_length=500)
    schema_version: str = Field(default=SCHEMA_VERSION, max_length=16)
    persist: bool = Field(
        default=True, description="Persist the decision and ingest the transaction"
    )


class RiskDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    transaction_id: str
    decision: Decision
    status: DecisionStatus = DecisionStatus.OK
    risk_score: float = Field(..., ge=0, le=1)
    transaction_risk: float | None = None
    behavior_risk: float | None = None
    campaign_risk: float | None = None
    intent_deviation: float | None = None
    rule_violation_score: float | None = None
    campaign_id: str | None = None
    case_id: str | None = None
    reason_code: str = Field(..., max_length=64)
    rationale: str = Field(..., max_length=500)
    evidence: list[RiskEvidence] = Field(default_factory=list)
    policy_version: str = POLICY_VERSION
    feature_snapshot_hash: str
    model_versions: dict[str, str] = Field(default_factory=dict)
    degraded_components: list[str] = Field(default_factory=list)
    component_health: list[ComponentHealth] = Field(default_factory=list)
    persisted: bool = Field(
        default=True, description="False when the decision store was unavailable"
    )
    decided_at: datetime
    latency_ms: float


class CampaignResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    campaign_id: str
    detected_at: datetime
    campaign_risk: float
    size: int
    customer_count: int
    agent_count: int
    device_count: int
    shared_entities: dict[str, Any] = Field(default_factory=dict)
    transaction_ids: list[str] = Field(default_factory=list)
    evidence: list[RiskEvidence] = Field(default_factory=list)


class RiskCaseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    status: str
    created_at: datetime
    updated_at: datetime
    campaign_id: str | None = None
    decision_ids: list[str] = Field(default_factory=list)
    transaction_ids: list[str] = Field(default_factory=list)
    severity: Severity
    summary: str
    evidence: list[RiskEvidence] = Field(default_factory=list)
    analyst_notes: list[str] = Field(default_factory=list)
    resolution: str | None = None
