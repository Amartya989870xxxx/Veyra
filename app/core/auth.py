"""Veyra Authentication, RBAC, and Multi-Tenant Authorization.

This is THE single source of truth for principal identity and tenant scoping. Every
route that touches merchant-specific data must depend on `get_current_principal` to
authenticate, and use `resolve_tenant_scope` (when a merchant_id can be supplied by the
caller) or `verify_tenant_access` (when a resource's merchant_id is already known, e.g.
after loading a row) to authorize.

`app/api/deps.py` owns everything that is not identity: DB sessions, the ingestion
service, rate limiting. It used to also own a second, disconnected auth mechanism
(`require_api_key`, a single global bearer token with no notion of merchant or role);
that function is gone, and `app/api/v1/events.py` now depends on `get_current_principal`
like every other router. One dependency, one place credentials are checked, one place
tenant identity is established.

Environments and the demo bypass
---------------------------------
A real credential check (a token matched against `settings.api_keys`) is always
available and always tried first. Outside `production`, when no credentials were
supplied and `settings.auth_required` is False (the default), a request falls back to
an explicit, single, clearly-named principal (`is_demo_bypass=True`) whose tenant
identity comes from the `X-Merchant-ID` header rather than a verified credential. This
is what keeps the demo UI, `/v2/demo/*`, and the existing integration test suite
working with zero configuration on a laptop.

The bypass cannot activate in production by construction, not by convention:
`settings.auth_required` is unconditionally `True` when `environment == "production"`
(see `Settings.auth_required`), and `get_current_principal` only reaches the bypass
branch when `auth_required` is False. There is no flag that re-enables it in
production — the check is on the environment, not on `require_auth` in isolation.
"""

from __future__ import annotations

import secrets
from enum import Enum
from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

DEMO_BYPASS_DEFAULT_MERCHANT_ID = "m_electronics_01"


class UserRole(str, Enum):
    VIEWER = "viewer"
    ANALYST = "analyst"
    MERCHANT_ADMIN = "merchant_admin"
    SYSTEM_SERVICE = "system_service"


class AuthenticatedPrincipal:
    def __init__(
        self,
        principal_id: str,
        merchant_id: str,
        role: UserRole,
        scopes: list[str] | None = None,
        is_demo_bypass: bool = False,
    ):
        self.principal_id = principal_id
        self.merchant_id = merchant_id
        self.role = role
        self.scopes = scopes or []
        self.is_demo_bypass = is_demo_bypass

    def can_access_merchant(self, target_merchant_id: str) -> bool:
        """Row-Level Security: can this principal read/write `target_merchant_id`'s data?

        `system_service` (a platform-level credential, not tied to one merchant) and the
        non-production demo bypass are the only principals trusted across tenants.
        Everyone else is pinned to their own `merchant_id`.
        """
        if self.role == UserRole.SYSTEM_SERVICE or self.is_demo_bypass:
            return True
        return self.merchant_id == target_merchant_id


api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_auth = HTTPBearer(auto_error=False)


def _lookup_configured_principal(token: str) -> AuthenticatedPrincipal | None:
    """Match a bearer credential against `settings.api_keys`.

    Constant-time comparison per candidate; the configured key list is expected to be
    small (a handful of merchant/service credentials), not a general-purpose user
    directory. `role` values that don't map to a known `UserRole` are treated as
    unmatched rather than raising, so one malformed config entry cannot 500 every
    authenticated request.
    """
    for entry in settings.api_keys:
        if secrets.compare_digest(entry.key, token):
            try:
                role = UserRole(entry.role)
            except ValueError:
                continue
            return AuthenticatedPrincipal(
                principal_id=f"key:{entry.merchant_id}:{role.value}",
                merchant_id=entry.merchant_id,
                role=role,
            )
    return None


async def get_current_principal(
    api_key: Optional[str] = Security(api_key_header),
    bearer: Optional[HTTPAuthorizationCredentials] = Security(bearer_auth),
    merchant_header: Optional[str] = Header(None, alias="X-Merchant-ID"),
) -> AuthenticatedPrincipal:
    """Authenticate the caller and return their principal. THE auth dependency."""
    token = api_key or (bearer.credentials if bearer else None)

    if token:
        principal = _lookup_configured_principal(token)
        if principal is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API credentials.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return principal

    if settings.auth_required:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided. Include X-API-Key or Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Unreachable when settings.auth_required is True (always true in production).
    return AuthenticatedPrincipal(
        principal_id="demo_bypass",
        merchant_id=merchant_header or DEMO_BYPASS_DEFAULT_MERCHANT_ID,
        role=UserRole.ANALYST,
        scopes=["read", "write"],
        is_demo_bypass=True,
    )


def require_role(allowed_roles: list[UserRole]):
    """RBAC Dependency: Require one of the specified roles."""
    async def role_checker(
        principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)]
    ) -> AuthenticatedPrincipal:
        if (
            principal.role not in allowed_roles
            and principal.role != UserRole.SYSTEM_SERVICE
            and not principal.is_demo_bypass
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: Action requires one of roles {[r.value for r in allowed_roles]}",
            )
        return principal

    return role_checker


def verify_tenant_access(principal: AuthenticatedPrincipal, merchant_id: str) -> None:
    """Row-Level Security Guard: raise 403 unless `principal` may access `merchant_id`.

    Use this when a resource's merchant_id is already known (e.g. a row was already
    loaded from the DB) and you're deciding whether to hand it back to the caller.
    """
    if not principal.can_access_merchant(merchant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access Denied: You do not have permissions to view merchant '{merchant_id}' records.",
        )


def resolve_tenant_scope(
    principal: AuthenticatedPrincipal,
    requested_merchant_id: str | None,
) -> str | None:
    """Resolve the effective merchant_id for a request, server-side.

    This is the other half of tenant isolation: `verify_tenant_access` checks a
    merchant_id you already have, this one decides which merchant_id a request is
    *allowed to ask for* before any query runs — so a client-supplied `merchant_id`
    can narrow a principal's own scope but can never widen it.

    - `system_service` (platform credential): the requested id is trusted outright,
      including `None`, which callers should treat as "no tenant filter" (e.g. an
      admin listing incidents across every merchant). This is the only path where
      `None` means "unscoped" rather than "use my own merchant".
    - demo bypass (non-production convenience): behaves like `system_service` for a
      specific id, but defaults to the bypass principal's own merchant_id — never
      "unscoped" — when none is supplied, preserving prior demo behaviour.
    - every other principal: pinned to their own `merchant_id`. An unspecified
      request defaults to it; a request naming a *different* merchant_id is denied
      with 403 rather than silently redirected to the caller's own tenant, so the
      mismatch is visible to the client instead of producing confusing data.
    """
    if principal.role == UserRole.SYSTEM_SERVICE:
        return requested_merchant_id

    if principal.is_demo_bypass:
        return requested_merchant_id or principal.merchant_id

    if requested_merchant_id is not None and requested_merchant_id != principal.merchant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Access Denied: authenticated principal is scoped to merchant "
                f"'{principal.merchant_id}' and cannot access '{requested_merchant_id}'."
            ),
        )
    return principal.merchant_id
