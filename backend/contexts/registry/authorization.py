"""Registry authorization policies (Phase 2A §9).

These policies are registered with the centralized PDP at startup.
Authorization is centralized — never look at JWT claims directly.
The Application Service additionally enforces Repository Defense-in-Depth
by filtering all queries on the ExecutionContext scope.
"""
from __future__ import annotations

from typing import Optional

from kernel.authorization.decisions import Decision
from kernel.authorization.policies import register_policy
from kernel.persistence.context import ExecutionContext

# Roles that may CREATE land vaults (Phase 2 §3.3).
CREATE_ROLES = frozenset({
    "super_admin", "field_agent", "surveyor", "surveyor_general",
    "compliance_officer", "licensed_surveyor", "surveyor_partner",
})

# Roles that may freely READ any land vault (governance + observer).
READ_PRIVILEGED_ROLES = frozenset({
    "super_admin", "surveyor_general", "compliance_officer",
    "government_observer",
})

# Roles that may update SURVEY fields.
SURVEY_UPDATE_ROLES = frozenset({
    "super_admin", "surveyor_general", "surveyor", "licensed_surveyor",
    "surveyor_partner", "field_agent",
})

# Roles that may update COMMUNITY fields.
COMMUNITY_UPDATE_ROLES = frozenset({
    "super_admin", "surveyor_general", "compliance_officer",
    "community_validator",
})

ARCHIVE_ROLES = frozenset({"super_admin"})

_REGISTRY_REGISTERED = False


def _is_creator_or_field_agent(ctx: ExecutionContext, resource: dict) -> bool:
    """The Application Service stamps `created_by`, `owner_email`,
    `field_agent_email` on the resource when it calls the PEP for an
    *instance-scoped* action. For action-only checks (`create`, `list`)
    the resource dict is empty — those policies allow on role alone."""
    if not resource:
        return False
    if resource.get("created_by") and resource.get("created_by") == ctx.principal_id:
        return True
    if (ctx.email and
            resource.get("owner_email", "").lower() == ctx.email.lower()):
        return True
    if (ctx.email and
            resource.get("field_agent_email", "").lower() == ctx.email.lower()):
        return True
    return False


def _registry_create(ctx: ExecutionContext, action: str, resource: dict,
                     env: dict) -> Optional[Decision]:
    if action != "registry.landvault.create":
        return None
    if not ctx.is_authenticated:
        return Decision.deny(reason="authentication required",
                             policy_id="registry.create.anonymous")
    if set(ctx.roles) & CREATE_ROLES:
        return Decision.permit(reason="role permits create",
                               policy_id="registry.create.role")
    return Decision.deny(reason="missing role for registry.create",
                         policy_id="registry.create.role_required")


def _registry_read(ctx: ExecutionContext, action: str, resource: dict,
                   env: dict) -> Optional[Decision]:
    if action not in {"registry.landvault.read", "registry.landvault.list"}:
        return None
    if not ctx.is_authenticated:
        return Decision.deny(reason="authentication required",
                             policy_id="registry.read.anonymous")
    if set(ctx.roles) & READ_PRIVILEGED_ROLES:
        return Decision.permit(reason="privileged read",
                               policy_id="registry.read.privileged")
    # Listing is always allowed — the Application Service scopes results.
    if action == "registry.landvault.list":
        return Decision.permit(reason="list scoped by execution context",
                               policy_id="registry.list.scoped")
    # Instance read: defer to ownership check OR allow at API layer; the
    # query service applies field projection so we PERMIT and project.
    return Decision.permit(reason="authenticated read with projection",
                           policy_id="registry.read.projected")


def _registry_update_owner_or_role(ctx: ExecutionContext, action: str,
                                   resource: dict, env: dict) -> Optional[Decision]:
    """Update policy.

    The PDP cannot reliably load resource ownership without a pre-fetch,
    so this policy authorizes by ROLE; the aggregate enforces the
    locked-state and owner-only invariants (defense in depth).

    Anyone with:
      * a privileged role (super_admin, governance), OR
      * a CREATE_ROLE (field_agent, surveyor, etc.) — i.e. someone who
        could have created the record in the first place

    is permitted. The aggregate's `_ensure_writable()` then enforces the
    locked-status guard, and the application service projects responses
    so unauthorized callers cannot exfiltrate data.
    """
    if not action.startswith("registry.landvault.update."):
        return None
    if not ctx.is_authenticated:
        return Decision.deny(reason="authentication required",
                             policy_id="registry.update.anonymous")
    if set(ctx.roles) & READ_PRIVILEGED_ROLES:
        return Decision.permit(reason="privileged role",
                               policy_id="registry.update.privileged")
    if action == "registry.landvault.update.survey":
        if set(ctx.roles) & SURVEY_UPDATE_ROLES:
            return Decision.permit(reason="survey role",
                                   policy_id="registry.update.survey.role")
    if action == "registry.landvault.update.community_data":
        if set(ctx.roles) & COMMUNITY_UPDATE_ROLES:
            return Decision.permit(reason="community role",
                                   policy_id="registry.update.community.role")
    # Generic owner-side update facets: location, geometry, ownership_contact.
    # Permit any actor with a CREATE_ROLES role; the aggregate enforces
    # locked-state and the repository enforces tenant scoping.
    if set(ctx.roles) & CREATE_ROLES:
        return Decision.permit(reason="operational role",
                               policy_id="registry.update.operational_role")
    if _is_creator_or_field_agent(ctx, resource):
        return Decision.permit(reason="owner or assigned",
                               policy_id="registry.update.owner")
    return None


def _registry_ownership_transfer(ctx: ExecutionContext, action: str,
                                 resource: dict, env: dict) -> Optional[Decision]:
    if action != "registry.landvault.ownership.transfer":
        return None
    if not ctx.is_authenticated:
        return Decision.deny(reason="authentication required",
                             policy_id="registry.transfer.anonymous")
    # Legal ownership transfers require a governance role OR the registered
    # owner themselves (in which case the aggregate still enforces locked
    # statuses).
    if set(ctx.roles) & READ_PRIVILEGED_ROLES:
        return Decision.permit(reason="governance transfer",
                               policy_id="registry.transfer.governance")
    if _is_creator_or_field_agent(ctx, resource):
        return Decision.permit(reason="owner-initiated transfer",
                               policy_id="registry.transfer.owner")
    return Decision.deny(reason="ownership transfer requires governance role",
                         policy_id="registry.transfer.role_required")


def _registry_archive(ctx: ExecutionContext, action: str, resource: dict,
                      env: dict) -> Optional[Decision]:
    if action != "registry.landvault.archive":
        return None
    if not ctx.is_authenticated:
        return Decision.deny(reason="authentication required",
                             policy_id="registry.archive.anonymous")
    if set(ctx.roles) & ARCHIVE_ROLES:
        return Decision.permit(reason="super_admin archive",
                               policy_id="registry.archive.super_admin")
    return Decision.deny(reason="archive requires super_admin",
                         policy_id="registry.archive.role_required")


def register_registry_policies() -> None:
    """Idempotent registration of registry policies."""
    global _REGISTRY_REGISTERED
    if _REGISTRY_REGISTERED:
        return
    register_policy("registry.create", 100,
                    "Registry create requires a CREATE_ROLES role",
                    _registry_create)
    register_policy("registry.read", 110,
                    "Registry read: privileged role OR scoped projection",
                    _registry_read)
    register_policy("registry.update", 120,
                    "Registry update: privileged role / owner / per-facet role",
                    _registry_update_owner_or_role)
    register_policy("registry.ownership_transfer", 121,
                    "Legal ownership transfer: governance role or owner",
                    _registry_ownership_transfer)
    register_policy("registry.archive", 130,
                    "Registry archive: super_admin only",
                    _registry_archive)
    _REGISTRY_REGISTERED = True
