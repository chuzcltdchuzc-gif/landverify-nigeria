"""Reusable ABAC Policy Library — ports the canonical legacy RLS patterns
(Foundation Spec §5; Phase 1 Definitive Spec §5).

These are **policy factories**: call them at startup to register concrete
policies into the PDP (via `register_policy`). Resource descriptors passed to
`authorize()` may include any of:

    {
        "resource_type": "demo" | future business types,
        "resource_id": "...",
        "owner_id": principal_id of the resource's creator,
        "owner_email": email-shaped owner identifier (legacy parity),
        "assigned_to": principal who is the active actor (e.g. field_agent_email),
        "tenant_id", "country", "organization_id",
        "status": current lifecycle status (locked states matter — see locked_state_guard),
        "classification": "Operational" | "Legal" | "Evidence" | "Audit",
    }

Each policy returns `Decision | None` per the existing PDP contract.
"""
from __future__ import annotations

from typing import Iterable, Optional

from contexts.identity.domain.value_objects import (
    GOVERNANCE_ROLES,
    Role,
)
from kernel.authorization.decisions import Decision, Obligation
from kernel.authorization.policies import register_policy
from kernel.persistence.context import ExecutionContext

# ---- States that prohibit owner-side mutation (legacy "locked" states) ---
LOCKED_STATES: frozenset[str] = frozenset({
    "approved_locked", "certificate_issued", "evidence_sealed", "audit_finalised",
})


def _principal_owns(ctx: ExecutionContext, resource: dict) -> bool:
    owner_id = resource.get("owner_id") or resource.get("created_by")
    if owner_id and ctx.principal_id == owner_id:
        return True
    owner_email = resource.get("owner_email")
    if owner_email and ctx.email and ctx.email.lower() == owner_email.lower():
        return True
    assigned = resource.get("assigned_to") or resource.get("assigned_email")
    if assigned and ctx.email and ctx.email.lower() == str(assigned).lower():
        return True
    return False


def _has_any(ctx: ExecutionContext, roles: Iterable[str]) -> bool:
    return bool(set(ctx.roles) & set(roles))


# ---- Policy factories ---------------------------------------------------

def owner_or_privileged_read_policy(
    *, action: str, resource_type: str, privileged_roles: Iterable[str],
    projection_fields: Optional[list[str]] = None,
) -> str:
    """Legacy READ pattern: owner / creator / assigned actor / privileged role.

    Returns the policy id. Registers a policy that grants READ on the given
    `action` for the given `resource_type`, with optional field-projection
    obligation when the caller is not privileged.
    """
    policy_id = f"abac.{resource_type}.read"
    privileged = frozenset(privileged_roles)

    def _fn(ctx: ExecutionContext, act: str, resource: dict, env: dict) -> Optional[Decision]:
        if act != action:
            return None
        if (resource.get("resource_type") or resource_type) != resource_type:
            return None
        if not ctx.is_authenticated:
            return None
        if _has_any(ctx, privileged):
            return Decision.permit(reason="privileged read", policy_id=policy_id)
        if _principal_owns(ctx, resource):
            obligations: tuple[Obligation, ...] = ()
            if projection_fields:
                obligations = (Obligation(kind="project_fields",
                                          args={"fields": list(projection_fields)}),)
            return Decision.permit(reason="owner/assigned read",
                                   policy_id=policy_id, obligations=list(obligations))
        return None

    register_policy(policy_id, 100, f"READ {resource_type} (owner-or-privileged)", _fn)
    return policy_id


def locked_state_guard_policy(*, action: str, resource_type: str,
                              privileged_roles: Iterable[str]) -> str:
    """Legacy UPDATE pattern: owners cannot mutate locked records; privileged can.

    Denies updates by the owner if the resource is in a LOCKED_STATES status.
    """
    policy_id = f"abac.{resource_type}.update.locked_guard"
    privileged = frozenset(privileged_roles)

    def _fn(ctx: ExecutionContext, act: str, resource: dict, env: dict) -> Optional[Decision]:
        if act != action:
            return None
        if (resource.get("resource_type") or resource_type) != resource_type:
            return None
        status = (resource.get("status") or "").lower()
        if status in LOCKED_STATES and _principal_owns(ctx, resource) and not _has_any(ctx, privileged):
            return Decision.deny(reason=f"locked state {status!r}",
                                 policy_id=policy_id)
        return None

    register_policy(policy_id, 50, f"UPDATE {resource_type} (locked-state guard)", _fn)
    return policy_id


def role_conditional_on_status_policy(*, action: str, resource_type: str,
                                      role: str, allowed_statuses: Iterable[str]) -> str:
    """A specific role may act ONLY while the resource is in one of the allowed statuses.

    Example: surveyor may update while status in {assigned, in_progress}; community_validator
    may update while validation_status == pending.
    """
    policy_id = f"abac.{resource_type}.{role}.status_gate"
    allowed = frozenset(s.lower() for s in allowed_statuses)

    def _fn(ctx: ExecutionContext, act: str, resource: dict, env: dict) -> Optional[Decision]:
        if act != action:
            return None
        if (resource.get("resource_type") or resource_type) != resource_type:
            return None
        if role not in ctx.roles:
            return None
        status = (resource.get("status") or "").lower()
        if status in allowed:
            return Decision.permit(reason=f"{role} permitted at status {status}",
                                   policy_id=policy_id)
        return Decision.deny(reason=f"{role} not allowed at status {status!r}",
                             policy_id=policy_id)

    register_policy(policy_id, 80, f"{role} ↔ status gate for {resource_type}", _fn)
    return policy_id


def delete_super_admin_only_policy(*, action: str, resource_type: str) -> str:
    """Legacy DELETE: super_admin only; prefer soft delete; always audited
    (auditing is handled by `enforce()` in the PEP)."""
    policy_id = f"abac.{resource_type}.delete.super_admin_only"

    def _fn(ctx: ExecutionContext, act: str, resource: dict, env: dict) -> Optional[Decision]:
        if act != action:
            return None
        if (resource.get("resource_type") or resource_type) != resource_type:
            return None
        if Role.SUPER_ADMIN.value in ctx.roles:
            return Decision.permit(reason="super_admin delete", policy_id=policy_id)
        return Decision.deny(reason="delete reserved for super_admin",
                             policy_id=policy_id)

    register_policy(policy_id, 60, f"DELETE {resource_type} (super_admin only)", _fn)
    return policy_id


def create_owner_stamp_policy(*, action: str, resource_type: str,
                              creator_roles: Optional[Iterable[str]] = None) -> str:
    """Legacy CREATE: caller becomes owner; record stamped created_by=principal.

    Optionally restricts who may create. Returns PERMIT with a
    `stamp_owner` obligation telling the application to record created_by =
    ctx.principal_id.
    """
    policy_id = f"abac.{resource_type}.create"
    restricted_to = frozenset(creator_roles) if creator_roles else None

    def _fn(ctx: ExecutionContext, act: str, resource: dict, env: dict) -> Optional[Decision]:
        if act != action:
            return None
        if (resource.get("resource_type") or resource_type) != resource_type:
            return None
        if not ctx.is_authenticated:
            return None
        if restricted_to is not None and not _has_any(ctx, restricted_to):
            return Decision.deny(reason="role not permitted to create",
                                 policy_id=policy_id)
        return Decision.permit(
            reason="create permitted; owner stamped",
            policy_id=policy_id,
            obligations=[Obligation(kind="stamp_owner",
                                    args={"principal_id": ctx.principal_id})],
        )

    register_policy(policy_id, 90, f"CREATE {resource_type}", _fn)
    return policy_id


def register_demo_resource_policies() -> None:
    """Register a canonical RLS-equivalent policy set on the internal `demo`
    resource. The Phase 1 authorization test matrix exercises these policies.

    The `demo` resource has no business meaning — it exists solely so the
    Authorization Engine can be verified independently of any business domain.
    """
    create_owner_stamp_policy(action="demo.create", resource_type="demo")
    owner_or_privileged_read_policy(action="demo.read", resource_type="demo",
                                    privileged_roles=GOVERNANCE_ROLES)
    locked_state_guard_policy(action="demo.update", resource_type="demo",
                              privileged_roles=GOVERNANCE_ROLES)
    role_conditional_on_status_policy(
        action="demo.update", resource_type="demo",
        role=Role.SURVEYOR.value,
        allowed_statuses=["assigned", "in_progress"],
    )
    role_conditional_on_status_policy(
        action="demo.update", resource_type="demo",
        role=Role.COMMUNITY_VALIDATOR.value,
        allowed_statuses=["validation_pending"],
    )
    delete_super_admin_only_policy(action="demo.delete", resource_type="demo")
