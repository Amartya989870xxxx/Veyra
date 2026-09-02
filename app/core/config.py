"""Application settings.

All secrets come from the environment. Nothing sensitive is defaulted in code, and
``.env.example`` documents every key without carrying a value.

``environment`` includes ``"production"`` on purpose (it did not, previously — a
literal type that could never equal the string every downstream security check
compared against, which made every ``environment == "production"`` gate in the
codebase dead code). The ``_production_fails_closed`` validator below is what makes
that value load-bearing rather than decorative: constructing ``Settings()`` with
``environment=production`` and any required secret missing raises immediately, so a
misconfigured production deployment fails at startup instead of silently running
open.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "ci", "demo", "production"]


class ApiKeyEntry(BaseModel):
    """One configured principal. Source of truth for ``VEYRA_API_KEYS`` (JSON array).

    Example: ``[{"key": "vy_...", "merchant_id": "m_electronics_01", "role": "analyst"}]``.
    ``role`` must be one of ``app.core.auth.UserRole``'s values; validated there rather
    than imported here to avoid a config<->auth import cycle.
    """

    key: str
    merchant_id: str
    role: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", env_prefix="VEYRA_"
    )

    environment: Environment = "local"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    # --- storage -------------------------------------------------------------------
    # SQLite keeps the prototype runnable with zero infrastructure; PostgreSQL is the
    # intended system of record and is exercised by the same ORM models unchanged.
    database_url: str = "sqlite+aiosqlite:///./veyra.db"
    db_echo: bool = False
    db_pool_size: int = 10

    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = True
    redis_timeout_seconds: float = 0.5

    # --- api -----------------------------------------------------------------------
    # `require_auth` forces credential checking outside production too (e.g. for a
    # staging environment or a targeted test); production requires it unconditionally
    # regardless of this flag — see `auth_required` below.
    require_auth: bool = False
    api_keys: list[ApiKeyEntry] = Field(
        default_factory=list,
        description=(
            "Configured principals as a JSON array via VEYRA_API_KEYS, e.g. "
            '[{"key":"vy_...","merchant_id":"m_electronics_01","role":"analyst"}]. '
            "Required when environment=production."
        ),
    )
    max_request_bytes: int = 1_048_576
    max_event_trace_items: int = 500
    rate_limit_per_minute: int = 600

    # --- cors ------------------------------------------------------------------------
    cors_allowed_origins: str = Field(
        default="",
        description=(
            "Comma-separated exact origins allowed to make credentialed cross-origin "
            "requests, e.g. https://app.example.com,https://staging.example.com. "
            "Never a wildcard when credentials are allowed. Required when "
            "environment=production."
        ),
    )

    # --- crypto ----------------------------------------------------------------------
    crypto_pepper: str | None = Field(
        default=None,
        description=(
            "Master secret for AES-GCM key derivation and HMAC-SHA256 instrument "
            "tokenization (app/core/crypto.py). No production default exists in code — "
            "outside production, an explicit, clearly-labelled dev-only constant is used "
            "instead so a laptop run still works. Required when environment=production."
        ),
    )

    # --- semantic (LLM) layer ------------------------------------------------------
    semantic_enabled: bool = False
    semantic_provider: Literal["null", "anthropic"] = "null"
    semantic_model: str = "claude-sonnet-5"
    semantic_api_key: str | None = None
    semantic_timeout_seconds: float = 8.0
    semantic_max_output_tokens: int = 512

    # --- risk engine ---------------------------------------------------------------
    artifact_dir: str = "artifacts"
    report_dir: str = "reports"
    model_dir: str = "artifacts/models"
    graph_window_seconds: int = 900
    graph_window_max_events: int = 5000

    # --- expected-loss model (all synthetic, documented assumptions) ---------------
    fn_cost_multiplier: float = Field(
        default=1.0, description="Merchant loss per missed abusive txn, as a multiple of amount"
    )
    fp_cost_multiplier: float = Field(
        default=0.25, description="Lost margin/goodwill per wrongly blocked legit txn"
    )
    review_cost_flat: float = Field(default=40.0, description="Analyst cost per manual review, INR")
    chargeback_fee_flat: float = Field(
        default=750.0, description="Flat dispute/chargeback handling fee per missed abuse, INR"
    )

    @field_validator("semantic_api_key", "crypto_pepper", mode="before")
    @classmethod
    def _blank_to_none(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def semantic_is_configured(self) -> bool:
        """Semantic verification only runs when explicitly enabled AND credentialed."""
        if not self.semantic_enabled or self.semantic_provider == "null":
            return False
        return bool(self.semantic_api_key)

    @property
    def auth_required(self) -> bool:
        """Whether requests must present a real, configured credential.

        Production requires this unconditionally — it does not read `require_auth` at
        all, so there is no flag that can leave production open by omission or a typo.
        Every other environment honours `require_auth` explicitly, off by default so a
        local run or the test suite needs no credentials.
        """
        return self.environment == "production" or self.require_auth

    @property
    def cors_origins_list(self) -> list[str]:
        """Configured origins, with a literal ``"*"`` always dropped.

        This app always sends ``allow_credentials=True``, so a wildcard origin would be
        a real cross-site request forgery exposure, not just a spec violation some
        browsers ignore. Silently dropping it (rather than passing it through) means a
        `VEYRA_CORS_ALLOWED_ORIGINS=*` misconfiguration degrades to "no trusted
        origins" instead of "every origin trusted".
        """
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip() and o.strip() != "*"]

    @model_validator(mode="after")
    def _production_fails_closed(self) -> "Settings":
        """Refuse to construct a production Settings object with missing secrets.

        This runs at `Settings()` construction time, i.e. at import/startup — a
        production process with a missing pepper, no configured API keys, or no CORS
        allowlist never reaches a point where it could serve a request insecurely; it
        never starts.
        """
        if self.environment != "production":
            return self

        missing = []
        if not self.crypto_pepper:
            missing.append("VEYRA_CRYPTO_PEPPER")
        if not self.api_keys:
            missing.append("VEYRA_API_KEYS")
        if not self.cors_origins_list:
            # Empty because it was never set, OR because the only entries given were
            # "*" and got dropped by cors_origins_list — both are "no real allowlist".
            missing.append("VEYRA_CORS_ALLOWED_ORIGINS (non-wildcard origin required)")
        if missing:
            raise ValueError(
                "Refusing to start with environment=production while required "
                f"secrets/config are unset: {', '.join(missing)}. Production must fail "
                "closed rather than silently fall back to insecure defaults."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
