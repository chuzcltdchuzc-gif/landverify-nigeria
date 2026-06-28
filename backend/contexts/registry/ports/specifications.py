"""Specifications for the LandVault aggregate (Phase 2 §3.3, §3.4).

The Application Service expresses data needs through these specifications;
the Mongo adapter is the ONLY place that translates them into a query.

Specifications combine; the adapter accumulates clauses and emits a single
Mongo filter that always includes tenant + country scope.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class LandVaultSpec:
    """Immutable, composable specification for LandVault queries.

    Use the helper builders (``ByTenant``, ``ByStatus``, etc.) and combine
    with ``.and_(...)``. The adapter is the only translator to Mongo.
    """
    tenant_id: Optional[str] = None
    country_code: Optional[str] = None
    statuses: tuple[str, ...] = field(default_factory=tuple)
    owner_email: Optional[str] = None
    field_agent_email: Optional[str] = None
    surveyor_id: Optional[str] = None
    created_by: Optional[str] = None
    parcel_number: Optional[str] = None
    legacy_alias: Optional[str] = None
    include_deleted: bool = False
    near_point: Optional[tuple[float, float, float]] = None  # (lon, lat, max_meters)

    def and_(self, other: "LandVaultSpec") -> "LandVaultSpec":
        return LandVaultSpec(
            tenant_id=other.tenant_id or self.tenant_id,
            country_code=other.country_code or self.country_code,
            statuses=tuple(set(self.statuses + other.statuses)),
            owner_email=other.owner_email or self.owner_email,
            field_agent_email=other.field_agent_email or self.field_agent_email,
            surveyor_id=other.surveyor_id or self.surveyor_id,
            created_by=other.created_by or self.created_by,
            parcel_number=other.parcel_number or self.parcel_number,
            legacy_alias=other.legacy_alias or self.legacy_alias,
            include_deleted=self.include_deleted or other.include_deleted,
            near_point=other.near_point or self.near_point,
        )


# ---- Convenience builders (mirror Phase 2 §3.4 specification names) ------

def ByTenant(tenant_id: str) -> LandVaultSpec:
    return LandVaultSpec(tenant_id=tenant_id)


def ByCountry(country_code: str) -> LandVaultSpec:
    return LandVaultSpec(country_code=country_code)


def ByStatus(*statuses: str) -> LandVaultSpec:
    return LandVaultSpec(statuses=tuple(statuses))


def ByOwnerEmail(email: str) -> LandVaultSpec:
    return LandVaultSpec(owner_email=email.lower().strip())


def ByFieldAgentEmail(email: str) -> LandVaultSpec:
    return LandVaultSpec(field_agent_email=email.lower().strip())


def BySurveyor(surveyor_id: str) -> LandVaultSpec:
    return LandVaultSpec(surveyor_id=surveyor_id)


def CreatedBy(principal_id: str) -> LandVaultSpec:
    return LandVaultSpec(created_by=principal_id)


def Near(lon: float, lat: float, max_meters: float = 1000.0) -> LandVaultSpec:
    return LandVaultSpec(near_point=(lon, lat, max_meters))
