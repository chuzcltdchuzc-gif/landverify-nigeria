"""ExecutionContext — the single authoritative source of identity, country,
tenant, organization, roles, permissions, session, and security claims for
the current request (Architectural Clarification, Phase 1 sign-off).

Built from a verified access-token only — never from request body or query.
Propagated through every layer via `ContextVar`. Business domains consume but
never modify this context.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Optional

# ---- Anonymous principal constant ----------------------------------------
ANONYMOUS_PRINCIPAL = "anonymous"


@dataclass(frozen=True)
class Delegation:
    """A bounded, audited grant allowing one principal to act for another."""
    delegator_id: str
    expires_at: str
    scope: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExecutionContext:
    """Authenticated execution context. Immutable per request."""

    # Identity
    principal_id: str            # "anonymous" or user_id
    email: Optional[str] = None

    # Scope (first-class)
    country: Optional[str] = None
    tenant_id: Optional[str] = None
    organization_id: Optional[str] = None

    # Authorization material
    roles: tuple[str, ...] = field(default_factory=tuple)
    scopes: tuple[str, ...] = field(default_factory=tuple)
    attributes: dict[str, Any] = field(default_factory=dict)

    # Session / delegation
    session_id: Optional[str] = None
    jti: Optional[str] = None
    delegation: Optional[Delegation] = None

    # Request envelope
    correlation_id: Optional[str] = None
    request_ip: Optional[str] = None
    user_agent: Optional[str] = None

    # ---- Convenience -----------------------------------------------------
    @property
    def is_anonymous(self) -> bool:
        return self.principal_id == ANONYMOUS_PRINCIPAL

    @property
    def is_authenticated(self) -> bool:
        return not self.is_anonymous

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def has_any_role(self, *roles: str) -> bool:
        return any(r in self.roles for r in roles)


ANONYMOUS = ExecutionContext(principal_id=ANONYMOUS_PRINCIPAL)

_ctx: ContextVar[ExecutionContext] = ContextVar("kernel_execution_context", default=ANONYMOUS)


def current_context() -> ExecutionContext:
    return _ctx.get()


def set_context(ctx: ExecutionContext):
    """Set the context for the current async task. Returns the token to reset."""
    return _ctx.set(ctx)


def reset_context(token) -> None:
    _ctx.reset(token)
