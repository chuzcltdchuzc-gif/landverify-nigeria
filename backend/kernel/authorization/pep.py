"""Policy Enforcement Point — single FastAPI dependency that:

1. Extracts the access token (Authorization: Bearer ... or `lv_access` cookie)
2. Verifies its signature via the kernel JWKS (RS256)
3. Builds the canonical ExecutionContext from token claims (NEVER from body)
4. Sets the context for the current request, propagating into all downstream
   repositories and services
5. Audits the access decision when authorize() is invoked downstream

This dependency replaces ad-hoc auth checks in routers (ADR-002, ADR-007).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import Cookie, Depends, Header, Request
from jwt import InvalidTokenError

from kernel.audit import audit
from kernel.authorization.decisions import Decision
from kernel.authorization.pdp import authorize
from kernel.errors.problem import forbidden, unauthenticated
from kernel.observability import set_correlation_id
from kernel.observability.metrics import increment
from kernel.persistence.context import (
    ANONYMOUS,
    ExecutionContext,
    current_context,
    reset_context,
    set_context,
)
from kernel.security.jwt import JwtVerifier

logger = logging.getLogger("kernel.authorization.pep")

_verifier: JwtVerifier | None = None


def configure_pep(verifier: JwtVerifier) -> None:
    """Bind the kernel JWT verifier (called once at app startup)."""
    global _verifier
    _verifier = verifier


def _extract_bearer(authorization: Optional[str], cookie_token: Optional[str]) -> Optional[str]:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    if cookie_token:
        return cookie_token.strip() or None
    return None


async def _build_context_from_token(request: Request, token: Optional[str]) -> ExecutionContext:
    if not token or _verifier is None:
        return _enrich_anonymous(request)
    try:
        claims = await _verifier.verify(token)
    except InvalidTokenError as exc:
        logger.info("invalid access token: %s", exc)
        raise unauthenticated("Invalid or expired access token",
                              code="auth.invalid_token") from exc
    if claims.get("typ") != "access":
        raise unauthenticated("Wrong token type", code="auth.wrong_token_type")

    ctx = ExecutionContext(
        principal_id=str(claims["sub"]),
        email=claims.get("email"),
        country=claims.get("country"),
        tenant_id=claims.get("tenant_id"),
        organization_id=claims.get("organization_id"),
        roles=tuple(claims.get("roles") or ()),
        scopes=tuple(claims.get("scopes") or ()),
        attributes=dict(claims.get("attributes") or {}),
        session_id=(claims.get("attributes") or {}).get("sid"),
        jti=claims.get("jti"),
        correlation_id=_request_correlation_id(request),
        request_ip=_request_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return ctx


def _request_ip(request: Request) -> Optional[str]:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",", 1)[0].strip()
    return request.client.host if request.client else None


def _request_correlation_id(request: Request) -> str:
    cid = request.headers.get("x-correlation-id") or request.headers.get("x-request-id")
    cid = set_correlation_id(cid)
    request.state.correlation_id = cid
    return cid


def _enrich_anonymous(request: Request) -> ExecutionContext:
    return ExecutionContext(
        principal_id=ANONYMOUS.principal_id,
        correlation_id=_request_correlation_id(request),
        request_ip=_request_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


# ---- FastAPI dependencies ------------------------------------------------

async def current_context_dep(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    lv_access: Optional[str] = Cookie(default=None),
) -> ExecutionContext:
    """Build the ExecutionContext for the current request (may be anonymous)."""
    token = _extract_bearer(authorization, lv_access)
    ctx = await _build_context_from_token(request, token)
    token_ref = set_context(ctx)
    request.state.kernel_ctx_token = token_ref
    return ctx


async def require_auth(
    ctx: ExecutionContext = Depends(current_context_dep),
) -> ExecutionContext:
    if ctx.is_anonymous:
        raise unauthenticated()
    return ctx


def require_role(*roles: str):
    """Return a dependency that allows only principals having ANY of the given roles."""
    async def _dep(ctx: ExecutionContext = Depends(require_auth)) -> ExecutionContext:
        if not ctx.has_any_role(*roles):
            await audit("authz.deny", resource_type="role_gate",
                        decision="DENY", payload={"required": list(roles),
                                                  "actual": list(ctx.roles)})
            await increment("authz_denial", labels={"reason": "missing_role"})
            raise forbidden(f"requires one of roles: {list(roles)}",
                            code="auth.missing_role")
        return ctx

    return _dep


async def enforce(action: str, *, resource: Optional[dict] = None,
                  env: Optional[dict] = None) -> Decision:
    """Programmatic PDP check. Raises 403 on DENY, audits + metrics on both outcomes."""
    decision = authorize(action, resource=resource, env=env)
    await audit(
        action="authz." + ("permit" if decision.permitted else "deny"),
        resource_type=(resource or {}).get("resource_type", "unknown"),
        resource_id=(resource or {}).get("resource_id"),
        decision=decision.effect.value,
        payload={"action": action, "reason": decision.reason,
                 "policy_id": decision.policy_id},
    )
    if decision.permitted:
        await increment("authz_permit", labels={"action": action})
    else:
        await increment("authz_denial", labels={"action": action,
                                                "policy": decision.policy_id or "none"})
        raise forbidden(decision.reason, code="auth.policy_deny")
    return decision
