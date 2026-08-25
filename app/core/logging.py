"""Structured JSON logging with request/event/decision correlation.

Correlation IDs live in context vars so any module can log without threading a logger
argument through the call stack. A redaction pass strips anything that looks like a
secret before it reaches a handler (PRD §26).
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from typing import Any

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)
event_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("event_id", default=None)
decision_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "decision_id", default=None
)

_SENSITIVE_KEY = re.compile(
    r"(pass(word)?|secret|token|api[_-]?key|authorization|cvv|otp|pan|card[_-]?number)", re.I
)
_CARD_LIKE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")

_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
    "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs",
    "relativeCreated", "thread", "threadName", "processName", "process", "taskName",
    "message", "asctime",
}


def redact(value: Any, _depth: int = 0) -> Any:
    """Recursively drop secret-looking keys and mask card-like digit runs."""
    if _depth > 6:
        return "<truncated>"
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if _SENSITIVE_KEY.search(str(k)):
                out[k] = "<redacted>"
            else:
                out[k] = redact(v, _depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(v, _depth + 1) for v in value[:100]]
    if isinstance(value, str):
        if _CARD_LIKE.search(value):
            return _CARD_LIKE.sub("<redacted-number>", value)
        return value[:2000]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, var in (
            ("request_id", request_id_var),
            ("event_id", event_id_var),
            ("decision_id", decision_id_var),
        ):
            value = var.get()
            if value:
                payload[key] = value
        extras = {k: v for k, v in record.__dict__.items() if k not in _RESERVED and k[0] != "_"}
        if extras:
            payload.update(redact(extras))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rid = request_id_var.get()
        prefix = f"[{rid}] " if rid else ""
        return f"{record.levelname:<7} {record.name:<28} {prefix}{record.getMessage()}"


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt == "json" else ConsoleFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
    for noisy in ("uvicorn.access", "sqlalchemy.engine.Engine", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
