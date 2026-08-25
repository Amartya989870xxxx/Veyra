"""Application settings.

All secrets come from the environment. Nothing sensitive is defaulted in code, and
``.env.example`` documents every key without carrying a value.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", env_prefix="TYCHE_"
    )

    environment: Literal["local", "test", "ci", "demo"] = "local"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    # --- storage -------------------------------------------------------------------
    # SQLite keeps the prototype runnable with zero infrastructure; PostgreSQL is the
    # intended system of record and is exercised by the same ORM models unchanged.
    database_url: str = "sqlite+aiosqlite:///./tyche.db"
    db_echo: bool = False
    db_pool_size: int = 10

    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = True
    redis_timeout_seconds: float = 0.5

    # --- api -----------------------------------------------------------------------
    api_key: str | None = Field(default=None, description="Static bearer key; unset disables auth")
    require_auth: bool = False
    max_request_bytes: int = 1_048_576
    max_event_trace_items: int = 500
    rate_limit_per_minute: int = 600

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

    @field_validator("semantic_api_key", "api_key", mode="before")
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
