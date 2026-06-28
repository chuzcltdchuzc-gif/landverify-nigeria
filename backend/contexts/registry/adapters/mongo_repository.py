"""Mongo adapter: LandVaultRepository.

Persistence ONLY (Phase 2A §4). This class never raises domain events.
Tenant + country scoping is enforced inside `_scope_filter()` via the
ExecutionContext — client-supplied tenant_id or country_code values are
ignored as a defense-in-depth measure.
"""
from __future__ import annotations

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from contexts.registry.domain.invariants import ConcurrencyConflict
from contexts.registry.domain.land_vault import LandVault
from contexts.registry.ports.specifications import LandVaultSpec
from kernel.errors.problem import conflict
from kernel.persistence.context import current_context

LANDVAULT_COLLECTION = "landvault_landvaults"


class MongoLandVaultRepository:
    """All reads/writes are filtered by the current ExecutionContext scope.

    Super-admin bypass is NOT performed here — the PEP authorizes the
    *action* against the resource. This adapter applies tenant + country
    isolation as a final line of defense (Phase 2 §3.3 "Repository
    Defense-in-Depth").
    """

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self.collection = db[LANDVAULT_COLLECTION]

    async def ensure_indexes(self) -> None:
        # Identity (Phase 2 §3.4)
        await self.collection.create_index("registry_id", unique=True)
        await self.collection.create_index("parcel_number", unique=True)
        await self.collection.create_index(
            "legacy_aliases",
            sparse=True,
            name="idx_legacy_aliases_sparse",
        )
        # Scope — every query carries (country_code, tenant_id)
        await self.collection.create_index([("country_code", 1), ("tenant_id", 1)])
        await self.collection.create_index(
            [("country_code", 1), ("tenant_id", 1), ("status", 1)])
        # Common access patterns
        await self.collection.create_index("status")
        await self.collection.create_index("created_at")
        await self.collection.create_index("owner_email")
        await self.collection.create_index("field_agent_email")
        await self.collection.create_index("surveyor_id")
        await self.collection.create_index("created_by")
        # Provenance — for migration idempotency
        await self.collection.create_index(
            [("origin.source_system", 1), ("origin.source_id", 1)],
            name="idx_origin_provenance",
        )
        # Geometry — 2dsphere
        await self.collection.create_index([("geometry", "2dsphere")])

    # ---- Scope ---------------------------------------------------------

    def _scope_filter(self, *, include_deleted: bool = False) -> dict:
        ctx = current_context()
        flt: dict = {}
        # Super admin bypass is reserved for cross-scope reads (the PEP
        # has already authorized the action). Anonymous never matches.
        if ctx.is_anonymous and not include_deleted:
            return {"tenant_id": "__NO_TENANT_CONTEXT__"}
        if not ctx.has_role("super_admin"):
            if ctx.tenant_id:
                flt["tenant_id"] = ctx.tenant_id
            if ctx.country:
                flt["country_code"] = ctx.country
        if not include_deleted:
            flt["deleted_at"] = None
        return flt

    def _spec_to_filter(self, spec: LandVaultSpec) -> dict:
        ctx = current_context()
        flt = self._scope_filter(include_deleted=spec.include_deleted)
        # Specification clauses (must not override scope already applied).
        if spec.tenant_id and ctx.has_role("super_admin"):
            flt["tenant_id"] = spec.tenant_id
        if spec.country_code and ctx.has_role("super_admin"):
            flt["country_code"] = spec.country_code
        if spec.statuses:
            flt["status"] = {"$in": list(spec.statuses)}
        if spec.owner_email:
            flt["owner_email"] = spec.owner_email
        if spec.field_agent_email:
            flt["field_agent_email"] = spec.field_agent_email
        if spec.surveyor_id:
            flt["surveyor_id"] = spec.surveyor_id
        if spec.created_by:
            flt["created_by"] = spec.created_by
        if spec.parcel_number:
            flt["parcel_number"] = spec.parcel_number
        if spec.legacy_alias:
            flt["legacy_aliases"] = spec.legacy_alias
        if spec.near_point:
            lon, lat, max_m = spec.near_point
            flt["geometry"] = {
                "$near": {
                    "$geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "$maxDistance": max_m,
                }
            }
        return flt

    # ---- Reads ---------------------------------------------------------

    async def _hydrate(self, doc: Optional[dict]) -> Optional[LandVault]:
        if not doc:
            return None
        return LandVault.from_state({k: v for k, v in doc.items()
                                      if k != "_id"})

    async def get_by_registry_id(self, registry_id: str) -> Optional[LandVault]:
        flt = self._scope_filter()
        flt["registry_id"] = registry_id
        doc = await self.collection.find_one(flt, {"_id": 0})
        return await self._hydrate(doc)

    async def get_by_parcel_number(self, parcel_number: str) -> Optional[LandVault]:
        flt = self._scope_filter()
        flt["parcel_number"] = parcel_number
        doc = await self.collection.find_one(flt, {"_id": 0})
        return await self._hydrate(doc)

    async def get_by_legacy_alias(self, alias: str) -> Optional[LandVault]:
        flt = self._scope_filter()
        flt["legacy_aliases"] = alias
        doc = await self.collection.find_one(flt, {"_id": 0})
        return await self._hydrate(doc)

    async def find(self, spec: LandVaultSpec, *, limit: int = 50,
                   skip: int = 0, sort: Optional[list[tuple]] = None) -> list[LandVault]:
        flt = self._spec_to_filter(spec)
        cur = self.collection.find(flt, {"_id": 0})
        if sort:
            cur = cur.sort(sort)
        cur = cur.skip(skip).limit(limit)
        return [LandVault.from_state(doc) async for doc in cur]

    async def count(self, spec: LandVaultSpec) -> int:
        flt = self._spec_to_filter(spec)
        return await self.collection.count_documents(flt)

    # ---- Writes --------------------------------------------------------

    async def add(self, agg: LandVault, *, session=None) -> LandVault:
        state = agg.to_state()
        try:
            await self.collection.insert_one(dict(state), session=session)
        except Exception as exc:  # noqa: BLE001
            if "duplicate key" in str(exc).lower():
                raise conflict(
                    "duplicate registry identifier — parcel_number or "
                    "registry_id already exists",
                    code="registry.duplicate_identifier",
                ) from exc
            raise
        return agg

    async def replace(self, agg: LandVault, *, expected_version: int,
                      session=None) -> LandVault:
        state = agg.to_state()
        # Optimistic concurrency: the aggregate already incremented its
        # version; we match the PREVIOUS version on disk.
        flt = {"registry_id": agg.registry_id, "version": expected_version}
        result = await self.collection.find_one_and_replace(
            flt, dict(state), return_document=True, projection={"_id": 0},
            session=session,
        )
        if not result:
            existing = await self.collection.find_one(
                {"registry_id": agg.registry_id},
                {"_id": 0, "version": 1},
                session=session,
            )
            if existing is None:
                raise ConcurrencyConflict(
                    f"LandVault {agg.registry_id} not found during replace"
                )
            raise ConcurrencyConflict(
                f"version conflict on {agg.registry_id}: "
                f"expected {expected_version}, on-disk {existing.get('version')}"
            )
        return LandVault.from_state(result)
