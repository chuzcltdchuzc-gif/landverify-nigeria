"""Specifications for Evidence aggregate queries (Phase 3.4).

Immutable, composable specs translated to Mongo by the adapter only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class EvidenceItemSpec:
    tenant_id: Optional[str] = None
    country_code: Optional[str] = None
    registry_id: Optional[str] = None
    statuses: tuple[str, ...] = field(default_factory=tuple)
    kinds: tuple[str, ...] = field(default_factory=tuple)
    seal_id: Optional[str] = None
    created_by: Optional[str] = None

    def and_(self, other: "EvidenceItemSpec") -> "EvidenceItemSpec":
        return EvidenceItemSpec(
            tenant_id=other.tenant_id or self.tenant_id,
            country_code=other.country_code or self.country_code,
            registry_id=other.registry_id or self.registry_id,
            statuses=tuple(set(self.statuses + other.statuses)),
            kinds=tuple(set(self.kinds + other.kinds)),
            seal_id=other.seal_id or self.seal_id,
            created_by=other.created_by or self.created_by,
        )


@dataclass(frozen=True)
class SealSpec:
    tenant_id: Optional[str] = None
    country_code: Optional[str] = None
    registry_id: Optional[str] = None
    statuses: tuple[str, ...] = field(default_factory=tuple)
    created_by: Optional[str] = None

    def and_(self, other: "SealSpec") -> "SealSpec":
        return SealSpec(
            tenant_id=other.tenant_id or self.tenant_id,
            country_code=other.country_code or self.country_code,
            registry_id=other.registry_id or self.registry_id,
            statuses=tuple(set(self.statuses + other.statuses)),
            created_by=other.created_by or self.created_by,
        )


# Convenience builders
def ByRegistry(registry_id: str) -> EvidenceItemSpec:
    return EvidenceItemSpec(registry_id=registry_id)


def ByStatus(*statuses: str) -> EvidenceItemSpec:
    return EvidenceItemSpec(statuses=tuple(statuses))


def BySeal(seal_id: str) -> EvidenceItemSpec:
    return EvidenceItemSpec(seal_id=seal_id)


def SealByRegistry(registry_id: str) -> SealSpec:
    return SealSpec(registry_id=registry_id)
