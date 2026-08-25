"""Redis hot-state with an explicit, bounded local fallback.

Redis carries sliding-window counters, dedupe keys and rate limits. When it is
unreachable the system does not silently pretend the counters are correct: it flips to a
bounded in-process store, records ``temporal_state`` as a degraded component, and the
caller surfaces that in the decision (PRD §25.4).
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

DEGRADED_TEMPORAL = "temporal_state"


class LocalWindowStore:
    """Bounded in-process sliding-window counters used only when Redis is unavailable.

    Bounded on purpose: a single process must never accumulate unbounded fraud state and
    then present it as if it were the system-wide view.
    """

    MAX_KEYS = 20_000
    MAX_PER_KEY = 512

    def __init__(self) -> None:
        self._windows: dict[str, deque[float]] = defaultdict(deque)
        self._values: dict[str, tuple[str, float]] = {}
        self._sets: dict[str, set[str]] = defaultdict(set)

    def _evict_if_needed(self) -> None:
        if len(self._windows) > self.MAX_KEYS:
            for key in list(self._windows.keys())[: len(self._windows) - self.MAX_KEYS]:
                self._windows.pop(key, None)

    def incr_window(self, key: str, now: float, window_seconds: int) -> int:
        series = self._windows[key]
        series.append(now)
        cutoff = now - window_seconds
        while series and series[0] < cutoff:
            series.popleft()
        while len(series) > self.MAX_PER_KEY:
            series.popleft()
        self._evict_if_needed()
        return len(series)

    def count_window(self, key: str, now: float, window_seconds: int) -> int:
        series = self._windows.get(key)
        if not series:
            return 0
        cutoff = now - window_seconds
        return sum(1 for ts in series if ts >= cutoff)

    def set_if_absent(self, key: str, value: str, ttl_seconds: int, now: float) -> bool:
        existing = self._values.get(key)
        if existing and existing[1] > now:
            return False
        self._values[key] = (value, now + ttl_seconds)
        return True

    def get(self, key: str, now: float) -> str | None:
        existing = self._values.get(key)
        if not existing or existing[1] <= now:
            return None
        return existing[0]

    def sadd(self, key: str, member: str) -> int:
        bucket = self._sets[key]
        before = len(bucket)
        if len(bucket) < self.MAX_PER_KEY:
            bucket.add(member)
        return len(bucket) - before

    def scard(self, key: str) -> int:
        return len(self._sets.get(key, ()))

    def clear(self) -> None:
        self._windows.clear()
        self._values.clear()
        self._sets.clear()


class HotStateClient:
    """Facade over Redis with automatic degradation.

    Every method returns ``(value, degraded)`` so the caller cannot accidentally treat a
    fallback reading as authoritative.
    """

    def __init__(self, url: str | None = None, enabled: bool | None = None) -> None:
        settings = get_settings()
        self._url = url or settings.redis_url
        self._enabled = settings.redis_enabled if enabled is None else enabled
        self._timeout = settings.redis_timeout_seconds
        self._client = None
        self._available: bool | None = None
        self._local = LocalWindowStore()
        self._lock = asyncio.Lock()

    @property
    def local(self) -> LocalWindowStore:
        return self._local

    async def _get_client(self):
        if not self._enabled:
            return None
        if self._client is not None:
            return self._client
        async with self._lock:
            if self._client is not None:
                return self._client
            try:
                import redis.asyncio as aioredis

                client = aioredis.from_url(
                    self._url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_timeout=self._timeout,
                    socket_connect_timeout=self._timeout,
                )
                await asyncio.wait_for(client.ping(), timeout=self._timeout)
                self._client = client
                self._available = True
                log.info("redis_connected")
            except Exception as exc:
                if self._available is not False:
                    log.warning("redis_unavailable_using_local_fallback", extra={"error": str(exc)})
                self._available = False
                self._client = None
        return self._client

    async def ping(self) -> bool:
        client = await self._get_client()
        if client is None:
            return False
        try:
            await asyncio.wait_for(client.ping(), timeout=self._timeout)
            return True
        except Exception:
            self._available = False
            self._client = None
            return False

    async def incr_window(self, key: str, window_seconds: int) -> tuple[int, bool]:
        """Increment a sliding-window counter. Returns ``(count, degraded)``."""
        now = time.time()
        client = await self._get_client()
        if client is not None:
            try:
                pipe = client.pipeline()
                pipe.zremrangebyscore(key, 0, now - window_seconds)
                pipe.zadd(key, {f"{now}:{id(object())}": now})
                pipe.zcard(key)
                pipe.expire(key, window_seconds + 60)
                result = await asyncio.wait_for(pipe.execute(), timeout=self._timeout)
                return int(result[2]), False
            except Exception as exc:
                log.warning("redis_incr_failed", extra={"error": str(exc), "key": key})
                self._client = None
                self._available = False
        return self._local.incr_window(key, now, window_seconds), True

    async def count_window(self, key: str, window_seconds: int) -> tuple[int, bool]:
        now = time.time()
        client = await self._get_client()
        if client is not None:
            try:
                pipe = client.pipeline()
                pipe.zremrangebyscore(key, 0, now - window_seconds)
                pipe.zcard(key)
                result = await asyncio.wait_for(pipe.execute(), timeout=self._timeout)
                return int(result[1]), False
            except Exception as exc:
                log.warning("redis_count_failed", extra={"error": str(exc), "key": key})
                self._client = None
                self._available = False
        return self._local.count_window(key, now, window_seconds), True

    async def claim_once(self, key: str, value: str, ttl_seconds: int) -> tuple[bool, bool]:
        """Best-effort dedupe claim. Returns ``(claimed, degraded)``.

        This is only a fast path: the authoritative idempotency guarantee is the unique
        constraint in PostgreSQL, so a degraded claim can never create a duplicate record.
        """
        client = await self._get_client()
        if client is not None:
            try:
                ok = await asyncio.wait_for(
                    client.set(key, value, nx=True, ex=ttl_seconds), timeout=self._timeout
                )
                return bool(ok), False
            except Exception as exc:
                log.warning("redis_claim_failed", extra={"error": str(exc)})
                self._client = None
                self._available = False
        return self._local.set_if_absent(key, value, ttl_seconds, time.time()), True

    async def get(self, key: str) -> tuple[str | None, bool]:
        client = await self._get_client()
        if client is not None:
            try:
                value = await asyncio.wait_for(client.get(key), timeout=self._timeout)
                return value, False
            except Exception:
                self._client = None
                self._available = False
        return self._local.get(key, time.time()), True

    async def add_to_set(self, key: str, member: str, ttl_seconds: int) -> tuple[int, bool]:
        client = await self._get_client()
        if client is not None:
            try:
                pipe = client.pipeline()
                pipe.sadd(key, member)
                pipe.expire(key, ttl_seconds)
                pipe.scard(key)
                result = await asyncio.wait_for(pipe.execute(), timeout=self._timeout)
                return int(result[2]), False
            except Exception:
                self._client = None
                self._available = False
        self._local.sadd(key, member)
        return self._local.scard(key), True

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # pragma: no cover
                pass
        self._client = None


_hot_state: HotStateClient | None = None


def get_hot_state() -> HotStateClient:
    global _hot_state
    if _hot_state is None:
        _hot_state = HotStateClient()
    return _hot_state


def reset_hot_state() -> None:
    global _hot_state
    _hot_state = None
