"""Phase 3.3 — Media Remediation Saga.

Migrates inline base64/binary blobs from legacy Mongo documents into
private WORM storage. Implements the operator's binding sequence:

    Verify (source readable + hashable)
        → Copy (StoragePort multipart with running hash)
        → Verify (independent read-back + re-hash; must match)
        → Cutover (record provenance, null the inline source)

Invariants (binding):

* The source bytes are **never** deleted before reverification succeeds.
* Every successful migration writes a provenance row to
  `evidence_remediated_media` with `legacy_collection`, `legacy_doc_id`,
  `legacy_field`, `server_hash`, `storage_key`, `import_batch`,
  `recorded_at`, `recorded_by`.
* Failed migrations are durably recorded in
  `evidence_remediation_orphans` with the failure state + reason; they
  do NOT clear the inline source.
* The saga state lives in `evidence_media_remediation_sagas` and is
  resumable: a crash mid-saga can be replayed from the last persisted
  transition.
* Idempotent: re-running on the same legacy (collection, doc_id, field)
  is a no-op when the document was already cut over.

Design constraints:

* `MediaRemediationSaga` depends ONLY on the StoragePort and Mongo
  primitives. The Evidence aggregate is not touched at Phase 3.3 — its
  link to remediated media lands at Phase 3.4 (where the EvidenceItem
  aggregate is introduced and the saga's `recorded_evidence_id` field
  becomes the foreign key).
* No data deletion from legacy collections — the inline binary is
  REPLACED with a reference dict (`{remediated: true, server_hash,
  storage_key}`) so callers can still find the bytes.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncIterator, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from contexts.evidence.adapters.fs_worm_storage import LocalFsWormStorage
from contexts.evidence.ports.storage import (
    StorageObjectKey,
    StoragePort,
    StorageTier,
    canonical_key,
)

logger = logging.getLogger("evidence.media_remediation")

SAGAS_COLLECTION = "evidence_media_remediation_sagas"
PROVENANCE_COLLECTION = "evidence_remediated_media"
ORPHANS_COLLECTION = "evidence_remediation_orphans"


class SagaState(str, Enum):
    REQUESTED = "requested"
    SRC_VERIFIED = "src_verified"
    COPYING = "copying"
    COPIED = "copied"
    REVERIFIED = "reverified"
    CUTOVER_COMMITTED = "cutover_committed"
    REVERIFICATION_FAILED = "reverification_failed"
    SOURCE_UNREADABLE = "source_unreadable"
    ORPHANED = "orphaned"


TERMINAL_STATES = {
    SagaState.CUTOVER_COMMITTED.value,
    SagaState.ORPHANED.value,
}


@dataclass(frozen=True)
class MediaSource:
    """Pointer to a legacy inline binary that needs to be remediated."""
    legacy_collection: str
    legacy_doc_id: str
    legacy_field: str
    tenant_id: str
    country: str
    media_type: str = "application/octet-stream"
    registry_id: Optional[str] = None  # set when known (e.g. parcels rows)


@dataclass
class MediaRemediationReport:
    scanned: int = 0
    migrated: int = 0
    already_done: int = 0
    orphaned: int = 0
    skipped_no_inline: int = 0


# ---- Helpers --------------------------------------------------------------

def _extract_inline_bytes(value: Any) -> Optional[bytes]:
    """Return the bytes inside a legacy inline field, or None.

    Supported shapes:
      * `bytes` — already-decoded inline bytes
      * `str` with the `data:<mime>;base64,<payload>` prefix
      * `str` that is a bare base64 payload (≥ 32 chars)
      * `dict` of the form `{base64: "..."}` (legacy convention)
    """
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("data:") and ";base64," in s:
            s = s.split(";base64,", 1)[1]
        if len(s) >= 32:
            try:
                pad = "=" * (-len(s) % 4)
                return base64.b64decode(s + pad, validate=False)
            except Exception:
                return None
        return None
    if isinstance(value, dict) and "base64" in value:
        try:
            raw = value["base64"]
            pad = "=" * (-len(raw) % 4)
            return base64.b64decode(raw + pad, validate=False)
        except Exception:
            return None
    return None


def _saga_id() -> str:
    return "mrs_" + uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- Saga -----------------------------------------------------------------

class MediaRemediationSaga:
    """Resumable saga orchestrator.

    The saga is a thin coordinator: every state transition is persisted
    to `evidence_media_remediation_sagas` before proceeding. A crash
    after any transition leaves the saga in a recoverable state.
    """

    def __init__(self, *, db: AsyncIOMotorDatabase, storage: StoragePort,
                  actor: str = "media_remediation_worker") -> None:
        self._db = db
        self._storage = storage
        self._actor = actor

    async def ensure_indexes(self) -> None:
        await self._db[SAGAS_COLLECTION].create_index("saga_id", unique=True)
        await self._db[SAGAS_COLLECTION].create_index(
            [("source.legacy_collection", 1),
             ("source.legacy_doc_id", 1),
             ("source.legacy_field", 1)],
            name="idx_mrs_source")
        await self._db[SAGAS_COLLECTION].create_index("state")
        await self._db[PROVENANCE_COLLECTION].create_index(
            [("legacy_collection", 1),
             ("legacy_doc_id", 1),
             ("legacy_field", 1)],
            unique=True, name="idx_provenance_unique_source")
        await self._db[PROVENANCE_COLLECTION].create_index("server_hash")
        await self._db[PROVENANCE_COLLECTION].create_index("storage_key")
        await self._db[ORPHANS_COLLECTION].create_index(
            [("legacy_collection", 1),
             ("legacy_doc_id", 1),
             ("legacy_field", 1)],
            name="idx_orphans_source")
        await self._db[ORPHANS_COLLECTION].create_index("state")

    # ---- public entry points -----------------------------------------

    async def remediate_one(self, *, source: MediaSource,
                            import_batch: str = "manual",
                            commit: bool = True) -> dict:
        """Run the full saga for one inline-media source. Idempotent."""
        # Idempotency: already cut over?
        prev = await self._db[PROVENANCE_COLLECTION].find_one({
            "legacy_collection": source.legacy_collection,
            "legacy_doc_id": source.legacy_doc_id,
            "legacy_field": source.legacy_field,
        })
        if prev:
            return {"state": "already_done",
                    "storage_key": prev["storage_key"],
                    "server_hash": prev["server_hash"]}

        saga = await self._open_saga(source=source, import_batch=import_batch)

        try:
            payload = await self._verify_source(saga=saga, source=source)
            if payload is None:
                return await self._mark_orphaned(
                    saga=saga, source=source,
                    state=SagaState.SOURCE_UNREADABLE,
                    reason="legacy field has no readable inline bytes")
            await self._transition(saga, SagaState.SRC_VERIFIED,
                                    {"source_size": len(payload),
                                     "source_hash": hashlib.sha256(payload).hexdigest()})

            if not commit:
                # Dry-run — leave saga at SRC_VERIFIED for inspection.
                return {"state": "dry_run",
                        "would_size": len(payload),
                        "would_hash": hashlib.sha256(payload).hexdigest()}

            stored = await self._copy(saga=saga, source=source, payload=payload)
            await self._transition(saga, SagaState.COPIED,
                                    {"storage_key": stored.key.as_str(),
                                     "streamed_hash": stored.streamed_sha256})

            independent_hash = await self._reverify(stored.key)
            if independent_hash != stored.streamed_sha256:
                return await self._mark_orphaned(
                    saga=saga, source=source,
                    state=SagaState.REVERIFICATION_FAILED,
                    reason=(f"reverify hash {independent_hash!r} != "
                            f"streamed hash {stored.streamed_sha256!r}"))
            await self._transition(saga, SagaState.REVERIFIED,
                                    {"independent_hash": independent_hash})

            await self._cutover(saga=saga, source=source,
                                 server_hash=independent_hash,
                                 storage_key=stored.key,
                                 import_batch=import_batch)
            return {"state": SagaState.CUTOVER_COMMITTED.value,
                    "saga_id": saga["saga_id"],
                    "storage_key": stored.key.as_str(),
                    "server_hash": independent_hash}
        except Exception as exc:  # noqa: BLE001
            await self._mark_orphaned(
                saga=saga, source=source, state=SagaState.ORPHANED,
                reason=f"unexpected: {type(exc).__name__}: {exc}")
            raise

    async def scan_collection(self, *, collection: str, field: str,
                              tenant_field: str = "tenant_id",
                              country_field: str = "country",
                              registry_id_field: Optional[str] = None,
                              import_batch: str = "manual",
                              commit: bool = True,
                              limit: Optional[int] = None
                              ) -> MediaRemediationReport:
        """Scan a legacy collection and remediate every doc whose `field`
        carries an inline base64/binary blob."""
        report = MediaRemediationReport()
        cur = self._db[collection].find({field: {"$exists": True}})
        if limit:
            cur = cur.limit(limit)
        async for doc in cur:
            report.scanned += 1
            payload = _extract_inline_bytes(doc.get(field))
            if payload is None:
                report.skipped_no_inline += 1
                continue
            src = MediaSource(
                legacy_collection=collection,
                legacy_doc_id=str(doc.get("id") or doc.get("_id")),
                legacy_field=field,
                tenant_id=doc.get(tenant_field) or "default",
                country=doc.get(country_field) or "NG",
                media_type=str(doc.get("media_type")
                                or doc.get("content_type")
                                or "application/octet-stream"),
                registry_id=doc.get(registry_id_field) if registry_id_field else None,
            )
            result = await self.remediate_one(source=src,
                                                import_batch=import_batch,
                                                commit=commit)
            if result["state"] == "already_done":
                report.already_done += 1
            elif result["state"] == SagaState.CUTOVER_COMMITTED.value:
                report.migrated += 1
            elif result["state"] in {SagaState.REVERIFICATION_FAILED.value,
                                      SagaState.SOURCE_UNREADABLE.value,
                                      SagaState.ORPHANED.value}:
                report.orphaned += 1
        return report

    async def resume_pending(self) -> int:
        """Resume any saga not in a terminal state. Returns count resumed."""
        count = 0
        cur = self._db[SAGAS_COLLECTION].find(
            {"state": {"$nin": list(TERMINAL_STATES)}})
        async for saga in cur:
            source = MediaSource(**saga["source"])
            try:
                await self.remediate_one(source=source,
                                          import_batch=saga.get("import_batch", "resume"),
                                          commit=True)
                count += 1
            except Exception:
                logger.exception("resume_pending: saga %s failed", saga["saga_id"])
        return count

    # ---- saga state ---------------------------------------------------

    async def _open_saga(self, *, source: MediaSource, import_batch: str
                          ) -> dict:
        # Resume if a previous saga exists.
        existing = await self._db[SAGAS_COLLECTION].find_one({
            "source.legacy_collection": source.legacy_collection,
            "source.legacy_doc_id": source.legacy_doc_id,
            "source.legacy_field": source.legacy_field,
            "state": {"$nin": list(TERMINAL_STATES)},
        })
        if existing:
            return existing
        saga = {
            "saga_id": _saga_id(),
            "state": SagaState.REQUESTED.value,
            "source": source.__dict__,
            "import_batch": import_batch,
            "actor": self._actor,
            "history": [{"state": SagaState.REQUESTED.value,
                          "at": _now_iso(), "actor": self._actor}],
            "created_at": _now_iso(),
        }
        await self._db[SAGAS_COLLECTION].insert_one(dict(saga))
        return saga

    async def _transition(self, saga: dict, state: SagaState,
                          extra: Optional[dict] = None) -> None:
        entry = {"state": state.value, "at": _now_iso(),
                 "actor": self._actor}
        if extra:
            entry.update(extra)
        saga["state"] = state.value
        saga.setdefault("history", []).append(entry)
        await self._db[SAGAS_COLLECTION].update_one(
            {"saga_id": saga["saga_id"]},
            {"$set": {"state": state.value},
             "$push": {"history": entry}},
        )

    # ---- saga steps ---------------------------------------------------

    async def _verify_source(self, *, saga: dict,
                              source: MediaSource) -> Optional[bytes]:
        doc = await self._db[source.legacy_collection].find_one(
            {"id": source.legacy_doc_id})
        if doc is None:
            # Try by _id as a fallback for collections that don't carry
            # an `id` field separately.
            from bson import ObjectId
            try:
                doc = await self._db[source.legacy_collection].find_one(
                    {"_id": ObjectId(source.legacy_doc_id)})
            except Exception:
                doc = None
        if doc is None:
            return None
        return _extract_inline_bytes(doc.get(source.legacy_field))

    async def _copy(self, *, saga: dict, source: MediaSource, payload: bytes):
        """Stream `payload` into private storage via the StoragePort."""
        await self._transition(saga, SagaState.COPYING)
        # Mint a stable "evidence_id-shaped" key. The Phase 3.4 aggregate
        # will adopt this key as its `object_ref`; until then the key is
        # the canonical handle used by the provenance row.
        evd_id = "evd_" + uuid.uuid4().hex
        key = canonical_key(tier=StorageTier.PRIVATE,
                             tenant_id=source.tenant_id,
                             evidence_id=evd_id, suffix="final")
        handle = await self._storage.initiate_multipart(
            key=key, media_type=source.media_type, max_size=max(len(payload), 1))

        async def _stream():
            chunk = 1024 * 256
            for i in range(0, len(payload), chunk):
                yield payload[i:i + chunk]

        receipt = await self._storage.upload_part(
            handle, part_no=1, stream=_stream())
        stored = await self._storage.complete_multipart(
            handle, parts=[receipt])
        return stored

    async def _reverify(self, key: StorageObjectKey) -> str:
        """Independent read-back pass per ADR-0004."""
        h = hashlib.sha256()
        async for chunk in self._storage.open_for_streaming_hash(key):
            h.update(chunk)
        return h.hexdigest()

    async def _cutover(self, *, saga: dict, source: MediaSource,
                       server_hash: str, storage_key: StorageObjectKey,
                       import_batch: str) -> None:
        # 1) Write provenance row (unique index forbids double-import).
        await self._db[PROVENANCE_COLLECTION].insert_one({
            "provenance_id": "rmp_" + uuid.uuid4().hex,
            "legacy_collection": source.legacy_collection,
            "legacy_doc_id": source.legacy_doc_id,
            "legacy_field": source.legacy_field,
            "tenant_id": source.tenant_id,
            "country": source.country,
            "registry_id": source.registry_id,
            "storage_key": storage_key.as_str(),
            "storage_provider": self._storage.provider_id,
            "media_type": source.media_type,
            "server_hash": server_hash,
            "hash_algorithm": "SHA-256",
            "import_batch": import_batch,
            "recorded_at": _now_iso(),
            "recorded_by": self._actor,
            "saga_id": saga["saga_id"],
        })
        # 2) Replace the inline source with a reference dict (NEVER delete
        #    the document). The reference points to the canonical storage
        #    key + server hash so legacy readers can still find the bytes.
        await self._db[source.legacy_collection].update_one(
            {"id": source.legacy_doc_id},
            {"$set": {source.legacy_field: {
                "remediated": True,
                "storage_key": storage_key.as_str(),
                "server_hash": server_hash,
                "remediated_at": _now_iso(),
            }}},
        )
        # 3) Finalize saga state.
        await self._transition(saga, SagaState.CUTOVER_COMMITTED,
                                {"server_hash": server_hash,
                                 "storage_key": storage_key.as_str()})

    async def _mark_orphaned(self, *, saga: dict, source: MediaSource,
                              state: SagaState, reason: str) -> dict:
        await self._transition(saga, state, {"reason": reason})
        await self._db[ORPHANS_COLLECTION].update_one(
            {"legacy_collection": source.legacy_collection,
             "legacy_doc_id": source.legacy_doc_id,
             "legacy_field": source.legacy_field},
            {"$set": {
                "saga_id": saga["saga_id"],
                "state": state.value, "reason": reason,
                "tenant_id": source.tenant_id, "country": source.country,
                "recorded_at": _now_iso(),
            }},
            upsert=True,
        )
        # Also mark the saga itself as terminal-orphan (so resume_pending
        # doesn't keep picking it up). REVERIFICATION_FAILED is already a
        # terminal-ish state but we make it explicit.
        if state != SagaState.ORPHANED:
            await self._transition(saga, SagaState.ORPHANED,
                                    {"prior_state": state.value})
        return {"state": SagaState.ORPHANED.value,
                "saga_id": saga["saga_id"],
                "reason": reason,
                "prior_state": state.value}
