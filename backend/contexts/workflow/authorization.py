"""Workflow authorization policies (Phase 4 — Slice 4.0).

Registered with the centralized PDP at startup. Authorization is
centralized — never look at JWT claims directly inside the engine.
"""
from __future__ import annotations

from typing import Optional

from kernel.authorization.decisions import Decision
from kernel.authorization.policies import register_policy
from kernel.persistence.context import ExecutionContext

# Roles permitted to start a workflow instance.
START_ROLES = frozenset({
    "super_admin", "compliance_officer", "surveyor_general",
})

# Roles permitted to read workflow data.
READ_ROLES = frozenset({
    "super_admin", "surveyor_general", "compliance_officer",
    "government_observer", "field_agent", "surveyor",
    "licensed_surveyor", "surveyor_partner", "community_validator",
})

# Roles permitted to operate workflow admin endpoints (replay,
# fire_timer, suspend/reactivate).
ADMIN_ROLES = frozenset({"super_admin"})

# Roles permitted to claim / complete tasks (broad operational set).
TASK_ROLES = frozenset({
    "super_admin", "field_agent", "surveyor", "surveyor_general",
    "compliance_officer", "licensed_surveyor", "surveyor_partner",
    "community_validator",
})

_WORKFLOW_REGISTERED = False


def _workflow_instance(ctx: ExecutionContext, action: str, resource: dict,
                         env: dict) -> Optional[Decision]:
    if not action.startswith("workflow.instance."):
        return None
    if not ctx.is_authenticated:
        return Decision.deny(reason="authentication required",
                              policy_id=f"{action}.anonymous")
    sub = action.split(".", 2)[2]  # start | cancel | suspend | reactivate | read | list
    if sub == "start":
        if set(ctx.roles) & START_ROLES:
            return Decision.permit(reason="start role",
                                    policy_id="workflow.instance.start.role")
        return Decision.deny(reason="missing role for workflow start",
                              policy_id="workflow.instance.start.role_required")
    if sub == "cancel":
        if set(ctx.roles) & (START_ROLES | ADMIN_ROLES):
            return Decision.permit(reason="cancel role",
                                    policy_id="workflow.instance.cancel.role")
        return Decision.deny(reason="missing role for workflow cancel",
                              policy_id="workflow.instance.cancel.role_required")
    if sub in {"suspend", "reactivate"}:
        if set(ctx.roles) & ADMIN_ROLES:
            return Decision.permit(reason="admin role",
                                    policy_id=f"workflow.instance.{sub}.role")
        return Decision.deny(reason="super_admin required",
                              policy_id=f"workflow.instance.{sub}.role_required")
    if sub in {"read", "list"}:
        if set(ctx.roles) & READ_ROLES:
            return Decision.permit(reason="read role",
                                    policy_id=f"workflow.instance.{sub}.role")
        return Decision.deny(reason="missing role for workflow read",
                              policy_id=f"workflow.instance.{sub}.role_required")
    return None


def _workflow_task(ctx: ExecutionContext, action: str, resource: dict,
                     env: dict) -> Optional[Decision]:
    if not action.startswith("workflow.task."):
        return None
    if not ctx.is_authenticated:
        return Decision.deny(reason="authentication required",
                              policy_id=f"{action}.anonymous")
    sub = action.split(".", 2)[2]
    if sub in {"claim", "complete"}:
        if set(ctx.roles) & TASK_ROLES:
            return Decision.permit(reason="task role",
                                    policy_id=f"workflow.task.{sub}.role")
        return Decision.deny(reason="missing role for task action",
                              policy_id=f"workflow.task.{sub}.role_required")
    if sub in {"read", "list"}:
        if set(ctx.roles) & READ_ROLES:
            return Decision.permit(reason="task read role",
                                    policy_id=f"workflow.task.{sub}.role")
        return Decision.deny(reason="missing role for task read",
                              policy_id=f"workflow.task.{sub}.role_required")
    if sub == "cancel":
        if set(ctx.roles) & ADMIN_ROLES:
            return Decision.permit(reason="admin role",
                                    policy_id="workflow.task.cancel.role")
        return Decision.deny(reason="super_admin required",
                              policy_id="workflow.task.cancel.role_required")
    return None


def _workflow_timer(ctx: ExecutionContext, action: str, resource: dict,
                      env: dict) -> Optional[Decision]:
    if not action.startswith("workflow.timer."):
        return None
    if not ctx.is_authenticated:
        return Decision.deny(reason="authentication required",
                              policy_id=f"{action}.anonymous")
    sub = action.split(".", 2)[2]
    if sub in {"read", "list"}:
        if set(ctx.roles) & READ_ROLES:
            return Decision.permit(reason="timer read role",
                                    policy_id=f"workflow.timer.{sub}.role")
        return Decision.deny(reason="missing role for timer read",
                              policy_id=f"workflow.timer.{sub}.role_required")
    if sub in {"fire", "cancel"}:
        if set(ctx.roles) & ADMIN_ROLES:
            return Decision.permit(reason="admin role",
                                    policy_id=f"workflow.timer.{sub}.role")
        return Decision.deny(reason="super_admin required",
                              policy_id=f"workflow.timer.{sub}.role_required")
    return None


def _workflow_admin(ctx: ExecutionContext, action: str, resource: dict,
                      env: dict) -> Optional[Decision]:
    if not action.startswith("workflow.admin."):
        return None
    if not ctx.is_authenticated:
        return Decision.deny(reason="authentication required",
                              policy_id=f"{action}.anonymous")
    if set(ctx.roles) & ADMIN_ROLES:
        return Decision.permit(reason="admin role",
                                policy_id="workflow.admin.role")
    return Decision.deny(reason="super_admin required",
                          policy_id="workflow.admin.role_required")


def register_workflow_policies() -> None:
    """Idempotent registration of Phase 4 Slice 4.0 policies."""
    global _WORKFLOW_REGISTERED
    if _WORKFLOW_REGISTERED:
        return
    register_policy("workflow.instance", 300,
                     "Workflow instance start / cancel / suspend / "
                     "reactivate / read / list policies",
                     _workflow_instance)
    register_policy("workflow.task", 310,
                     "Workflow task claim / complete / cancel / "
                     "read / list policies",
                     _workflow_task)
    register_policy("workflow.timer", 320,
                     "Workflow timer fire / cancel / read / list policies",
                     _workflow_timer)
    register_policy("workflow.admin", 330,
                     "Workflow admin (replay) — super_admin only",
                     _workflow_admin)
    _WORKFLOW_REGISTERED = True
