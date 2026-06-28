"""Repository base — mandatory persistence shape (ADR-002/003/007).

Tenant + country scope are injected from the authenticated ExecutionContext
on every read and write. Client-supplied scope values are ignored. All writes
stamp audit metadata and increment `version` for optimistic concurrency.

Concrete domain repositories MUST subclass `BaseRepository` (or fulfil its
port via composition) and MUST NOT bypass it to talk to Mongo directly.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

from kernel.errors.problem import bad_request, conflict, not_found
from kernel.persistence.context import current_context

logger = logging.getLogger("kernel.persistence.repository")

# When the collection is conceptually platform-global (e.g. signing keys,
# identity records before login), pass scope=GLOBAL to opt out of tenant
# scoping. The Identity context uses this for users, sessions, and keys
# (since users are *the* source of tenant_id).
GLOBAL = "GLOBAL"
TENANT_SCOPED = "TENANT_SCOPED"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RepositoryError(Exception):
    pass


class BaseRepository:
    """Common repository behaviour. Subclass to add domain methods."""

    collection_name: str = ""
    scope: str = TENANT_SCOPED   # override to GLOBAL for platform-global collections

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        if not self.collection_name:
            raise RepositoryError(f"{type(self).__name__} must define `collection_name`")
        self._db = db

    @property
    def collection(self) -> AsyncIOMotorCollection:
        return self._db[self.collection_name]

    # ---- Scope filtering ------------------------------------------------
    def _scope_filter(self) -> dict:
        if self.scope == GLOBAL:
            return {}
        ctx = current_context()
        if ctx.is_anonymous or not ctx.tenant_id:
            # Default-deny: anonymous principals or contexts without a tenant
            # cannot read tenant-scoped data through this repository.
            return {"tenant_id": "__NO_TENANT_CONTEXT__"}
        f: dict[str, Any] = {"tenant_id": ctx.tenant_id}
        if ctx.country:
            f["country"] = ctx.country
        return f

    def _merge(self, base: Optional[dict]) -> dict:
        scope = self._scope_filter()
        if not base:
            return scope
        if not scope:
            return dict(base)
        # Defence in depth — caller cannot override scope.
        merged = dict(base)
        merged.update(scope)
        return merged

    def _stamp_create(self, doc: dict) -> dict:
        ctx = current_context()
        now = _now_iso()
        out = dict(doc)
        if self.scope == TENANT_SCOPED:
            if not ctx.tenant_id:
                raise bad_request("Missing tenant context for tenant-scoped insert",
                                  code="persistence.no_tenant")
            out["tenant_id"] = ctx.tenant_id
            out["country"] = ctx.country
            if ctx.organization_id is not None:
                out.setdefault("organization_id", ctx.organization_id)
        out.setdefault("created_at", now)
        out.setdefault("created_by", ctx.principal_id)
        out["updated_at"] = now
        out["updated_by"] = ctx.principal_id
        out["version"] = 1
        out["schema_version"] = out.get("schema_version", 1)
        return out

    def _stamp_update(self, patch: dict) -> dict:
        ctx = current_context()
        out = dict(patch)
        out["updated_at"] = _now_iso()
        out["updated_by"] = ctx.principal_id
        return out

    # ---- CRUD ------------------------------------------------------------
    async def get(self, id_value: str, *, id_field: str = "id") -> Optional[dict]:
        doc = await self.collection.find_one(self._merge({id_field: id_value}), {"_id": 0})
        return doc

    async def get_or_404(self, id_value: str, *, id_field: str = "id") -> dict:
        doc = await self.get(id_value, id_field=id_field)
        if not doc:
            raise not_found(f"{self.collection_name} {id_value} not found",
                            code=f"{self.collection_name}.not_found")
        return doc

    async def find(self, spec: Optional[dict] = None, *, limit: int = 100, skip: int = 0,
                   sort: Optional[list[tuple]] = None) -> list[dict]:
        cur = self.collection.find(self._merge(spec), {"_id": 0})
        if sort:
            cur = cur.sort(sort)
        cur = cur.skip(skip).limit(limit)
        return [doc async for doc in cur]

    async def count(self, spec: Optional[dict] = None) -> int:
        return await self.collection.count_documents(self._merge(spec))

    async def add(self, doc: dict) -> dict:
        stamped = self._stamp_create(doc)
        await self.collection.insert_one(dict(stamped))
        return stamped

    async def update(self, id_value: str, patch: dict, *, expected_version: int,
                     id_field: str = "id") -> dict:
        if not isinstance(expected_version, int):
            raise bad_request("expected_version must be an integer",
                              code="persistence.bad_version")
        flt = self._merge({id_field: id_value, "version": expected_version})
        update = {"$set": self._stamp_update(patch), "$inc": {"version": 1}}
        result = await self.collection.find_one_and_update(
            flt, update, return_document=True, projection={"_id": 0},
        )
        if not result:
            # Was it a version mismatch or not found?
            existing = await self.collection.find_one(self._merge({id_field: id_value}),
                                                     {"_id": 0, "version": 1})
            if existing is None:
                raise not_found(f"{self.collection_name} {id_value} not found",
                                code=f"{self.collection_name}.not_found")
            raise conflict("Optimistic concurrency conflict",
                           code="persistence.version_conflict")
        return result

    async def soft_delete(self, id_value: str, reason: str, *, id_field: str = "id") -> None:
        ctx = current_context()
        await self.collection.update_one(
            self._merge({id_field: id_value}),
            {"$set": {"deleted_at": _now_iso(), "deleted_by": ctx.principal_id,
                      "delete_reason": reason, "status": "DELETED"}},
        )
