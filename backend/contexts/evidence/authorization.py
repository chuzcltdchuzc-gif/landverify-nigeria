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


def _evidence_anchor(ctx: ExecutionContext, action: str, resource: dict,
                       env: dict) -> Optional[Decision]:
    if action == "evidence.anchor.batch.read":
        if not ctx.is_authenticated:
            return Decision.deny(reason="authentication required",
                                  policy_id="evidence.anchor.read.anonymous")
        if (set(ctx.roles) & READ_PRIVILEGED_ROLES) or (set(ctx.roles) & UPLOAD_ROLES):
            return Decision.permit(reason="anchor read allowed",
                                    policy_id="evidence.anchor.read.role")
        return Decision.deny(reason="missing role for anchor read",
                              policy_id="evidence.anchor.read.role_required")
    if action == "evidence.anchor.batch.replay_dlq":
        if not ctx.is_authenticated:
            return Decision.deny(reason="authentication required",
                                  policy_id="evidence.anchor.replay.anonymous")
        if "super_admin" in ctx.roles:
            return Decision.permit(reason="super_admin",
                                    policy_id="evidence.anchor.replay.super_admin")
        return Decision.deny(reason="super_admin only",
                              policy_id="evidence.anchor.replay.role_required")
    return None


def _evidence_lock(ctx: ExecutionContext, action: str, resource: dict,
                    env: dict) -> Optional[Decision]:
    if action == "evidence.lock.read":
        if not ctx.is_authenticated:
            return Decision.deny(reason="authentication required",
                                  policy_id="evidence.lock.read.anonymous")
        if (set(ctx.roles) & READ_PRIVILEGED_ROLES) or (set(ctx.roles) & UPLOAD_ROLES):
            return Decision.permit(reason="lock read",
                                    policy_id="evidence.lock.read.role")
        return Decision.deny(reason="missing role",
                              policy_id="evidence.lock.read.role_required")
    if action == "evidence.lock.extend":
        if not ctx.is_authenticated:
            return Decision.deny(reason="authentication required",
                                  policy_id="evidence.lock.extend.anonymous")
        if (set(ctx.roles) & {"super_admin", "compliance_officer"}):
            return Decision.permit(reason="lock extend allowed",
                                    policy_id="evidence.lock.extend.role")
        return Decision.deny(reason="super_admin or compliance_officer required",
                              policy_id="evidence.lock.extend.role_required")
    return None


def _evidence_integrity(ctx: ExecutionContext, action: str, resource: dict,
                          env: dict) -> Optional[Decision]:
    if action == "evidence.integrity.trigger":
        if not ctx.is_authenticated:
            return Decision.deny(reason="authentication required",
                                  policy_id="evidence.integrity.trigger.anonymous")
        if (set(ctx.roles) & {"super_admin", "compliance_officer",
                                "government_observer"}):
            return Decision.permit(reason="integrity trigger allowed",
                                    policy_id="evidence.integrity.trigger.role")
        return Decision.deny(reason="missing role",
                              policy_id="evidence.integrity.trigger.role_required")
    if action == "evidence.integrity.read":
        if not ctx.is_authenticated:
            return Decision.deny(reason="authentication required",
                                  policy_id="evidence.integrity.read.anonymous")
        if (set(ctx.roles) & READ_PRIVILEGED_ROLES) or (set(ctx.roles) & UPLOAD_ROLES):
            return Decision.permit(reason="integrity read",
                                    policy_id="evidence.integrity.read.role")
        return Decision.deny(reason="missing role",
                              policy_id="evidence.integrity.read.role_required")
    if action == "evidence.ctlog.checkpoint.read":
        if not ctx.is_authenticated:
            return Decision.deny(reason="authentication required",
                                  policy_id="evidence.ctlog.read.anonymous")
        return Decision.permit(reason="ctlog checkpoint readable to authenticated",
                                policy_id="evidence.ctlog.read.authenticated")
    return None


def _evidence_timeline(ctx: ExecutionContext, action: str, resource: dict,
                         env: dict) -> Optional[Decision]:
    if action not in {"evidence.timeline.read", "evidence.custody.read",
                      "evidence.custody.record",
                      "evidence.legal_hold.read",
                      "evidence.legal_hold.apply",
                      "evidence.legal_hold.release"}:
        return None
    if not ctx.is_authenticated:
        return Decision.deny(reason="authentication required",
                              policy_id=f"{action}.anonymous")
    if action in {"evidence.timeline.read", "evidence.custody.read",
                   "evidence.legal_hold.read"}:
        if (set(ctx.roles) & READ_PRIVILEGED_ROLES) or (set(ctx.roles) & UPLOAD_ROLES):
            return Decision.permit(reason="role permitted",
                                    policy_id=f"{action}.role")
        return Decision.deny(reason="missing role",
                              policy_id=f"{action}.role_required")
    if action == "evidence.custody.record":
        if set(ctx.roles) & UPLOAD_ROLES or set(ctx.roles) & READ_PRIVILEGED_ROLES:
            return Decision.permit(reason="role permitted",
                                    policy_id=f"{action}.role")
        return Decision.deny(reason="missing role",
                              policy_id=f"{action}.role_required")
    # Legal hold apply / release: super_admin + compliance_officer only.
    if set(ctx.roles) & {"super_admin", "compliance_officer"}:
        return Decision.permit(reason="hold actor",
                                policy_id=f"{action}.role")
    return Decision.deny(reason="super_admin or compliance_officer required",
                          policy_id=f"{action}.role_required")


def register_evidence_policies() -> None:
    """Idempotent registration of Phase 3.4 + 3.5 + 3.6 + 3.7 policies."""
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
    register_policy("evidence.anchor", 250,
                    "Anchor batch read + DLQ replay policies",
                    _evidence_anchor)
    register_policy("evidence.lock", 260,
                    "Lock read + forward-only extend policies",
                    _evidence_lock)
    register_policy("evidence.integrity", 270,
                    "Integrity check trigger + read + CT-log checkpoint read",
                    _evidence_integrity)
    register_policy("evidence.timeline", 280,
                    "Phase 3.7 timeline + custody + legal hold policies",
                    _evidence_timeline)
    _EVIDENCE_REGISTERED = True
