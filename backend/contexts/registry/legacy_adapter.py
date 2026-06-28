"""Legacy → Registry compatibility adapter (Phase 2A directive §2).

Translates legacy session-authenticated calls into a Registry
command-service invocation. The Registry is the AUTHORITATIVE writer
(per ADR-001); the legacy `parcels` collection now functions as a
read-only mirror for legacy routers and is rebuilt from the canonical
aggregate after every successful write.

Rules enforced here:

* The Registry write happens first. Only on success do we mirror to
  `parcels` (so the legacy collection can never hold a record the
  Registry doesn't acknowledge).
* No business logic — this module is a thin shim.
* The compatibility layer is a transition mechanism. After the
  migration tool (`contexts.registry.migration`) has been run and the
  legacy frontend has been cut over to `/api/v1/registry/*`, both this
  shim and the legacy collection can be removed.
"""
from __future__ import annotations

from typing import Optional

from contexts.registry.application import (
    PRIVILEGED_REGISTRY_ROLES,
    RegistryCommandService,
)
from kernel.persistence.context import ExecutionContext, set_context

_command_service: Optional[RegistryCommandService] = None


def configure_legacy_adapter(svc: RegistryCommandService) -> None:
    global _command_service
    _command_service = svc


def _build_legacy_context(user: dict) -> ExecutionContext:
    """Translate the legacy `user` dict (from `get_current_user`) into the
    canonical ExecutionContext used by the kernel and the Registry."""
    role = user.get("role") or "general_user"
    roles_list = list(user.get("roles") or [])
    if role and role not in roles_list:
        roles_list.append(role)
    # The legacy role names are upper-snake-case in some places; map to the
    # canonical lowercase canonical roles where they directly correspond.
    canonical_aliases = {
        "PLATFORM_SUPER_ADMIN": "super_admin",
        "FIELD_AGENT": "field_agent",
        "SURVEYOR": "surveyor",
        "COMPLIANCE_OFFICER": "compliance_officer",
        "SURVEYOR_GENERAL": "surveyor_general",
        "GENERAL_USER": "general_user",
        "LICENSED_SURVEYOR": "licensed_surveyor",
        "SURVEYOR_PARTNER": "surveyor_partner",
        "COMMUNITY_VALIDATOR": "community_validator",
        "GOVERNMENT_OBSERVER": "government_observer",
    }
    normalized = []
    for r in roles_list:
        normalized.append(canonical_aliases.get(r, r.lower() if r else r))
    # Legacy citizens get field_agent privileges for the purpose of CREATING
    # a parcel through the legacy path, because the legacy UI has always
    # allowed any logged-in user to upload a parcel. The Registry aggregate
    # still enforces tenant scoping and locked-state invariants.
    if "field_agent" not in normalized and "super_admin" not in normalized:
        normalized.append("field_agent")
    return ExecutionContext(
        principal_id=user.get("user_id") or "legacy_user",
        email=user.get("email"),
        country=user.get("country") or "NG",
        tenant_id=user.get("tenant_id") or "default",
        organization_id=user.get("organization_id"),
        roles=tuple(normalized),
    )


async def legacy_create_parcel_via_registry(*, user: dict, body) -> dict:
    """Run a legacy `POST /api/parcels` write through the Registry.

    Returns the parcel-shaped response the legacy frontend expects (the
    field set mirrors the historical schema).
    """
    if _command_service is None:
        raise RuntimeError("legacy adapter not configured (Phase 2A bootstrap)")

    ctx = _build_legacy_context(user)
    token = set_context(ctx)
    try:
        # Map legacy body → registry create kwargs.
        prop_type_alias = {
            "residential": "RES", "commercial": "COM", "farm": "FRM",
            "market": "MKT", "shop": "SHP", "settlement": "STL",
            "kiosk": "KSK", "government": "GOV", "institutional": "INS",
        }
        raw_pt = (getattr(body, "property_type", None) or "residential").lower()
        property_type = prop_type_alias.get(raw_pt, "RES")
        result = await _command_service.create_landvault(
            country_code=user.get("country") or "NG",
            state=getattr(body, "state", "") or "UNKNOWN",
            lga=getattr(body, "lga", "") or "UNKNOWN",
            ward=getattr(body, "ward", "") or "UNKNOWN",
            property_type=property_type,
            ownership_type="individual",
            owner_name=user.get("name") or user.get("full_name") or "Unknown",
            owner_email=user.get("email"),
            title=None,
            community=getattr(body, "community", None),
            address=None,
            geometry=None,
            legacy_aliases=[getattr(body, "parcel_number", None)]
                if getattr(body, "parcel_number", None) else [],
            field_agent_email=user.get("email"),
        )
    finally:
        # Restore previous context (reset_context expects the token).
        from kernel.persistence.context import reset_context
        reset_context(token)
    return result
