"""Semantic verifier interface and its strict output contract.

The trust boundary is explicit: an LLM may *classify* whether a proposed payment reads as
consistent with a natural-language instruction. It cannot decide anything. Its output must
validate against :class:`SemanticVerdict` or it is rejected outright — never coerced,
never defaulted, never averaged with a guess.

The instruction text is untrusted input. It is passed as data inside a delimited block with
an explicit statement that it must not be treated as instructions, and the only thing that
can come back is a small fixed JSON object.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.entities import IntentContract, Transaction


class SemanticVerdict(BaseModel):
    """The only shape a semantic provider is allowed to return."""

    model_config = ConfigDict(extra="forbid")

    aligned: bool = Field(..., description="Does the payment match the stated instruction?")
    mismatch_score: float = Field(
        ..., ge=0.0, le=1.0, description="0 = fully consistent, 1 = clearly inconsistent"
    )
    mismatch_reasons: list[str] = Field(default_factory=list, max_length=5)
    ambiguous: bool = Field(
        default=False, description="True when the instruction cannot settle the question"
    )
    confidence: float = Field(..., ge=0.0, le=1.0)

    @property
    def usable(self) -> bool:
        """Low-confidence or ambiguous verdicts inform evidence but must not move the score."""
        return not self.ambiguous and self.confidence >= 0.5


class SemanticResult(BaseModel):
    """Wrapper carrying either a verdict or an explicit failure. Never both, never neither."""

    model_config = ConfigDict(extra="forbid")

    verdict: SemanticVerdict | None = None
    provider: str
    model: str
    latency_ms: float = 0.0
    error_code: str | None = None
    error_detail: str | None = None
    raw_excerpt: str | None = None

    @property
    def ok(self) -> bool:
        return self.verdict is not None and self.error_code is None


@runtime_checkable
class SemanticVerifier(Protocol):
    provider: str
    model: str

    async def verify_intent(
        self,
        transaction: Transaction,
        intent: IntentContract | None,
        instruction_text: str | None,
        action_types: list[str],
    ) -> SemanticResult:
        ...

    async def health(self) -> bool:
        ...
