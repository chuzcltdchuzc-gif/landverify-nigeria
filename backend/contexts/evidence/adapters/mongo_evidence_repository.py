"""Mongo adapter for EvidenceItem + Seal repositories (Phase 3.4).

Persistence ONLY — these classes never raise domain events. Tenant +
country scoping is enforced inside ``_scope_filter()`` via the
ExecutionContext; client-supplied tenant_id / country_code values are
ignored as a defense-in-depth measure.
"""
from __future__ import annotations

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from contexts.evidence.domain.evidence_item import EvidenceItem
from contexts.evidence.domain.invariants import ConcurrencyConflict
from contexts.evidence.domain.seal import Seal
from contexts.evidence.ports.specifications import EvidenceItemSpec, SealSpec
from kernel.errors.problem import conflict
from kernel.persistence.context import current_context

EVIDENCE_ITEMS_COLLECTION = "evidence_items"
EVIDENCE_SEALS_COLLECTION = "evidence_seals"


def _scope(*, include_archived: bool = False) -> dict:
    ctx = current_context()
    flt: dict = {}
    if ctx.is_anonymous:
        return {"tenant_id": "__NO_TENANT_CONTEXT__"}
    if not ctx.has_role("super_admin"):
        if ctx.tenant_id:
            flt["tenant_id"] = ctx.tenant_id
        if ctx.country:
            flt["country_code"] = ctx.country
    if not include_archived:
        flt.setdefault("status", {})
    return flt


class MongoEvidenceItemRepository:
    """`evidence_items` collection."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self.collection = db[EVIDENCE_ITEMS_COLLECTION]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("evidence_id", unique=True)
        await self.collection.create_index([("country_code", 1), ("tenant_id", 1)])
        await self.collection.create_index(
            [("country_code", 1), ("tenant_id", 1), ("status", 1)])
        await self.collection.create_index("registry_id")
        await self.collection.create_index("seal_id", sparse=True)
        await self.collection.create_index("created_by")
        await self.collection.create_index("created_at")

    def _spec_filter(self, spec: EvidenceItemSpec) -> dict:
        ctx = current_context()
        flt: dict = {}
        if ctx.is_anonymous:
            return {"tenant_id": "__NO_TENANT_CONTEXT__"}
        if not ctx.has_role("super_admin"):
            if ctx.tenant_id:
                flt["tenant_id"] = ctx.tenant_id
            if ctx.country:
                flt["country_code"] = ctx.country
        else:
            if spec.tenant_id:
                flt["tenant_id"] = spec.tenant_id
            if spec.country_code:
                flt["country_code"] = spec.country_code
        if spec.registry_id:
            flt["registry_id"] = spec.registry_id
        if spec.statuses:
            flt["status"] = {"$in": list(spec.statuses)}
        if spec.kinds:
            flt["kind"] = {"$in": list(spec.kinds)}
        if spec.seal_id:
            flt["seal_id"] = spec.seal_id
        if spec.created_by:
            flt["created_by"] = spec.created_by
        return flt

    async def _hydrate(self, doc: Optional[dict]) -> Optional[EvidenceItem]:
        if not doc:
            return None
        return EvidenceItem.from_state({k: v for k, v in doc.items()
                                         if k != "_id"})

    async def get(self, evidence_id: str) -> Optional[EvidenceItem]:
        ctx = current_context()
        flt: dict = {"evidence_id": evidence_id}
        if not ctx.has_role("super_admin"):
            if ctx.tenant_id:
                flt["tenant_id"] = ctx.tenant_id
            if ctx.country:
                flt["country_code"] = ctx.country
        doc = await self.collection.find_one(flt, {"_id": 0})
        return await self._hydrate(doc)

    async def get_many(self, evidence_ids: list[str]) -> list[EvidenceItem]:
        if not evidence_ids:
            return []
        ctx = current_context()
        flt: dict = {"evidence_id": {"$in": list(evidence_ids)}}
        if not ctx.has_role("super_admin"):
            if ctx.tenant_id:
                flt["tenant_id"] = ctx.tenant_id
            if ctx.country:
                flt["country_code"] = ctx.country
        cur = self.collection.find(flt, {"_id": 0})
        return [EvidenceItem.from_state(d) async for d in cur]

    async def find(self, spec: EvidenceItemSpec, *, limit: int = 50,
                   skip: int = 0, sort: Optional[list] = None
                   ) -> list[EvidenceItem]:
        flt = self._spec_filter(spec)
        cur = self.collection.find(flt, {"_id": 0})
        if sort:
            cur = cur.sort(sort)
        cur = cur.skip(skip).limit(limit)
        return [EvidenceItem.from_state(d) async for d in cur]

    async def count(self, spec: EvidenceItemSpec) -> int:
        return await self.collection.count_documents(self._spec_filter(spec))

    async def add(self, agg: EvidenceItem, *, session=None) -> EvidenceItem:
        try:
            await self.collection.insert_one(dict(agg.to_state()),
                                              session=session)
        except Exception as exc:  # noqa: BLE001
            if "duplicate key" in str(exc).lower():
                raise conflict(
                    "duplicate evidence_id",
                    code="evidence.duplicate_identifier",
                ) from exc
            raise
        return agg

    async def replace(self, agg: EvidenceItem, *, expected_version: int,
                      session=None) -> EvidenceItem:
        flt = {"evidence_id": agg.evidence_id, "version": expected_version}
        result = await self.collection.find_one_and_replace(
            flt, dict(agg.to_state()), return_document=True,
            projection={"_id": 0}, session=session,
        )
        if not result:
            existing = await self.collection.find_one(
                {"evidence_id": agg.evidence_id},
                {"_id": 0, "version": 1}, session=session,
            )
            if existing is None:
                raise ConcurrencyConflict(
                    f"EvidenceItem {agg.evidence_id} not found during replace"
                )
            raise ConcurrencyConflict(
                f"version conflict on {agg.evidence_id}: "
                f"expected {expected_version}, on-disk {existing.get('version')}"
            )
        return EvidenceItem.from_state(result)


class MongoSealRepository:
    """`evidence_seals` collection."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self.collection = db[EVIDENCE_SEALS_COLLECTION]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("seal_id", unique=True)
        await self.collection.create_index([("country_code", 1), ("tenant_id", 1)])
        await self.collection.create_index("registry_id")
        await self.collection.create_index([("manifest_hash", 1)])
        await self.collection.create_index("status")
        await self.collection.create_index("anchor_batch_id", sparse=True)
        await self.collection.create_index("created_at")

    def _spec_filter(self, spec: SealSpec) -> dict:
        ctx = current_context()
        flt: dict = {}
        if ctx.is_anonymous:
            return {"tenant_id": "__NO_TENANT_CONTEXT__"}
        if not ctx.has_role("super_admin"):
            if ctx.tenant_id:
                flt["tenant_id"] = ctx.tenant_id
            if ctx.country:
                flt["country_code"] = ctx.country
        else:
            if spec.tenant_id:
                flt["tenant_id"] = spec.tenant_id
            if spec.country_code:
                flt["country_code"] = spec.country_code
        if spec.registry_id:
            flt["registry_id"] = spec.registry_id
        if spec.statuses:
            flt["status"] = {"$in": list(spec.statuses)}
        if spec.created_by:
            flt["created_by"] = spec.created_by
        return flt

    async def get(self, seal_id: str) -> Optional[Seal]:
        ctx = current_context()
        flt: dict = {"seal_id": seal_id}
        if not ctx.has_role("super_admin"):
            if ctx.tenant_id:
                flt["tenant_id"] = ctx.tenant_id
            if ctx.country:
                flt["country_code"] = ctx.country
        doc = await self.collection.find_one(flt, {"_id": 0})
        if not doc:
            return None
        return Seal.from_state(doc)

    async def add(self, agg: Seal, *, session=None) -> Seal:
        try:
            await self.collection.insert_one(dict(agg.to_state()),
                                              session=session)
        except Exception as exc:  # noqa: BLE001
            if "duplicate key" in str(exc).lower():
                raise conflict(
                    "duplicate seal_id",
                    code="evidence.duplicate_identifier",
                ) from exc
            raise
        return agg

    async def replace(self, agg: Seal, *, expected_version: int,
                      session=None) -> Seal:
        flt = {"seal_id": agg.seal_id, "version": expected_version}
        result = await self.collection.find_one_and_replace(
            flt, dict(agg.to_state()), return_document=True,
            projection={"_id": 0}, session=session,
        )
        if not result:
            existing = await self.collection.find_one(
                {"seal_id": agg.seal_id}, {"_id": 0, "version": 1},
                session=session,
            )
            if existing is None:
                raise ConcurrencyConflict(
                    f"Seal {agg.seal_id} not found during replace"
                )
            raise ConcurrencyConflict(
                f"version conflict on {agg.seal_id}: "
                f"expected {expected_version}, on-disk {existing.get('version')}"
            )
        return Seal.from_state(result)

    async def find(self, spec: SealSpec, *, limit: int = 50,
                   skip: int = 0, sort: Optional[list] = None
                   ) -> list[Seal]:
        flt = self._spec_filter(spec)
        cur = self.collection.find(flt, {"_id": 0})
        if sort:
            cur = cur.sort(sort)
        cur = cur.skip(skip).limit(limit)
        return [Seal.from_state(d) async for d in cur]

    async def count(self, spec: SealSpec) -> int:
        return await self.collection.count_documents(self._spec_filter(spec))
