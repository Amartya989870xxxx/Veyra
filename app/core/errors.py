"""Typed error taxonomy.

Errors carry a stable machine code so clients and the audit trail can branch on the
failure class rather than parsing prose.
"""

from __future__ import annotations


class TycheError(Exception):
    """Base class for all Tyche errors."""

    code = "tyche_error"
    http_status = 500

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


class ValidationError(TycheError):
    code = "validation_error"
    http_status = 422


class UnknownSchemaError(TycheError):
    code = "unknown_schema_version"
    http_status = 422


class NotFoundError(TycheError):
    code = "not_found"
    http_status = 404


class ConflictError(TycheError):
    code = "conflict"
    http_status = 409


class AuthError(TycheError):
    code = "unauthorized"
    http_status = 401


class RateLimitedError(TycheError):
    code = "rate_limited"
    http_status = 429


class PersistenceError(TycheError):
    """The decision store is unavailable. We must not claim a decision was persisted."""

    code = "persistence_unavailable"
    http_status = 503


class SemanticProviderError(TycheError):
    """The LLM provider failed, timed out, or returned unusable output."""

    code = "semantic_provider_error"
    http_status = 502


class MalformedModelOutputError(SemanticProviderError):
    """The LLM returned output that failed strict schema validation. Never coerce it."""

    code = "malformed_model_output"
    http_status = 502


class PayloadTooLargeError(TycheError):
    code = "payload_too_large"
    http_status = 413
