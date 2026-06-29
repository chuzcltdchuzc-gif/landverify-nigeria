"""Phase 3.7 Mongo adapters — append-only timeline, custody, legal hold.

All three collections are insert-only at the adapter; the only legal
mutation is the LegalHold ACTIVE → RELEASED transition via
``find_one_and_replace`` with a strict CAS predicate on ``status``.
"""
from __future__ import annotations

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from contexts.evidence.domain.invariants import (
    ConcurrencyConflict,
    ImmutableFieldError,
    InvariantViolation,
)
from contexts.evidence.domain.timeline import (
    CustodyEntry,
    LegalHold,
    LegalHoldStatus,
    TimelineEntry,
)
from kernel.persistence.context import current_context

TIMELINE_COLLECTION = "evidence_timeline"
CUSTODY_COLLECTION = "evidence_custody"
LEGAL_HOLD_COLLECTION = "evidence_legal_holds"


def _scope(q: Optional[dict] = None) -> dict:
    ctx = current_context()
    flt: dict = dict(q or {})
    if ctx.is_anonymous:
        flt["tenant_id"] = "__NO_TENANT_CONTEXT__"
        return flt
    if not ctx.has_role("super_admin"):
        if ctx.tenant_id:
            flt["tenant_id"] = ctx.tenant_id
        if ctx.country:
            flt["country_code"] = ctx.country
    return flt


class MongoTimelineRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self.collection = db[TIMELINE_COLLECTION]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("timeline_id", unique=True)
        await self.collection.create_index(
            [("evidence_id", 1), ("seq", 1)], unique=True)
        await self.collection.create_index("occurred_at")
        await self.collection.create_index(
            [("country_code", 1), ("tenant_id", 1)])

    async def head(self, evidence_id: str) -> Optional[TimelineEntry]:
        doc = await self.collection.find_one(
            {"evidence_id": evidence_id}, {"_id": 0}, sort=[("seq", -1)])
        return TimelineEntry.from_state(doc) if doc else None

    async def append(self, entry: TimelineEntry, *, session=None) -> None:
        try:
            await self.collection.insert_one(dict(entry.to_state()),
                                                session=session)
        except Exception as exc:  # noqa: BLE001
            if "duplicate key" in str(exc).lower():
                raise InvariantViolation(
                    f"duplicate timeline (evidence_id={entry.evidence_id},"
                    f"seq={entry.seq})") from exc
            raise

    async def chain(self, evidence_id: str) -> list[TimelineEntry]:
        cur = self.collection.find(_scope({"evidence_id": evidence_id}),
                                     {"_id": 0}).sort("seq", 1)
        return [TimelineEntry.from_state(d) async for d in cur]


class MongoCustodyRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self.collection = db[CUSTODY_COLLECTION]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("custody_id", unique=True)
        await self.collection.create_index(
            [("evidence_id", 1), ("seq", 1)], unique=True)
        await self.collection.create_index("occurred_at")
        await self.collection.create_index(
            [("country_code", 1), ("tenant_id", 1)])

    async def head(self, evidence_id: str) -> Optional[CustodyEntry]:
        doc = await self.collection.find_one(
            {"evidence_id": evidence_id}, {"_id": 0}, sort=[("seq", -1)])
        return CustodyEntry.from_state(doc) if doc else None

    async def append(self, entry: CustodyEntry, *, session=None) -> None:
        try:
            await self.collection.insert_one(dict(entry.to_state()),
                                                session=session)
        except Exception as exc:  # noqa: BLE001
            if "duplicate key" in str(exc).lower():
                raise InvariantViolation(
                    f"duplicate custody (evidence_id={entry.evidence_id},"
                    f"seq={entry.seq})") from exc
            raise

    async def chain(self, evidence_id: str) -> list[CustodyEntry]:
        cur = self.collection.find(_scope({"evidence_id": evidence_id}),
                                     {"_id": 0}).sort("seq", 1)
        return [CustodyEntry.from_state(d) async for d in cur]


class MongoLegalHoldRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self.collection = db[LEGAL_HOLD_COLLECTION]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("hold_id", unique=True)
        await self.collection.create_index(
            [("evidence_id", 1), ("status", 1)])
        await self.collection.create_index("case_reference")
        await self.collection.create_index(
            [("country_code", 1), ("tenant_id", 1)])

    async def add(self, agg: LegalHold, *, session=None) -> LegalHold:
        await self.collection.insert_one(dict(agg.to_state()), session=session)
        return agg

    async def get(self, hold_id: str) -> Optional[LegalHold]:
        doc = await self.collection.find_one(_scope({"hold_id": hold_id}),
                                               {"_id": 0})
        return LegalHold.from_state(doc) if doc else None

    async def active_for_evidence(self, evidence_id: str
                                     ) -> list[LegalHold]:
        cur = self.collection.find(
            _scope({"evidence_id": evidence_id,
                     "status": LegalHoldStatus.ACTIVE.value}),
            {"_id": 0}).sort("issued_at", -1)
        return [LegalHold.from_state(d) async for d in cur]

    async def list_for_evidence(self, evidence_id: str
                                  ) -> list[LegalHold]:
        cur = self.collection.find(_scope({"evidence_id": evidence_id}),
                                     {"_id": 0}).sort("issued_at", -1)
        return [LegalHold.from_state(d) async for d in cur]

    async def release(self, agg: LegalHold, *, expected_version: int,
                       session=None) -> LegalHold:
        """CAS-guarded: only flips status while status=='active'."""
        flt = {"hold_id": agg.hold_id, "version": expected_version,
                "status": LegalHoldStatus.ACTIVE.value}
        result = await self.collection.find_one_and_replace(
            flt, dict(agg.to_state()), return_document=True,
            projection={"_id": 0}, session=session)
        if not result:
            existing = await self.collection.find_one(
                {"hold_id": agg.hold_id}, {"_id": 0, "version": 1, "status": 1},
                session=session)
            if existing is None:
                raise ConcurrencyConflict(
                    f"LegalHold {agg.hold_id} not found")
            if existing.get("status") != LegalHoldStatus.ACTIVE.value:
                raise ImmutableFieldError(
                    f"LegalHold {agg.hold_id} not active ({existing.get('status')})"
                )
            raise ConcurrencyConflict(
                f"version conflict on {agg.hold_id}: expected "
                f"{expected_version}, on-disk {existing.get('version')}")
        return LegalHold.from_state(result)
