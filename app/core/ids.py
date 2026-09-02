"""Deterministic, human-readable synthetic identifiers.

Veyra never handles real customer identity. Every ID here is a synthetic token with a
type prefix so that a raw log line is self-describing (``dec_...`` is a decision, and so on).
"""

from __future__ import annotations

import hashlib
import time
import uuid


def _ulid_like() -> str:
    """A lexicographically sortable, collision-resistant token.

    48-bit millisecond timestamp + 80 bits of randomness, base32-ish hex encoded. Sortable
    IDs keep decision tables naturally time-ordered without an extra index.
    """
    ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    rand = uuid.uuid4().int & ((1 << 80) - 1)
    return f"{ms:012x}{rand:020x}"


def new_id(prefix: str) -> str:
    return f"{prefix}_{_ulid_like()}"


def decision_id() -> str:
    return new_id("dec")


def event_id() -> str:
    return new_id("evt")


def request_id() -> str:
    return new_id("req")


def incident_id() -> str:
    return new_id("inc")


def scoped_incident_id(merchant_id: str, kind: str, window_end: object) -> str:
    """A stable incident ID for one merchant's window.

    Unlike :func:`incident_id`, this is derived rather than random. Scoring the same
    merchant-window twice has to resolve to the same incident so that the incident store
    upserts instead of accumulating a duplicate per re-score, which means the identifier
    must be a function of what the incident *is* rather than of when it was created.
    """
    return f"inc_{stable_hash(f'{merchant_id}|{kind}|{window_end}')[:26]}"


def run_id() -> str:
    return new_id("run")


def stable_hash(payload: str) -> str:
    """Content hash used for feature snapshots and idempotency fingerprints."""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
