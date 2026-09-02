"""Veyra Enterprise Security Headers & HTTPS Enforcement Middleware (Checklist Items 18, 19).

Injects standard security headers onto all outgoing responses:
1. Content-Security-Policy (CSP)
2. Strict-Transport-Security (HSTS)
3. X-Content-Type-Options: nosniff
4. X-Frame-Options: SAMEORIGIN
5. X-XSS-Protection: 1; mode=block
6. Referrer-Policy: strict-origin-when-cross-origin
7. Permissions-Policy: camera=(), microphone=(), geolocation=()
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.core.config import settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Item 19: Force HTTPS redirection in production environments
        if settings.environment == "production":
            proto = request.headers.get("x-forwarded-proto", request.url.scheme)
            if proto == "http":
                secure_url = request.url.replace(scheme="https")
                return RedirectResponse(url=str(secure_url), status_code=301)

        response = await call_next(request)

        # Item 18: Enterprise Security Headers
        headers = response.headers

        # Prevent MIME type sniffing
        headers["X-Content-Type-Options"] = "nosniff"

        # Prevent clickjacking
        headers["X-Frame-Options"] = "SAMEORIGIN"

        # Cross-Site Scripting filter
        headers["X-XSS-Protection"] = "1; mode=block"

        # Referrer Policy
        headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Feature / Permissions Policy
        headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"

        # HSTS (Strict-Transport-Security)
        if settings.environment == "production":
            headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"

        # Content-Security-Policy
        headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn-cookieyes.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data: https: blob:; "
            "frame-src 'self' https://www.youtube.com https://youtube.com; "
            "connect-src 'self' http://localhost:8008 https: ws: wss:; "
            "object-src 'none'; "
            "base-uri 'self';"
        )

        return response
