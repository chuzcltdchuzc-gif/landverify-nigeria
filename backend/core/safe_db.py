"""Tenant-aware MongoDB collection wrapper.

`tdb.<collection>` returns a proxy whose every read/write transparently scopes
to the current request's tenant_id (see `core.tenant`). Cross-tenant code paths
must wrap calls in `bypass_tenant()`.

Supported operations (auto-scoped):
    find, find_one, count_documents, distinct, aggregate,
    update_one, update_many, find_one_and_update, find_one_and_replace,
    delete_one, delete_many, find_one_and_delete

Inserts auto-stamp `tenant_id` when missing.

This is the RLS-equivalent guard for the LandVault platform — no router or
service can accidentally leak data across tenants by forgetting a filter.
"""
from __future__ import annotations

from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorCollection

from core.database import db as _raw_db
from core.tenant import current_tenant, is_bypassed


def _tenant_filter() -> Optional[dict]:
    """Return the {tenant_id: ...} filter to merge, or None to bypass."""
    if is_bypassed():
        return None
    tid = current_tenant()
    if tid is None:
        # No tenant context = either pre-auth or test scaffolding. We refuse to
        # silently leak across tenants. Returning a filter that matches nothing
        # is safer than returning everything.
        return {"tenant_id": "__NO_TENANT_CONTEXT__"}
    return {"tenant_id": tid}


def _merge(base: Optional[dict], extra: Optional[dict]) -> dict:
    if not base:
        return extra or {}
    if not extra:
        return base
    # `$and` ensures we never overwrite a caller-supplied tenant_id (defence
    # in depth: even if a caller tries to query a foreign tenant, the AND
    # collapses to "no results" unless they match).
    if "tenant_id" in base and base.get("tenant_id") != extra.get("tenant_id"):
        return {"$and": [base, extra]}
    return {**base, **extra}


class SafeCollection:
    """Motor collection wrapper that injects tenant_id on every operation."""

    def __init__(self, raw: AsyncIOMotorCollection):
        self._raw = raw

    # ---- READ ------------------------------------------------------------
    def find(self, filter: Optional[dict] = None, *args, **kwargs):
        return self._raw.find(_merge(filter, _tenant_filter()), *args, **kwargs)

    async def find_one(self, filter: Optional[dict] = None, *args, **kwargs):
        return await self._raw.find_one(_merge(filter, _tenant_filter()), *args, **kwargs)

    async def count_documents(self, filter: Optional[dict] = None, *args, **kwargs):
        return await self._raw.count_documents(_merge(filter, _tenant_filter()), *args, **kwargs)

    async def distinct(self, key: str, filter: Optional[dict] = None, *args, **kwargs):
        return await self._raw.distinct(key, _merge(filter, _tenant_filter()), *args, **kwargs)

    def aggregate(self, pipeline: list, *args, **kwargs):
        tf = _tenant_filter()
        if tf:
            pipeline = [{"$match": tf}, *pipeline]
        return self._raw.aggregate(pipeline, *args, **kwargs)

    # ---- WRITE -----------------------------------------------------------
    async def insert_one(self, document: dict, *args, **kwargs):
        tf = _tenant_filter()
        if tf and "tenant_id" not in document:
            document = {**document, **tf}
        return await self._raw.insert_one(document, *args, **kwargs)

    async def insert_many(self, documents: list[dict], *args, **kwargs):
        tf = _tenant_filter()
        if tf:
            documents = [
                {**doc, **tf} if "tenant_id" not in doc else doc
                for doc in documents
            ]
        return await self._raw.insert_many(documents, *args, **kwargs)

    async def update_one(self, filter: dict, update: Any, *args, **kwargs):
        return await self._raw.update_one(_merge(filter, _tenant_filter()), update, *args, **kwargs)

    async def update_many(self, filter: dict, update: Any, *args, **kwargs):
        return await self._raw.update_many(_merge(filter, _tenant_filter()), update, *args, **kwargs)

    async def delete_one(self, filter: dict, *args, **kwargs):
        return await self._raw.delete_one(_merge(filter, _tenant_filter()), *args, **kwargs)

    async def delete_many(self, filter: dict, *args, **kwargs):
        return await self._raw.delete_many(_merge(filter, _tenant_filter()), *args, **kwargs)

    async def find_one_and_update(self, filter: dict, update: Any, *args, **kwargs):
        return await self._raw.find_one_and_update(_merge(filter, _tenant_filter()), update, *args, **kwargs)

    async def find_one_and_replace(self, filter: dict, replacement: dict, *args, **kwargs):
        return await self._raw.find_one_and_replace(_merge(filter, _tenant_filter()), replacement, *args, **kwargs)

    async def find_one_and_delete(self, filter: dict, *args, **kwargs):
        return await self._raw.find_one_and_delete(_merge(filter, _tenant_filter()), *args, **kwargs)

    # Direct access escape hatch (e.g. for indexes during startup).
    @property
    def raw(self) -> AsyncIOMotorCollection:
        return self._raw

    # Anything else (rare): delegate.
    def __getattr__(self, item):
        return getattr(self._raw, item)


class TenantDB:
    """Attribute-style access to SafeCollection wrappers, mirroring `db.*`."""

    def __init__(self, raw_db) -> None:
        self._raw_db = raw_db
        self._cache: dict[str, SafeCollection] = {}

    def __getattr__(self, name: str) -> SafeCollection:
        if name.startswith("_"):
            raise AttributeError(name)
        col = self._cache.get(name)
        if col is None:
            col = SafeCollection(getattr(self._raw_db, name))
            self._cache[name] = col
        return col


tdb = TenantDB(_raw_db)
