"""Persistence ports for the Evidence context (Phase 3.4)."""
from __future__ import annotations

from typing import Optional, Protocol

from contexts.evidence.domain.evidence_item import EvidenceItem
from contexts.evidence.domain.seal import Seal
from contexts.evidence.ports.specifications import EvidenceItemSpec, SealSpec


class EvidenceItemRepository(Protocol):
    async def ensure_indexes(self) -> None: ...

    async def get(self, evidence_id: str) -> Optional[EvidenceItem]: ...

    async def get_many(self, evidence_ids: list[str]) -> list[EvidenceItem]: ...

    async def add(self, agg: EvidenceItem, *, session=None) -> EvidenceItem: ...

    async def replace(self, agg: EvidenceItem, *, expected_version: int,
                      session=None) -> EvidenceItem: ...

    async def find(self, spec: EvidenceItemSpec, *, limit: int = 50,
                   skip: int = 0, sort: Optional[list] = None
                   ) -> list[EvidenceItem]: ...

    async def count(self, spec: EvidenceItemSpec) -> int: ...


class SealRepository(Protocol):
    async def ensure_indexes(self) -> None: ...

    async def get(self, seal_id: str) -> Optional[Seal]: ...

    async def add(self, agg: Seal, *, session=None) -> Seal: ...

    async def replace(self, agg: Seal, *, expected_version: int,
                      session=None) -> Seal: ...

    async def find(self, spec: SealSpec, *, limit: int = 50,
                   skip: int = 0, sort: Optional[list] = None
                   ) -> list[Seal]: ...

    async def count(self, spec: SealSpec) -> int: ...
