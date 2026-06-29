"""Phase 3.8 — Kernel projection admin authorization policies.

Projection admin endpoints (replay, snapshot, health) are gated to
``super_admin`` only (ADR-0010 §5).
"""
from __future__ import annotations

from typing import Optional

from kernel.authorization.decisions import Decision
from kernel.authorization.policies import register_policy
from kernel.persistence.context import ExecutionContext

_REGISTERED = False


def _projection_admin(ctx: ExecutionContext, action: str, resource: dict,
                      env: dict) -> Optional[Decision]:
    if action != "kernel.projections.admin":
        return None
    if not ctx.is_authenticated:
        return Decision.deny(reason="authentication required",
                             policy_id="kernel.projections.admin.anonymous")
    if "super_admin" in ctx.roles:
        return Decision.permit(reason="super_admin",
                               policy_id="kernel.projections.admin.super_admin")
    return Decision.deny(reason="super_admin only",
                         policy_id="kernel.projections.admin.role_required")


def register_projection_policies() -> None:
    """Idempotent registration of Phase 3.8 projection admin policy."""
    global _REGISTERED
    if _REGISTERED:
        return
    register_policy("kernel.projections.admin", 100,
                    "Projection admin (replay/health/snapshot): super_admin only",
                    _projection_admin)
    _REGISTERED = True
