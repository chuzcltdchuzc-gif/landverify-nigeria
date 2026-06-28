"""Policy Information Point — supplies attributes the PDP needs.

For Phase 1 principal attributes come entirely from the verified JWT claims
(no DB lookups in the hot path — keeps authz O(1)). The PIP exposes helpers
that can be used by domain code to enrich a resource descriptor before
calling `authorize()`.
"""
from __future__ import annotations

from typing import Any, Optional

from kernel.persistence.context import ExecutionContext, current_context


def principal_attributes(ctx: Optional[ExecutionContext] = None) -> dict[str, Any]:
    ctx = ctx or current_context()
    return {
        "principal_id": ctx.principal_id,
        "country": ctx.country,
        "tenant_id": ctx.tenant_id,
        "organization_id": ctx.organization_id,
        "roles": list(ctx.roles),
        **dict(ctx.attributes),
    }


def resource_descriptor(resource_type: str, *, resource_id: Optional[str] = None,
                        tenant_id: Optional[str] = None, country: Optional[str] = None,
                        organization_id: Optional[str] = None,
                        owner_id: Optional[str] = None,
                        classification: Optional[str] = None,
                        extra: Optional[dict] = None) -> dict[str, Any]:
    desc: dict[str, Any] = {"resource_type": resource_type, "resource_id": resource_id,
                            "tenant_id": tenant_id, "country": country,
                            "organization_id": organization_id, "owner_id": owner_id,
                            "classification": classification}
    if extra:
        desc.update(extra)
    return {k: v for k, v in desc.items() if v is not None}
