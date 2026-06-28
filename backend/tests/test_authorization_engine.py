"""PDP / Policy engine unit tests — pure decision logic, no HTTP.

Verifies default-deny, anonymous restrictions, tenant + country isolation,
super-admin override, and self-action rules without booting FastAPI.
"""
from __future__ import annotations

from kernel.authorization.decisions import Effect
from kernel.authorization.pdp import authorize
from kernel.authorization.policies import register_default_policies
from kernel.persistence.context import ANONYMOUS, ExecutionContext

register_default_policies()


def _authed(*, tenant: str = "ten_a", country: str = "NG", roles=()) -> ExecutionContext:
    return ExecutionContext(
        principal_id="usr_1", email="u@example.com", country=country,
        tenant_id=tenant, roles=tuple(roles),
    )


def test_anonymous_default_deny_on_protected_action():
    d = authorize("identity.user.read", ctx=ANONYMOUS, resource={"user_id": "x"})
    assert d.effect == Effect.DENY
    assert "anonymous" in d.reason.lower()


def test_anonymous_permitted_on_whitelisted_public_actions():
    for action in ("identity.register", "identity.login", "identity.refresh",
                   "identity.jwks.read"):
        d = authorize(action, ctx=ANONYMOUS)
        assert d.effect == Effect.PERMIT, action


def test_authenticated_self_read():
    ctx = _authed(roles=["general_user"])
    d = authorize("identity.user.read", ctx=ctx, resource={"user_id": "usr_1"})
    assert d.effect == Effect.PERMIT
    d2 = authorize("identity.user.read", ctx=ctx, resource={"user_id": "usr_OTHER"})
    # Falls through to default-deny (no policy permits cross-user reads in Phase 1).
    assert d2.effect == Effect.DENY


def test_tenant_isolation_blocks_cross_tenant_access():
    ctx = _authed(tenant="ten_A", roles=["general_user"])
    d = authorize("some.action", ctx=ctx,
                  resource={"tenant_id": "ten_B"})
    assert d.effect == Effect.DENY
    assert "cross-tenant" in d.reason


def test_country_isolation_blocks_cross_country_access():
    ctx = _authed(country="NG", roles=["general_user"])
    d = authorize("some.action", ctx=ctx,
                  resource={"country": "KE"})
    assert d.effect == Effect.DENY
    assert "cross-country" in d.reason


def test_super_admin_bypasses_isolation():
    ctx = _authed(tenant="ten_A", country="NG",
                  roles=["PLATFORM_SUPER_ADMIN"])
    d = authorize("anything", ctx=ctx,
                  resource={"tenant_id": "ten_B", "country": "KE"})
    assert d.effect == Effect.PERMIT
    assert d.policy_id == "platform.super_admin"


def test_default_deny_when_no_policy_grants():
    ctx = _authed(tenant="ten_A", roles=["general_user"])
    d = authorize("custom.protected.action", ctx=ctx, resource={"tenant_id": "ten_A"})
    assert d.effect == Effect.DENY
    assert d.policy_id == "platform.default_deny"
