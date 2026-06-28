"""Policy registry (Policy Administration Point — PAP).

For Phase 1 policies are in-code and registered at startup. The Administration
domain will later expose a configuration surface that pushes policies into
this registry, but the *evaluation model* will not change (ADR-002).

Each policy is a pure function `(ExecutionContext, action, resource, env) ->
Decision | None`. Returning `None` means "this policy doesn't apply — defer
to the next policy". The PDP evaluates policies in priority order; the first
explicit PERMIT or DENY wins. If no policy returns a decision, the PDP
default-denies (ADR-002, fail closed).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from kernel.authorization.decisions import Decision
from kernel.persistence.context import ExecutionContext

logger = logging.getLogger("kernel.authorization.policies")

PolicyFn = Callable[[ExecutionContext, str, dict, dict], Optional[Decision]]


@dataclass(frozen=True)
class Policy:
    id: str
    priority: int           # lower = evaluated earlier
    description: str
    fn: PolicyFn


_policies: list[Policy] = []


def register_policy(policy_id: str, priority: int, description: str, fn: PolicyFn) -> None:
    """Append a policy. Re-registration of an id is a configuration error."""
    if any(p.id == policy_id for p in _policies):
        raise ValueError(f"policy {policy_id!r} already registered")
    _policies.append(Policy(id=policy_id, priority=priority, description=description, fn=fn))
    _policies.sort(key=lambda p: p.priority)
    logger.debug("registered policy %s priority=%d", policy_id, priority)


def all_policies() -> list[Policy]:
    return list(_policies)


# ---- Phase 1 built-in policies ------------------------------------------
# These are wired by `register_default_policies()`. The Identity context calls
# this on startup. Business contexts will add their own policies later.

def _super_admin_allows_everything(ctx: ExecutionContext, action: str, resource: dict,
                                   env: dict) -> Optional[Decision]:
    # Canonical role per Phase 1A spec is `super_admin`. Legacy
    # `PLATFORM_SUPER_ADMIN` is kept as a compatibility alias for transition.
    if ctx.has_any_role("super_admin", "PLATFORM_SUPER_ADMIN"):
        return Decision.permit(reason="super admin", policy_id="platform.super_admin")
    return None


def _anonymous_can_only_access_public_actions(ctx: ExecutionContext, action: str, resource: dict,
                                              env: dict) -> Optional[Decision]:
    """Anonymous callers may only perform actions explicitly marked
    `identity.register`, `identity.login`, `identity.refresh`, or `platform.public.*`.
    """
    if ctx.is_authenticated:
        return None
    if action.startswith("platform.public.") or action in {
        "identity.register",
        "identity.login",
        "identity.refresh",
        "identity.jwks.read",
    }:
        return Decision.permit(reason="anonymous public action",
                               policy_id="platform.anonymous_public")
    return Decision.deny(reason="anonymous principal not allowed",
                         policy_id="platform.anonymous_default_deny")


def _self_actions(ctx: ExecutionContext, action: str, resource: dict,
                  env: dict) -> Optional[Decision]:
    """Any authenticated principal may operate on their own user record."""
    if not ctx.is_authenticated:
        return None
    if action in {"identity.self.read", "identity.self.logout"}:
        return Decision.permit(reason="self action", policy_id="identity.self")
    if action == "identity.user.read":
        if resource.get("user_id") == ctx.principal_id:
            return Decision.permit(reason="reading self", policy_id="identity.self.read")
    return None


def _tenant_isolation(ctx: ExecutionContext, action: str, resource: dict,
                      env: dict) -> Optional[Decision]:
    """Hard deny when an authenticated request targets another tenant explicitly."""
    if not ctx.is_authenticated:
        return None
    target_tenant = resource.get("tenant_id")
    if target_tenant and ctx.tenant_id and target_tenant != ctx.tenant_id:
        if not ctx.has_any_role("super_admin", "PLATFORM_SUPER_ADMIN"):
            return Decision.deny(reason="cross-tenant access denied",
                                 policy_id="platform.tenant_isolation")
    return None


def _country_isolation(ctx: ExecutionContext, action: str, resource: dict,
                       env: dict) -> Optional[Decision]:
    if not ctx.is_authenticated:
        return None
    target_country = resource.get("country")
    if target_country and ctx.country and target_country != ctx.country:
        if not ctx.has_any_role("super_admin", "PLATFORM_SUPER_ADMIN"):
            return Decision.deny(reason="cross-country access denied",
                                 policy_id="platform.country_isolation")
    return None


_DEFAULTS_REGISTERED = False


def register_default_policies() -> None:
    """Idempotent registration of Phase 1 platform policies."""
    global _DEFAULTS_REGISTERED
    if _DEFAULTS_REGISTERED:
        return
    register_policy("platform.tenant_isolation", 10,
                    "Deny cross-tenant access unless PLATFORM_SUPER_ADMIN",
                    _tenant_isolation)
    register_policy("platform.country_isolation", 11,
                    "Deny cross-country access unless PLATFORM_SUPER_ADMIN",
                    _country_isolation)
    register_policy("platform.super_admin", 20,
                    "PLATFORM_SUPER_ADMIN can do anything within their scope",
                    _super_admin_allows_everything)
    register_policy("platform.anonymous_public", 30,
                    "Anonymous principals are limited to whitelisted public actions",
                    _anonymous_can_only_access_public_actions)
    register_policy("identity.self", 40,
                    "Any authenticated principal may operate on their own record",
                    _self_actions)
    _DEFAULTS_REGISTERED = True
