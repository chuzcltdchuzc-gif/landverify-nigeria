"""Phase 1A — comprehensive per-role Authorization Test Matrix.

Validates that the new ABAC engine faithfully reproduces the legacy Base44
RLS guarantees for all 10 canonical roles across CRUD + projection + tenant
isolation + country isolation + locked-state guard + role-status gate.

The matrix is exercised against an internal `demo` resource (no business
entity) so the authorization engine is verified independently.
"""
from __future__ import annotations

import pytest

from contexts.identity.domain.value_objects import (
    GOVERNANCE_ROLES,
    Role,
)
from kernel.authorization.decisions import Effect
from kernel.authorization.pdp import authorize
from kernel.authorization.policy_library import (
    register_demo_resource_policies,
)
from kernel.persistence.context import ExecutionContext


@pytest.fixture(scope="module", autouse=True)
def _register():
    # Idempotent — policies already registered at app startup.
    try:
        register_demo_resource_policies()
    except ValueError:
        pass


ALL_ROLES = [r.value for r in Role]


def _ctx(role: str, *, principal_id: str = "usr_principal", email: str = "p@example.com",
         tenant: str = "ten_A", country: str = "NG") -> ExecutionContext:
    return ExecutionContext(
        principal_id=principal_id, email=email, country=country, tenant_id=tenant,
        roles=(role,),
    )


def _demo(*, owner_id: str = "usr_other", status: str = "draft",
          tenant: str = "ten_A", country: str = "NG") -> dict:
    return {"resource_type": "demo", "resource_id": "dem_x",
            "owner_id": owner_id, "status": status,
            "tenant_id": tenant, "country": country}


# ---- CREATE -------------------------------------------------------------
@pytest.mark.parametrize("role", ALL_ROLES)
def test_create_demo_any_authenticated_role(role):
    """Anyone authenticated may CREATE on `demo`; obligation stamps the owner
    (except super_admin, which gets PERMIT via the bypass policy)."""
    d = authorize("demo.create", ctx=_ctx(role), resource={"resource_type": "demo"})
    assert d.effect == Effect.PERMIT, role
    if role != Role.SUPER_ADMIN.value:
        kinds = {ob.kind for ob in d.obligations}
        assert "stamp_owner" in kinds


# ---- READ ---------------------------------------------------------------
@pytest.mark.parametrize("role", [Role.SUPER_ADMIN.value,
                                   Role.SURVEYOR_GENERAL.value,
                                   Role.COMPLIANCE_OFFICER.value])
def test_governance_roles_can_read_anyones_demo(role):
    d = authorize("demo.read", ctx=_ctx(role),
                  resource=_demo(owner_id="usr_someone_else"))
    assert d.effect == Effect.PERMIT, role


def test_owner_can_read_own_demo():
    d = authorize("demo.read", ctx=_ctx(Role.GENERAL_USER.value,
                                        principal_id="usr_owner"),
                  resource=_demo(owner_id="usr_owner"))
    assert d.effect == Effect.PERMIT


def test_non_owner_non_privileged_cannot_read_demo():
    for role in (Role.GENERAL_USER.value, Role.FIELD_AGENT.value,
                 Role.SURVEYOR.value, Role.LICENSED_SURVEYOR.value,
                 Role.SURVEYOR_PARTNER.value, Role.COMMUNITY_VALIDATOR.value,
                 Role.GOVERNMENT_OBSERVER.value):
        d = authorize("demo.read", ctx=_ctx(role, principal_id="usr_outsider"),
                      resource=_demo(owner_id="usr_someone_else"))
        assert d.effect == Effect.DENY, role


# ---- UPDATE / locked-state guard --------------------------------------
def test_owner_cannot_update_locked_demo():
    d = authorize("demo.update", ctx=_ctx(Role.GENERAL_USER.value,
                                          principal_id="usr_owner"),
                  resource=_demo(owner_id="usr_owner", status="certificate_issued"))
    assert d.effect == Effect.DENY
    assert "locked" in d.reason


@pytest.mark.parametrize("status", ["approved_locked", "certificate_issued",
                                     "evidence_sealed", "audit_finalised"])
def test_super_admin_can_update_locked_demo(status):
    d = authorize("demo.update", ctx=_ctx(Role.SUPER_ADMIN.value),
                  resource=_demo(status=status))
    assert d.effect == Effect.PERMIT


# ---- Role-conditional-on-status -------------------------------------
@pytest.mark.parametrize("status,expect", [
    ("assigned", Effect.PERMIT),
    ("in_progress", Effect.PERMIT),
    ("approved_locked", Effect.DENY),
    ("draft", Effect.DENY),
])
def test_surveyor_update_status_gate(status, expect):
    d = authorize("demo.update", ctx=_ctx(Role.SURVEYOR.value),
                  resource=_demo(status=status))
    assert d.effect == expect, status


def test_community_validator_only_while_pending():
    permitted = authorize("demo.update", ctx=_ctx(Role.COMMUNITY_VALIDATOR.value),
                          resource=_demo(status="validation_pending"))
    assert permitted.effect == Effect.PERMIT
    denied = authorize("demo.update", ctx=_ctx(Role.COMMUNITY_VALIDATOR.value),
                       resource=_demo(status="finalised"))
    assert denied.effect == Effect.DENY


# ---- DELETE: super_admin only ---------------------------------------
@pytest.mark.parametrize("role", ALL_ROLES)
def test_delete_demo_is_super_admin_only(role):
    d = authorize("demo.delete", ctx=_ctx(role), resource=_demo())
    if role == Role.SUPER_ADMIN.value:
        assert d.effect == Effect.PERMIT, role
    else:
        assert d.effect == Effect.DENY, role


# ---- Tenant isolation (applies to ANY action) -----------------------
def test_tenant_isolation_overrides_owner_read():
    # Owner in tenant A trying to read THEIR record from tenant B → DENY.
    d = authorize("demo.read",
                  ctx=_ctx(Role.GENERAL_USER.value, principal_id="usr_owner",
                           tenant="ten_A"),
                  resource={**_demo(owner_id="usr_owner"), "tenant_id": "ten_B"})
    assert d.effect == Effect.DENY
    assert "cross-tenant" in d.reason


def test_country_isolation_blocks_governance_read_across_countries():
    d = authorize("demo.read",
                  ctx=_ctx(Role.COMPLIANCE_OFFICER.value, country="NG"),
                  resource={**_demo(), "country": "KE"})
    assert d.effect == Effect.DENY


def test_super_admin_bypasses_country_and_tenant():
    d = authorize("demo.read",
                  ctx=_ctx(Role.SUPER_ADMIN.value, tenant="ten_A", country="NG"),
                  resource={**_demo(), "tenant_id": "ten_B", "country": "KE"})
    assert d.effect == Effect.PERMIT


# ---- Field projection obligation -----------------------------------
def test_owner_read_returns_no_projection_obligation_for_privileged():
    d = authorize("demo.read", ctx=_ctx(Role.SUPER_ADMIN.value),
                  resource=_demo(owner_id="usr_someone_else"))
    assert d.effect == Effect.PERMIT
    assert all(ob.kind != "project_fields" for ob in d.obligations)
