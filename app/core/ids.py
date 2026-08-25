"""Deterministic, human-readable synthetic identifiers.

Tyche never handles real customer identity. Every ID here is a synthetic token with a
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


def case_id() -> str:
    return new_id("case")


def run_id() -> str:
    return new_id("run")


def campaign_id() -> str:
    return new_id("camp")


def stable_hash(payload: str) -> str:
    """Content hash used for feature snapshots and idempotency fingerprints."""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
