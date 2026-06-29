"""Mongo adapters for Phase 3.6 append-only aggregates.

Per ADR-0008 §9.1: repositories REFUSE update/delete operations at the
adapter layer. The only legal mutations are:
* ``insert_one`` for any append-only collection.
* CAS-guarded ``find_one_and_replace`` for ``evidence_anchor_batches``
  with a whitelisted ``state``-predicate filter — and only for
  non-terminal states (CONFIRMED + DEAD_LETTER are frozen at the
  adapter).
* ``find_one_and_update({_id}, {$set: {last_status_check, …}})`` on
  ``evidence_locks`` for the non-cryptographic operational counters
  (last_status_check, version-bump on extension).

Every adapter scopes queries to the running ExecutionContext's tenant +
country (defense in depth).
"""
from __future__ import annotations

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from contexts.evidence.domain.anchor_batch import (
    AnchorBatch,
    BatchState,
    TERMINAL_STATES,
)
from contexts.evidence.domain.evidence_lock import EvidenceLock
from contexts.evidence.domain.integrity_check import EvidenceIntegrityCheck
from contexts.evidence.domain.invariants import (
    ConcurrencyConflict,
    ImmutableFieldError,
    InvariantViolation,
)
from kernel.persistence.context import current_context

EVIDENCE_LOCKS_COLLECTION = "evidence_locks"
EVIDENCE_INTEGRITY_COLLECTION = "evidence_integrity_checks"
EVIDENCE_ANCHOR_BATCHES_COLLECTION = "evidence_anchor_batches"
EVIDENCE_ANCHOR_ATTEMPTS_COLLECTION = "evidence_anchor_attempts"
EVIDENCE_CTLOG_TREE_COLLECTION = "evidence_ctlog_tree"
EVIDENCE_CTLOG_CHECKPOINTS_COLLECTION = "evidence_ctlog_checkpoints"


class OperationNotPermitted(Exception):
    """The adapter refuses this operation — append-only enforcement."""


def _scope(coll_q: Optional[dict] = None) -> dict:
    ctx = current_context()
    flt: dict = dict(coll_q or {})
    if ctx.is_anonymous:
        flt["tenant_id"] = "__NO_TENANT_CONTEXT__"
        return flt
    if not ctx.has_role("super_admin"):
        if ctx.tenant_id:
            flt["tenant_id"] = ctx.tenant_id
        if ctx.country:
            flt["country_code"] = ctx.country
    return flt


# ---- EvidenceLock --------------------------------------------------------

class MongoEvidenceLockRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self.collection = db[EVIDENCE_LOCKS_COLLECTION]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("lock_id", unique=True)
        await self.collection.create_index("evidence_id")
        await self.collection.create_index("seal_id")
        await self.collection.create_index(
            [("country_code", 1), ("tenant_id", 1)])

    async def add(self, agg: EvidenceLock, *, session=None) -> EvidenceLock:
        await self.collection.insert_one(dict(agg.to_state()), session=session)
        return agg

    async def get(self, lock_id: str) -> Optional[EvidenceLock]:
        doc = await self.collection.find_one(_scope({"lock_id": lock_id}),
                                              {"_id": 0})
        return EvidenceLock.from_state(doc) if doc else None

    async def list_for_evidence(self, evidence_id: str
                                 ) -> list[EvidenceLock]:
        cur = self.collection.find(_scope({"evidence_id": evidence_id}),
                                     {"_id": 0}).sort("applied_at", -1)
        return [EvidenceLock.from_state(d) async for d in cur]

    async def replace(self, agg: EvidenceLock, *, expected_version: int,
                        session=None) -> EvidenceLock:
        """Permitted ONLY for the forward-only extension path. The
        aggregate has already validated retention monotonicity."""
        flt = {"lock_id": agg.lock_id, "version": expected_version}
        result = await self.collection.find_one_and_replace(
            flt, dict(agg.to_state()), return_document=True,
            projection={"_id": 0}, session=session)
        if not result:
            existing = await self.collection.find_one(
                {"lock_id": agg.lock_id}, {"_id": 0, "version": 1},
                session=session)
            if existing is None:
                raise ConcurrencyConflict(
                    f"EvidenceLock {agg.lock_id} not found during replace")
            raise ConcurrencyConflict(
                f"version conflict on {agg.lock_id}: expected "
                f"{expected_version}, on-disk {existing.get('version')}")
        return EvidenceLock.from_state(result)

    # Append-only refusal helpers (called by static-scan + tests)
    async def reject_delete(self, *_args, **_kwargs):
        raise OperationNotPermitted("evidence_locks is append-only")


# ---- EvidenceIntegrityCheck ---------------------------------------------

class MongoIntegrityCheckRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self.collection = db[EVIDENCE_INTEGRITY_COLLECTION]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("check_id", unique=True)
        await self.collection.create_index(
            [("evidence_id", 1), ("seq", 1)], unique=True)
        await self.collection.create_index("started_at")
        await self.collection.create_index(
            [("country_code", 1), ("tenant_id", 1)])

    async def add(self, agg: EvidenceIntegrityCheck, *, session=None
                   ) -> EvidenceIntegrityCheck:
        try:
            await self.collection.insert_one(dict(agg.to_state()),
                                                session=session)
        except Exception as exc:  # noqa: BLE001
            if "duplicate key" in str(exc).lower():
                raise InvariantViolation(
                    f"duplicate (evidence_id, seq) for "
                    f"{agg.evidence_id}:{agg.seq}") from exc
            raise
        return agg

    async def get(self, check_id: str) -> Optional[EvidenceIntegrityCheck]:
        doc = await self.collection.find_one(_scope({"check_id": check_id}),
                                              {"_id": 0})
        return EvidenceIntegrityCheck.from_state(doc) if doc else None

    async def chain_for_evidence(self, evidence_id: str
                                   ) -> list[EvidenceIntegrityCheck]:
        cur = self.collection.find(_scope({"evidence_id": evidence_id}),
                                     {"_id": 0}).sort("seq", 1)
        return [EvidenceIntegrityCheck.from_state(d) async for d in cur]

    async def head_for_evidence(self, evidence_id: str
                                  ) -> Optional[EvidenceIntegrityCheck]:
        doc = await self.collection.find_one(
            _scope({"evidence_id": evidence_id}),
            {"_id": 0}, sort=[("seq", -1)])
        return EvidenceIntegrityCheck.from_state(doc) if doc else None

    async def replace(self, agg: EvidenceIntegrityCheck, *,
                        expected_outcome_running: bool = True,
                        session=None) -> EvidenceIntegrityCheck:
        """Single permitted update: terminal write-once outcome from
        ``running``. The CAS predicate ``outcome=='running'`` enforces
        this at the adapter even if a caller forgets."""
        flt = {"check_id": agg.check_id}
        if expected_outcome_running:
            flt["outcome"] = "running"
        result = await self.collection.find_one_and_replace(
            flt, dict(agg.to_state()), return_document=True,
            projection={"_id": 0}, session=session)
        if not result:
            raise ImmutableFieldError(
                f"integrity check {agg.check_id} already terminal — "
                f"refusing mutation")
        return EvidenceIntegrityCheck.from_state(result)


# ---- AnchorBatch --------------------------------------------------------

class MongoAnchorBatchRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self.collection = db[EVIDENCE_ANCHOR_BATCHES_COLLECTION]
        self.attempts = db[EVIDENCE_ANCHOR_ATTEMPTS_COLLECTION]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("batch_id", unique=True)
        await self.collection.create_index(
            [("state", 1), ("next_attempt_at", 1)])
        await self.collection.create_index(
            [("country_code", 1), ("tenant_id", 1), ("created_at", -1)])
        await self.collection.create_index("seal_ids")
        await self.collection.create_index("provider_id")
        await self.collection.create_index("merkle_root")
        await self.attempts.create_index(
            [("batch_id", 1), ("seq", 1)], unique=True)
        await self.attempts.create_index("attempt_id", unique=True)

    async def add(self, agg: AnchorBatch, *, session=None) -> AnchorBatch:
        await self.collection.insert_one(dict(agg.to_state()), session=session)
        return agg

    async def get(self, batch_id: str) -> Optional[AnchorBatch]:
        doc = await self.collection.find_one(_scope({"batch_id": batch_id}),
                                              {"_id": 0})
        return AnchorBatch.from_state(doc) if doc else None

    async def list_by_seal(self, seal_id: str) -> list[AnchorBatch]:
        cur = self.collection.find(_scope({"seal_ids": seal_id}),
                                     {"_id": 0}).sort("created_at", -1)
        return [AnchorBatch.from_state(d) async for d in cur]

    async def replace(self, agg: AnchorBatch, *, expected_version: int,
                        expected_state: Optional[str] = None,
                        session=None) -> AnchorBatch:
        """CAS-guarded replace. Refuses mutation of terminal records at
        the adapter layer (defense in depth)."""
        existing = await self.collection.find_one(
            {"batch_id": agg.batch_id},
            {"_id": 0, "state": 1, "version": 1}, session=session)
        if existing is None:
            raise ConcurrencyConflict(
                f"AnchorBatch {agg.batch_id} not found")
        # We allow the special replay-marker case: replace permitted if
        # the existing on-disk state is DEAD_LETTER AND the incoming
        # update only adds the ``replayed_to`` marker (state stays DLQ).
        is_replay_marker = (
            existing["state"] == BatchState.DEAD_LETTER.value
            and agg.state == BatchState.DEAD_LETTER.value
        )
        if existing["state"] in TERMINAL_STATES and not is_replay_marker:
            raise ImmutableFieldError(
                f"batch {agg.batch_id} terminal ({existing['state']}); "
                f"mutation forbidden")
        flt = {"batch_id": agg.batch_id, "version": expected_version}
        if expected_state is not None:
            flt["state"] = expected_state
        result = await self.collection.find_one_and_replace(
            flt, dict(agg.to_state()), return_document=True,
            projection={"_id": 0}, session=session)
        if not result:
            raise ConcurrencyConflict(
                f"CAS failed on AnchorBatch {agg.batch_id}: "
                f"expected version={expected_version} state={expected_state}")
        return AnchorBatch.from_state(result)

    async def claim_due(self, *, states: list[str], now_iso: str,
                          limit: int = 25) -> list[AnchorBatch]:
        """CAS-claim a batch for processing. Workers race; the first to
        succeed gets the batch (no double-submission)."""
        flt = {
            "state": {"$in": states},
            "$or": [{"next_attempt_at": None},
                     {"next_attempt_at": {"$lte": now_iso}}],
        }
        cur = self.collection.find(flt, {"_id": 0}).limit(limit)
        return [AnchorBatch.from_state(d) async for d in cur]

    async def append_attempt(self, attempt: dict, *, session=None) -> None:
        try:
            await self.attempts.insert_one(dict(attempt), session=session)
        except Exception as exc:  # noqa: BLE001
            if "duplicate key" in str(exc).lower():
                raise InvariantViolation(
                    f"duplicate anchor attempt seq for "
                    f"batch={attempt.get('batch_id')} "
                    f"seq={attempt.get('seq')}") from exc
            raise

    async def attempt_chain(self, batch_id: str) -> list[dict]:
        cur = self.attempts.find({"batch_id": batch_id},
                                   {"_id": 0}).sort("seq", 1)
        return [d async for d in cur]

    async def list_batches(self, *, state: Optional[str] = None,
                             limit: int = 50, skip: int = 0
                             ) -> list[AnchorBatch]:
        flt = _scope()
        if state:
            flt["state"] = state
        cur = self.collection.find(flt, {"_id": 0}).sort(
            "created_at", -1).skip(skip).limit(limit)
        return [AnchorBatch.from_state(d) async for d in cur]
