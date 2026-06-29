"""Evidence authorization policies (Phase 3.4 + 3.5).

Registered with the centralized PDP at startup. Authorization is
centralized — never look at JWT claims directly. The Application
Service additionally enforces Repository Defense-in-Depth by filtering
all queries on the ExecutionContext scope.
"""
from __future__ import annotations

from typing import Optional

from kernel.authorization.decisions import Decision
from kernel.authorization.policies import register_policy
from kernel.persistence.context import ExecutionContext

# Roles permitted to upload evidence (Phase 3.4 §3).
UPLOAD_ROLES = frozenset({
    "super_admin", "field_agent", "surveyor", "surveyor_general",
    "compliance_officer", "licensed_surveyor", "surveyor_partner",
})

# Roles permitted to read evidence metadata + issue signed URLs.
READ_PRIVILEGED_ROLES = frozenset({
    "super_admin", "surveyor_general", "compliance_officer",
    "government_observer",
})

# Roles permitted to create seals (Phase 3.5).
SEAL_CREATE_ROLES = frozenset({
    "super_admin", "surveyor_general", "compliance_officer",
    "licensed_surveyor",
})

# Roles permitted to flip the WORM switch.
SEAL_WORM_ROLES = frozenset({"super_admin", "compliance_officer"})

_EVIDENCE_REGISTERED = False


def _evidence_upload(ctx: ExecutionContext, action: str, resource: dict,
                     env: dict) -> Optional[Decision]:
    if action not in {"evidence.item.upload.initiate",
                      "evidence.item.upload.complete"}:
        return None
    if not ctx.is_authenticated:
        return Decision.deny(reason="authentication required",
                             policy_id="evidence.upload.anonymous")
    if set(ctx.roles) & UPLOAD_ROLES:
        return Decision.permit(reason="upload role",
                               policy_id="evidence.upload.role")
    return Decision.deny(reason="missing role for evidence upload",
                         policy_id="evidence.upload.role_required")


def _evidence_verify(ctx: ExecutionContext, action: str, resource: dict,
                     env: dict) -> Optional[Decision]:
    if action != "evidence.item.verify":
        return None
    if not ctx.is_authenticated:
        return Decision.deny(reason="authentication required",
                             policy_id="evidence.verify.anonymous")
    # Verify is callable post-upload by the uploader OR any governance
    # role (re-verification is a governance act).
    if (set(ctx.roles) & READ_PRIVILEGED_ROLES) or (set(ctx.roles) & UPLOAD_ROLES):
        return Decision.permit(reason="verify allowed",
                               policy_id="evidence.verify.role")
    return Decision.deny(reason="missing role for evidence verify",
                         policy_id="evidence.verify.role_required")


def _evidence_read(ctx: ExecutionContext, action: str, resource: dict,
                   env: dict) -> Optional[Decision]:
    if action not in {"evidence.item.read", "evidence.item.list",
                      "evidence.item.read.signed_url"}:
        return None
    if not ctx.is_authenticated:
        return Decision.deny(reason="authentication required",
                             policy_id="evidence.read.anonymous")
    if set(ctx.roles) & READ_PRIVILEGED_ROLES:
        return Decision.permit(reason="privileged read",
                               policy_id="evidence.read.privileged")
    if action == "evidence.item.list":
        return Decision.permit(reason="list scoped by execution context",
                               policy_id="evidence.list.scoped")
    if set(ctx.roles) & UPLOAD_ROLES:
        return Decision.permit(reason="operational role",
                               policy_id="evidence.read.operational")
    # Owner (creator) read is permitted.
    if resource and resource.get("created_by") == ctx.principal_id:
        return Decision.permit(reason="creator read",
                               policy_id="evidence.read.creator")
    return Decision.deny(reason="missing role for evidence read",
                         policy_id="evidence.read.role_required")


def _evidence_seal(ctx: ExecutionContext, action: str, resource: dict,
                   env: dict) -> Optional[Decision]:
    if action == "evidence.seal.create":
        if not ctx.is_authenticated:
            return Decision.deny(reason="authentication required",
                                 policy_id="evidence.seal.anonymous")
        if set(ctx.roles) & SEAL_CREATE_ROLES:
            return Decision.permit(reason="seal create role",
                                   policy_id="evidence.seal.create.role")
        return Decision.deny(reason="missing role for seal create",
                             policy_id="evidence.seal.create.role_required")
    if action == "evidence.seal.apply_worm":
        if not ctx.is_authenticated:
            return Decision.deny(reason="authentication required",
                                 policy_id="evidence.seal.worm.anonymous")
        if set(ctx.roles) & SEAL_WORM_ROLES:
            return Decision.permit(reason="seal worm role",
                                   policy_id="evidence.seal.worm.role")
        return Decision.deny(reason="missing role for apply_worm",
                             policy_id="evidence.seal.worm.role_required")
    if action == "evidence.seal.read":
        if not ctx.is_authenticated:
            return Decision.deny(reason="authentication required",
                                 policy_id="evidence.seal.read.anonymous")
        # Any authenticated principal in a recognised role may read a
        # seal (the application service projects fields per role).
        if (set(ctx.roles) & READ_PRIVILEGED_ROLES) or (set(ctx.roles) & UPLOAD_ROLES):
            return Decision.permit(reason="seal read allowed",
                                   policy_id="evidence.seal.read.role")
        return Decision.deny(reason="missing role for seal read",
                             policy_id="evidence.seal.read.role_required")
    return None


def register_evidence_policies() -> None:
    """Idempotent registration of Phase 3.4 + 3.5 policies."""
    global _EVIDENCE_REGISTERED
    if _EVIDENCE_REGISTERED:
        return
    register_policy("evidence.upload", 200,
                    "Evidence upload requires an UPLOAD_ROLES role",
                    _evidence_upload)
    register_policy("evidence.verify", 220,
                    "Verify allowed for uploaders + governance roles",
                    _evidence_verify)
    register_policy("evidence.read", 210,
                    "Evidence read: privileged role / operational role / creator",
                    _evidence_read)
    register_policy("evidence.seal", 230,
                    "Seal create + apply_worm + read policies",
                    _evidence_seal)
    _EVIDENCE_REGISTERED = True
