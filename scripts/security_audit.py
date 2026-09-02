#!/usr/bin/env python3
"""Veyra Security Invariant Audit.

This replaces a prior version of this script that printed "ALL 20 PRODUCTION SECURITY
CONTROLS: PASSED" while checking only crypto round-trips, a rate-limiter counter, and a
regex secret scan — none of which would have caught the auth-not-wired-into-routes,
hardcoded-crypto-fallback, or unreachable-production-environment issues this hardening
pass fixed. Every check below exercises the actual code path it claims to validate
(a real HTTP request through the real FastAPI app, a real Settings() construction) rather
than a proxy for it, per the "prefer integration tests over superficial grep checks"
principle.

What this script does NOT do: penetration testing, dependency/CVE scanning, secrets-in-git-
history scanning, infrastructure/network security, or anything covering categories this
repository doesn't implement (WAF, key rotation, intrusion detection). A clean run means
"the invariants below hold right now" — it is not a certification and this script does not
print language implying one.

Exit code is 0 only if every check passes.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

SECRET_PATTERNS = [
    (re.compile(r"(?i)(api[_-]?key|secret|password|auth_token)\s*=\s*['\"][a-zA-Z0-9_\-]{16,}['\"]"), "Potential hardcoded secret"),
    (re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"), "Committed private key"),
    (re.compile(r"ghp_[0-9a-zA-Z]{36}"), "GitHub Personal Access Token"),
    (re.compile(r"sk_live_[0-9a-zA-Z]{24}"), "Stripe Live Key"),
]

IGNORED_DIRS = {".git", ".venv", "node_modules", "dist", ".gemini", "__pycache__", "tests"}

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail and not ok else ""))


def scan_secrets(root_dir: Path) -> list[str]:
    violations = []
    for path in root_dir.rglob("*"):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix in {".py", ".ts", ".tsx", ".js", ".json", ".yaml", ".yml", ".env"}:
            if path.name.startswith(".env.example"):
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
                for pattern, desc in SECRET_PATTERNS:
                    if pattern.search(content):
                        violations.append(f"{desc} in {path.relative_to(root_dir)}")
            except Exception:
                pass
    return violations


def check_secret_scan(root: Path) -> None:
    violations = scan_secrets(root)
    record(
        "1. No hardcoded secret-shaped literals (`key = \"...\"` pattern, PEM keys, known token formats)",
        not violations,
        "; ".join(violations),
    )
    # This is a narrow pattern scan, not a leak-detection guarantee — say so.
    print("       note: pattern-based; does not prove absence of leaked secrets in other forms.")


def check_production_fails_closed_without_secrets() -> None:
    """A production Settings object must refuse to construct with no secrets configured."""
    from app.core.config import Settings

    try:
        Settings(
            environment="production",
            crypto_pepper=None,
            api_keys=[],
            cors_allowed_origins="",
        )
        record("2. Production Settings() refuses to construct with no secrets configured", False, "no exception raised")
    except (ValueError, ValidationError):
        record("2. Production Settings() refuses to construct with no secrets configured", True)


def check_production_fails_closed_partial_secrets() -> None:
    """Missing even ONE of {pepper, api_keys, cors origins} must still fail closed."""
    from app.core.config import Settings

    ok = True
    detail = []
    cases = [
        dict(crypto_pepper=None, api_keys=[{"key": "k", "merchant_id": "m", "role": "analyst"}], cors_allowed_origins="https://a.example"),
        dict(crypto_pepper="p", api_keys=[], cors_allowed_origins="https://a.example"),
        dict(crypto_pepper="p", api_keys=[{"key": "k", "merchant_id": "m", "role": "analyst"}], cors_allowed_origins=""),
    ]
    for case in cases:
        try:
            Settings(environment="production", **case)
            ok = False
            detail.append(f"did not raise for {case}")
        except (ValueError, ValidationError):
            pass
    record("3. Production fails closed on ANY single missing secret (pepper / api_keys / CORS origins)", ok, "; ".join(detail))


def check_production_settings_valid_when_configured() -> None:
    """A fully-configured production Settings object must construct successfully."""
    from app.core.config import Settings

    try:
        s = Settings(
            environment="production",
            crypto_pepper="a-real-pepper",
            api_keys=[{"key": "vy_prod_x", "merchant_id": "m_1", "role": "analyst"}],
            cors_allowed_origins="https://app.example.com",
        )
        record("4. Fully-configured production Settings() constructs successfully", s.environment == "production" and s.auth_required is True)
    except Exception as e:
        record("4. Fully-configured production Settings() constructs successfully", False, str(e))


def check_crypto_no_production_fallback() -> None:
    """`_effective_pepper` must raise in production when no pepper is configured, not
    silently fall back to the dev-only constant."""
    from app.core import crypto
    from app.core.config import settings as live_settings

    original_env = live_settings.environment
    original_pepper = live_settings.crypto_pepper
    try:
        live_settings.environment = "production"
        live_settings.crypto_pepper = None
        try:
            crypto._effective_pepper(None)
            record("5. Crypto pepper resolution raises (does not fall back) when unset in production", False, "no exception raised")
        except RuntimeError:
            record("5. Crypto pepper resolution raises (does not fall back) when unset in production", True)
    finally:
        live_settings.environment = original_env
        live_settings.crypto_pepper = original_pepper


def check_crypto_roundtrip() -> None:
    from app.core.crypto import decrypt_sensitive_field, encrypt_sensitive_field, tokenize_instrument

    test_pii = "4111-2222-3333-4444"
    enc = encrypt_sensitive_field(test_pii)
    dec = decrypt_sensitive_field(enc)
    tok = tokenize_instrument(test_pii)
    record(
        "6. AES-GCM encrypt/decrypt round-trip and HMAC tokenization prefix",
        dec == test_pii and tok.startswith("ins_tok_") and enc != test_pii,
    )


def check_password_hashing() -> None:
    from app.core.security import hash_password, verify_password

    pw = "SuperSecurePassword2026!"
    h = hash_password(pw)
    record(
        "7. PBKDF2-HMAC-SHA256 password hashing verifies correct and rejects incorrect",
        h.startswith("pbkdf2:sha256:600000$") and verify_password(pw, h) and not verify_password("WrongPassword", h),
    )


def check_rate_limiter() -> None:
    from app.api.middleware.rate_limit import RateLimiter

    limiter = RateLimiter()  # fresh instance — do not share state with the running app
    a, _ = limiter.is_allowed("audit_probe_client", limit_per_minute=2)
    b, _ = limiter.is_allowed("audit_probe_client", limit_per_minute=2)
    c, _ = limiter.is_allowed("audit_probe_client", limit_per_minute=2)
    record("8. Sliding-window rate limiter blocks after the configured limit", a and b and not c)


async def _check_routes_require_auth_async() -> None:
    """The check the previous audit script could not have caught: does an unauthenticated
    request to a sensitive route actually get rejected when auth is required?

    Constructs an isolated app instance with auth forced on via dependency override rather
    than mutating global settings, so this does not interfere with the rest of the suite or
    depend on environment=production (which has its own stricter, separately-tested path).
    """
    from fastapi import HTTPException

    from app.core.auth import get_current_principal
    from app.main import app

    def _deny_all():
        raise HTTPException(status_code=401, detail="Authentication credentials were not provided.")

    app.dependency_overrides[get_current_principal] = _deny_all
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://audit") as client:
            checks = [
                ("POST", "/v2/score-window", {"merchant_id": "m_1"}),
                ("GET", "/v2/incidents", None),
                ("GET", "/v2/merchants/m_1/baselines", None),
                ("GET", "/v2/demo/scenarios", None),
                ("POST", "/api/v1/events", {"event_id": "e1", "event_type": "PAYMENT_ATTEMPT", "timestamp": "2026-01-01T00:00:00Z", "payment_attempt": {}}),
            ]
            all_denied = True
            details = []
            for method, path, body in checks:
                resp = await (client.post(path, json=body) if method == "POST" else client.get(path))
                if resp.status_code != 401:
                    all_denied = False
                    details.append(f"{method} {path} -> {resp.status_code} (expected 401)")
            record(
                "9. Every merchant-data route (scoring, incidents, baselines, demo, ingestion) "
                "rejects a request when authentication is denied",
                all_denied,
                "; ".join(details),
            )
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


async def _check_tenant_isolation_async() -> None:
    """Behavioural cross-tenant check: two configured principals for two different
    merchants; principal A must not be able to read merchant B's incidents via a
    client-supplied merchant_id."""
    from app.core.auth import AuthenticatedPrincipal, UserRole, get_current_principal
    from app.main import app

    principal_a = AuthenticatedPrincipal("p_a", "m_alpha", UserRole.ANALYST)

    app.dependency_overrides[get_current_principal] = lambda: principal_a
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://audit") as client:
            resp = await client.get("/v2/merchants/m_bravo/baselines")
            denied = resp.status_code == 403
            record(
                "10. A principal scoped to one merchant is denied (403) when requesting another "
                "merchant's baselines via a client-supplied merchant_id",
                denied,
                f"got {resp.status_code}",
            )
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


def check_cors_no_wildcard_with_credentials() -> None:
    """A literal '*' in VEYRA_CORS_ALLOWED_ORIGINS must never become a trusted origin.

    `cors_origins_list` drops a literal "*" unconditionally (this app always sends
    allow_credentials=True, so a wildcard origin there is a real CSRF exposure, not a
    spec technicality). Setting production's origins to only "*" must therefore fail
    closed exactly like leaving it unset — verified both ways below.
    """
    from app.core.config import Settings

    non_production_dropped = "*" not in Settings(
        environment="local", cors_allowed_origins="*,https://kept.example"
    ).cors_origins_list

    production_wildcard_only_rejected = False
    try:
        Settings(
            environment="production",
            crypto_pepper="p",
            api_keys=[{"key": "k", "merchant_id": "m", "role": "analyst"}],
            cors_allowed_origins="*",
        )
    except (ValueError, ValidationError):
        production_wildcard_only_rejected = True

    record(
        "11. A literal '*' in VEYRA_CORS_ALLOWED_ORIGINS is dropped everywhere, and "
        "production fails closed if '*' is the only configured origin",
        non_production_dropped and production_wildcard_only_rejected,
        f"dropped_outside_prod={non_production_dropped} prod_rejected_wildcard_only={production_wildcard_only_rejected}",
    )


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    print("=" * 70)
    print("VEYRA SECURITY INVARIANT AUDIT")
    print("This validates specific, enumerated invariants below. It is not a")
    print("penetration test, a compliance certification, or proof the system")
    print("cannot be compromised.")
    print("=" * 70)

    check_secret_scan(root)
    check_production_fails_closed_without_secrets()
    check_production_fails_closed_partial_secrets()
    check_production_settings_valid_when_configured()
    check_crypto_no_production_fallback()
    check_crypto_roundtrip()
    check_password_hashing()
    check_rate_limiter()
    asyncio.run(_check_routes_require_auth_async())
    asyncio.run(_check_tenant_isolation_async())
    check_cors_no_wildcard_with_credentials()

    print("=" * 70)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"{passed}/{total} checks passed.")
    print("=" * 70)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
