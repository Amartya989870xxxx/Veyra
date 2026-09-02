"""Veyra Rate Limiting & Bot Defense Middleware (Checklist Items 11, 12, 16).

Provides:
1. In-memory sliding window rate limiting per IP / API key.
2. Bot & Automated scanner signature detection.
3. Maximum payload size restriction (prevents body buffer overflow DoS).
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Dict, List, Tuple

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

MAX_REQUEST_BODY_SIZE = 10 * 1024 * 1024  # 10 MB limit (Item 16)
DEFAULT_MAX_REQUESTS_PER_MINUTE = 600
LOGIN_MAX_REQUESTS_PER_MINUTE = 30

KNOWN_MALICIOUS_USER_AGENTS = {
    "sqlmap",
    "nikto",
    "dirbuster",
    "hydra",
    "wpscan",
    "nessus",
}


class RateLimiter:
    def __init__(self):
        # Maps client_identifier -> list of request timestamps
        self._history: Dict[str, List[float]] = defaultdict(list)

    def is_allowed(self, client_id: str, limit_per_minute: int = DEFAULT_MAX_REQUESTS_PER_MINUTE) -> Tuple[bool, int]:
        now = time.time()
        window_start = now - 60.0
        
        # Prune older than 60s
        self._history[client_id] = [t for t in self._history[client_id] if t > window_start]
        
        current_count = len(self._history[client_id])
        if current_count >= limit_per_minute:
            return False, current_count
        
        self._history[client_id].append(now)
        return True, current_count + 1


rate_limiter = RateLimiter()


class RateLimitAndBotProtectionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "").lower()
        api_key = request.headers.get("x-api-key", "")
        client_id = f"{client_ip}:{api_key}" if api_key else client_ip

        # Item 12: Bot & Scanner signature blocking
        for bot_sig in KNOWN_MALICIOUS_USER_AGENTS:
            if bot_sig in user_agent:
                return JSONResponse(
                    status_code=403,
                    content={"error": "Forbidden: Automated scanner or malicious bot signature detected."},
                )

        # Item 16: Check content-length header to restrict oversized uploads
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_REQUEST_BODY_SIZE:
            return JSONResponse(
                status_code=413,
                content={"error": "Payload Too Large: Request body exceeds maximum allowed 10MB limit."},
            )

        # Item 11: Rate limiting (stricter for auth/login endpoints, standard for events)
        limit = LOGIN_MAX_REQUESTS_PER_MINUTE if "/auth" in request.url.path else DEFAULT_MAX_REQUESTS_PER_MINUTE
        allowed, current_reqs = rate_limiter.is_allowed(client_id, limit_per_minute=limit)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too Many Requests",
                    "detail": f"Rate limit of {limit} requests/minute exceeded. Please back off.",
                },
                headers={"Retry-After": "60"},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - current_reqs))
        return response
