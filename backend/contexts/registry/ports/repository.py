"""Port: LandVault persistence + RegistryNumberAllocator.

The Application Service depends on these protocols only. Concrete
adapters (Mongo + others) implement them. Repositories are persistence-
only — they never raise domain events (Phase 2A §4).
"""
from __future__ import annotations

from typing import Optional, Protocol

from contexts.registry.domain.land_vault import LandVault
from contexts.registry.ports.specifications import LandVaultSpec


class LandVaultRepository(Protocol):
    async def ensure_indexes(self) -> None: ...

    async def get_by_registry_id(self, registry_id: str) -> Optional[LandVault]: ...

    async def get_by_parcel_number(self, parcel_number: str) -> Optional[LandVault]: ...

    async def get_by_legacy_alias(self, alias: str) -> Optional[LandVault]: ...

    async def add(self, agg: LandVault, *, session=None) -> LandVault: ...

    async def replace(self, agg: LandVault, *, expected_version: int,
                      session=None) -> LandVault: ...

    async def find(self, spec: LandVaultSpec, *, limit: int = 50,
                   skip: int = 0, sort: Optional[list[tuple]] = None) -> list[LandVault]: ...

    async def count(self, spec: LandVaultSpec) -> int: ...


class RegistryNumberAllocator(Protocol):
    async def ensure_indexes(self) -> None: ...

    async def allocate(self, *, country: str, state: str, lga: str, ward: str,
                       property_type: str, session=None) -> str:
        """Atomically allocate the next parcel_number for a sequence key.

        Returns a string of the form `STATE-LGA-WARD-PROPTYPE-NNNNNN`.
        MUST be concurrency-safe — parallel callers MUST receive distinct
        sequence numbers with zero duplicates.
        """
        ...
