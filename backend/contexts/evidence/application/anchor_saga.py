"""Phase 3.6 Anchoring Saga + Integrity Scheduler + CT-log Checkpointer.

This module orchestrates the AnchorPort + CheckpointPublisherPort
adapters into the full saga defined by ADR-0008. Three concurrent
loops run in the background:

1. ``anchor_batcher_tick()`` — scoops WORM-applied seals that have no
   anchor batch for one of the configured providers, builds Merkle
   batches (auto-splits at 256 — §15 Decision 5), persists them in
   ``pending_batch`` and immediately transitions to ``sealed`` via the
   aggregate.
2. ``anchor_confirmer_tick()`` — claims batches in ``sealed`` /
   ``failed`` (with ``next_attempt_at`` due) and in ``submitted`` /
   ``confirming`` for re-poll. Runs ``request_anchor`` → ``submitted``,
   ``poll_confirmation`` → ``confirming`` or ``confirmed``.
3. ``integrity_scheduler_tick()`` — runs the 30-day baseline re-hash
   for sealed items (§15 Decision 4 baseline). Mandatory triggers are
   driven event-by-event from subscribers (separate code path).
4. ``ctlog_checkpointer_tick()`` — daily-cadence publisher of signed
   tree heads via the CheckpointPublisherPort.

All loops are idempotent and crash-safe.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from contexts.evidence.adapters.checkpoint_publishers import (
    LocalFsCheckpointPublisher,
    build_publisher_from_env,
)
from contexts.evidence.adapters.ctlog_internal import (
    CtlogInternalAdapter,
)
from contexts.evidence.adapters.mongo_anchor_repository import (
    EVIDENCE_ANCHOR_BATCHES_COLLECTION,
    MongoAnchorBatchRepository,
    MongoEvidenceLockRepository,
    MongoIntegrityCheckRepository,
)
from contexts.evidence.adapters.ots_v1 import OtsV1Adapter
from contexts.evidence.domain.anchor_batch import (
    AnchorBatch,
    AnchorProvider,
    BatchState,
    new_attempt_id,
    new_batch_id,
)
from contexts.evidence.domain.chain import compute_entry_hash
from contexts.evidence.domain.evidence_lock import EvidenceLock
from contexts.evidence.domain.integrity_check import (
    EvidenceIntegrityCheck,
    IntegrityTrigger,
)
from contexts.evidence.domain.value_objects import now_iso
from contexts.evidence.ports.anchor import (
    AnchorPort,
    AnchorRequest,
    AnchorState,
)
from contexts.evidence.ports.checkpoint_publisher import (
    CheckpointPublisherPort,
    TreeHead,
)
from kernel.audit import audit
from kernel.events.outbox import publish
from kernel.persistence.context import ExecutionContext, set_context, reset_context

logger = logging.getLogger("evidence.anchor_saga")


# ---- Configuration ------------------------------------------------------

def _env_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    try:
        return int(val) if val is not None else default
    except ValueError:
        return default


def _env_backoff() -> list[int]:
    csv = os.environ.get("EVIDENCE_ANCHOR_BACKOFF_SECONDS",
                         "10,60,300,3600,21600,86400")
    return [int(x.strip()) for x in csv.split(",") if x.strip()]


MAX_BATCH_SIZE = _env_int("EVIDENCE_ANCHOR_MAX_BATCH_SIZE", 256)
MAX_ATTEMPTS = _env_int("EVIDENCE_ANCHOR_MAX_ATTEMPTS", 12)
BATCHER_INTERVAL_S = _env_int("EVIDENCE_ANCHOR_BATCHER_INTERVAL_SECONDS", 60)
CONFIRMER_INTERVAL_S = _env_int("EVIDENCE_ANCHOR_CONFIRMER_INTERVAL_SECONDS", 30)
INTEGRITY_INTERVAL_DAYS = _env_int("EVIDENCE_INTEGRITY_CHECK_INTERVAL_DAYS", 30)
CHECKPOINTER_INTERVAL_S = _env_int(
    "EVIDENCE_CTLOG_CHECKPOINTER_INTERVAL_SECONDS", 86400)


def _next_attempt_at(attempts_done: int) -> Optional[str]:
    backoff = _env_backoff()
    if attempts_done >= MAX_ATTEMPTS:
        return None
    idx = min(attempts_done, len(backoff) - 1)
    return (datetime.now(timezone.utc) +
            timedelta(seconds=backoff[idx])).isoformat()


# ---- System ExecutionContext (worker principal) -------------------------

def _system_ctx() -> ExecutionContext:
    return ExecutionContext(principal_id="system.anchor_saga",
                            roles=("super_admin",),
                            tenant_id=None, country=None)


# ---- Saga Service -------------------------------------------------------

@dataclass
class AnchorSagaService:
    """Drives the AnchorBatch FSM. Stateless across calls — every method
    re-reads the aggregate, mutates, persists, fans out events."""

    client: AsyncIOMotorClient
    db: AsyncIOMotorDatabase
    batches: MongoAnchorBatchRepository
    locks: MongoEvidenceLockRepository
    integrity: MongoIntegrityCheckRepository
    adapters: dict[str, AnchorPort]
    publisher: CheckpointPublisherPort

    # ---- Helpers --------------------------------------------------------

    async def _publish_events(self, agg) -> None:
        for evt in agg.pull_events():
            env = evt.to_envelope(tenant_id=getattr(agg, "tenant_id", None),
                                    country=getattr(agg, "country_code", None),
                                    actor="system.anchor_saga")
            await publish(env)
            await audit(action=evt.event_type,
                         resource_type=evt.aggregate_type.lower(),
                         resource_id=evt.aggregate_id,
                         decision="EXECUTED",
                         payload={"version": evt.aggregate_version})

    async def _append_attempt(self, batch_id: str, *, outcome: str,
                                error_summary: Optional[str] = None,
                                provider_response_snapshot: Optional[dict] = None
                                ) -> None:
        prior = await self.batches.attempt_chain(batch_id)
        seq = len(prior)
        prev_hash = prior[-1]["entry_hash"] if prior else None
        payload = {
            "attempt_id": new_attempt_id(),
            "batch_id": batch_id, "attempt_no": seq + 1,
            "started_at": now_iso(), "completed_at": now_iso(),
            "outcome": outcome,
            "error_summary": error_summary,
            "provider_response_snapshot": provider_response_snapshot,
            "seq": seq,
        }
        entry_hash = compute_entry_hash(prev_hash, payload)
        await self.batches.append_attempt({
            **payload, "prev_hash": prev_hash, "entry_hash": entry_hash})

    # ---- Batcher --------------------------------------------------------

    async def batcher_tick(self) -> int:
        """Scoop sealed + WORM-applied Seals not yet anchored by each
        provider, build batches. Returns count of batches created."""
        token = set_context(_system_ctx())
        try:
            seals_coll = self.db["evidence_seals"]
            providers = [p.value for p in AnchorProvider]
            total = 0
            for provider_id in providers:
                anchored_for_provider = {sid for batch in
                                            await self._batches_for_provider(provider_id)
                                            for sid in batch.seal_ids}
                # Select seals where status is worm_applied AND not in
                # any existing batch for this provider.
                cur = seals_coll.find(
                    {"status": "worm_applied",
                      "seal_id": {"$nin": list(anchored_for_provider)}},
                    {"_id": 0, "seal_id": 1, "tenant_id": 1,
                     "country_code": 1, "merkle_root": 1}
                ).limit(MAX_BATCH_SIZE * 4)
                buckets: dict[tuple[str, str], list[dict]] = {}
                async for seal_doc in cur:
                    key = (seal_doc["tenant_id"], seal_doc["country_code"])
                    buckets.setdefault(key, []).append({
                        "seal_id": seal_doc["seal_id"],
                        "merkle_root": seal_doc["merkle_root"],
                    })
                for (tenant_id, country_code), seals in buckets.items():
                    # Auto-split at MAX_BATCH_SIZE.
                    for chunk_idx in range(0, len(seals), MAX_BATCH_SIZE):
                        chunk = seals[chunk_idx:chunk_idx + MAX_BATCH_SIZE]
                        try:
                            batch = AnchorBatch.create(
                                provider_id=provider_id,
                                tenant_id=tenant_id,
                                country_code=country_code,
                                seals=chunk)
                            await self.batches.add(batch)
                            batch.mark_sealed()
                            await self.batches.replace(
                                batch, expected_version=batch.version - 1,
                                expected_state=BatchState.PENDING_BATCH.value)
                            await self._publish_events(batch)
                            total += 1
                        except Exception:  # noqa: BLE001
                            logger.exception("batcher: failed to create batch")
            return total
        finally:
            reset_context(token)

    async def _batches_for_provider(self, provider_id: str
                                       ) -> list[AnchorBatch]:
        flt = {"provider_id": provider_id}
        cur = self.db[EVIDENCE_ANCHOR_BATCHES_COLLECTION].find(
            flt, {"_id": 0})
        return [AnchorBatch.from_state(d) async for d in cur]

    # ---- Confirmer ------------------------------------------------------

    async def confirmer_tick(self) -> int:
        """Process due batches: submit → confirm → DLQ on max attempts."""
        token = set_context(_system_ctx())
        try:
            now = now_iso()
            due = await self.batches.claim_due(
                states=[BatchState.SEALED.value,
                         BatchState.SUBMITTED.value,
                         BatchState.CONFIRMING.value,
                         BatchState.FAILED.value],
                now_iso=now, limit=25)
            processed = 0
            for batch in due:
                try:
                    await self._advance_batch(batch)
                    processed += 1
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "confirmer: failed to advance batch %s", batch.batch_id)
            return processed
        finally:
            reset_context(token)

    async def _advance_batch(self, batch: AnchorBatch) -> None:
        adapter = self.adapters.get(batch.provider_id)
        if adapter is None:
            logger.error("no adapter for provider %s", batch.provider_id)
            return
        if batch.state == BatchState.SEALED.value or (
            batch.state == BatchState.FAILED.value and batch.attempts < MAX_ATTEMPTS
        ):
            # Submit (idempotent over (batch_id, root))
            try:
                req = await adapter.request_anchor(batch_id=batch.batch_id,
                                                      root=batch.merkle_root)
                prev_v = batch.version
                batch.mark_submitted(provider_request_id=req.provider_request_id,
                                      provider_response={"submitted_at": req.submitted_at,
                                                          **req.extra})
                await self.batches.replace(batch, expected_version=prev_v)
                await self._publish_events(batch)
                await self._append_attempt(batch.batch_id, outcome="submitted")
                # Immediately transition to confirming for the same tick.
                prev_v = batch.version
                batch.mark_confirming()
                await self.batches.replace(batch, expected_version=prev_v)
                await self._publish_events(batch)
            except Exception as exc:  # noqa: BLE001
                await self._handle_failure(batch, exc, "submit_failed")
                return
        if batch.state in (BatchState.SUBMITTED.value,
                            BatchState.CONFIRMING.value):
            # Poll for confirmation.
            if not batch.provider_request_id:
                await self._handle_failure(batch,
                                              RuntimeError("missing provider_request_id"),
                                              "missing_request_id")
                return
            req = AnchorRequest(provider_id=batch.provider_id,
                                  batch_id=batch.batch_id,
                                  root=batch.merkle_root,
                                  provider_request_id=batch.provider_request_id,
                                  submitted_at=batch.last_attempt_at or now_iso())
            try:
                result = await adapter.poll_confirmation(req)
            except Exception as exc:  # noqa: BLE001
                await self._handle_failure(batch, exc, "poll_failed")
                return
            if result.state == AnchorState.CONFIRMED.value:
                # Materialize per-seal inclusion proofs.
                proofs: dict[str, dict] = {}
                for leaf in batch.seal_leaves:
                    try:
                        ip = await adapter.fetch_inclusion_proof(
                            req, leaf["merkle_root"])
                        proofs[leaf["seal_id"]] = {
                            "leaf_hash": ip.leaf_hash,
                            "proof_blob": ip.proof_blob,
                            "checkpoint_ref": ip.checkpoint_ref,
                        }
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("inclusion proof failed for %s",
                                          leaf["seal_id"])
                        proofs[leaf["seal_id"]] = {
                            "leaf_hash": leaf["merkle_root"],
                            "proof_blob": {"error": str(exc)},
                            "checkpoint_ref": None,
                        }
                prev_v = batch.version
                batch.mark_confirmed(inclusion_proofs=proofs,
                                       provider_response=result.provider_response)
                await self.batches.replace(batch, expected_version=prev_v)
                await self._publish_events(batch)
                await self._append_attempt(
                    batch.batch_id, outcome="confirmed",
                    provider_response_snapshot=result.provider_response)
            elif result.state == AnchorState.PENDING.value:
                # Stay in confirming, schedule next poll.
                await self.db[EVIDENCE_ANCHOR_BATCHES_COLLECTION].update_one(
                    {"batch_id": batch.batch_id,
                     "state": BatchState.CONFIRMING.value},
                    {"$set": {"next_attempt_at":
                                 _next_attempt_at(batch.attempts)}})
                await self._append_attempt(batch.batch_id, outcome="pending",
                                              error_summary=result.detail)
            elif result.state == AnchorState.FAILED_PERMANENT.value:
                await self._handle_failure(batch,
                                              RuntimeError(result.detail or "permanent"),
                                              "permanent_failure",
                                              transient=False)
            else:
                await self._handle_failure(batch,
                                              RuntimeError(result.detail or "transient"),
                                              "transient_failure")

    async def _handle_failure(self, batch: AnchorBatch, exc: Exception,
                                reason: str, *,
                                transient: bool = True) -> None:
        prev_v = batch.version
        try:
            if (not transient) or (batch.attempts >= MAX_ATTEMPTS):
                batch.mark_dead_letter(reason=f"{reason}: {exc}")
            else:
                batch.mark_failed(reason=f"{reason}: {exc}",
                                    next_attempt_at=_next_attempt_at(batch.attempts),
                                    transient=transient)
            await self.batches.replace(batch, expected_version=prev_v)
            await self._publish_events(batch)
            await self._append_attempt(
                batch.batch_id,
                outcome=("failed_permanent" if not transient
                          else "failed_transient"),
                error_summary=str(exc))
        except Exception:  # noqa: BLE001
            logger.exception("handle_failure: secondary failure on batch %s",
                              batch.batch_id)

    # ---- Replay (DLQ → new batch) ---------------------------------------

    async def replay(self, *, batch_id: str) -> AnchorBatch:
        """Spawn a new AnchorBatch from a DLQ row. Original DLQ row stays
        frozen — only a write-once ``replayed_to`` marker is appended."""
        token = set_context(_system_ctx())
        try:
            orig = await self.batches.get(batch_id)
            if orig is None:
                raise ValueError(f"batch {batch_id} not found")
            if orig.state != BatchState.DEAD_LETTER.value:
                raise ValueError(
                    f"replay requires DEAD_LETTER; current={orig.state}")
            seals = [{"seal_id": leaf["seal_id"],
                       "merkle_root": leaf["merkle_root"]}
                      for leaf in orig.seal_leaves]
            new_batch = AnchorBatch.create(
                provider_id=orig.provider_id, tenant_id=orig.tenant_id,
                country_code=orig.country_code, seals=seals,
                replayed_from=orig.batch_id,
                batch_id=new_batch_id())
            await self.batches.add(new_batch)
            new_batch.mark_sealed()
            await self.batches.replace(
                new_batch, expected_version=new_batch.version - 1,
                expected_state=BatchState.PENDING_BATCH.value)
            await self._publish_events(new_batch)
            # Append the replay marker to the original.
            orig.mark_replay_initiated(new_batch_id=new_batch.batch_id)
            await self.batches.replace(orig,
                                          expected_version=orig.version - 1)
            await self._publish_events(orig)
            return new_batch
        finally:
            reset_context(token)


# ---- Integrity scheduler ------------------------------------------------

@dataclass
class IntegrityScheduler:
    db: AsyncIOMotorDatabase
    integrity: MongoIntegrityCheckRepository
    storage: object  # StoragePort
    seals_collection_name: str = "evidence_seals"
    items_collection_name: str = "evidence_items"

    async def tick(self) -> int:
        """Find sealed items whose last integrity check is older than the
        baseline interval (or none) and run a `scheduled` check."""
        token = set_context(_system_ctx())
        try:
            cutoff = (datetime.now(timezone.utc) -
                      timedelta(days=INTEGRITY_INTERVAL_DAYS)).isoformat()
            items = self.db[self.items_collection_name].find(
                {"status": {"$in": ["sealed"]}, "server_hash": {"$ne": None}},
                {"_id": 0, "evidence_id": 1, "tenant_id": 1,
                 "country_code": 1, "server_hash": 1, "storage_locator": 1}
            ).limit(50)
            scheduled = 0
            async for item in items:
                head = await self.integrity.head_for_evidence(item["evidence_id"])
                if head and head.started_at > cutoff:
                    continue
                try:
                    await self.run_check_for_item(item,
                                                     trigger=IntegrityTrigger.SCHEDULED.value)
                    scheduled += 1
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "integrity scheduler failed for %s",
                        item.get("evidence_id"))
            return scheduled
        finally:
            reset_context(token)

    async def run_check_for_item(self, item: dict, *, trigger: str,
                                    principal: Optional[str] = None
                                    ) -> EvidenceIntegrityCheck:
        head = await self.integrity.head_for_evidence(item["evidence_id"])
        seq = (head.seq + 1) if head else 0
        prev_hash = head.entry_hash if head else None
        check = EvidenceIntegrityCheck.start(
            evidence_id=item["evidence_id"],
            tenant_id=item["tenant_id"],
            country_code=item["country_code"],
            triggered_by=trigger,
            triggered_by_principal=principal,
            expected_hash=item["server_hash"],
            seq=seq, prev_hash=prev_hash)
        await self.integrity.add(check)
        # Stream + hash the storage object.
        from contexts.evidence.ports.storage import StorageObjectKey, StorageTier
        try:
            parts = item["storage_locator"].split("/")
            key = StorageObjectKey(
                tier=StorageTier(parts[0]), tenant_id=parts[1],
                yyyy=parts[2], mm=parts[3], dd=parts[4],
                evidence_id=parts[5], suffix=parts[6])
            h = hashlib.sha256()
            async for chunk in self.storage.open_for_streaming_hash(key):
                h.update(chunk)
            observed = h.hexdigest()
        except Exception as exc:  # noqa: BLE001
            check.record_error(error_summary=str(exc))
            await self.integrity.replace(check)
            for evt in check.pull_events():
                env = evt.to_envelope(tenant_id=check.tenant_id,
                                        country=check.country_code,
                                        actor="system.integrity")
                await publish(env)
            return check
        if observed == item["server_hash"]:
            check.record_pass(observed_hash=observed)
        else:
            check.record_fail(observed_hash=observed,
                                 reason="hash drift detected")
        await self.integrity.replace(check)
        for evt in check.pull_events():
            env = evt.to_envelope(tenant_id=check.tenant_id,
                                    country=check.country_code,
                                    actor="system.integrity")
            await publish(env)
        return check


# ---- CT-log checkpointer ------------------------------------------------

@dataclass
class CtlogCheckpointer:
    ctlog: CtlogInternalAdapter
    publisher: CheckpointPublisherPort
    signing_key_id: str = "ctlog-v1"
    signing_secret: bytes = b""  # populated from env on startup

    async def tick(self) -> Optional[str]:
        """Publish a new signed tree head if the tree has grown since the
        last checkpoint."""
        token = set_context(_system_ctx())
        try:
            head = await self.ctlog.current_tree_head()
            if not head:
                return None
            latest = await self.ctlog.latest_checkpoint()
            if latest and latest["tree_size"] >= head["tree_size"]:
                return None
            next_head_seq = (latest["head_seq"] + 1) if latest else 1
            head_obj = TreeHead(head_seq=next_head_seq,
                                  tree_size=head["tree_size"],
                                  root_hash=head["root_hash"],
                                  timestamp=now_iso(),
                                  publisher_id=self.ctlog.provider_id)
            # Sign the canonical head JSON with HMAC-SHA256 over the
            # signing secret. Production deploys swap this for the
            # platform's JWKS private key — but the API contract is
            # identical (base64 signature + kid).
            payload_bytes = json.dumps(head_obj.to_dict(), sort_keys=True,
                                         separators=(",", ":"),
                                         ensure_ascii=False).encode("utf-8")
            import hmac
            sig = hmac.new(self.signing_secret or b"dev-signing-secret",
                            payload_bytes, hashlib.sha256).digest()
            signature_b64 = base64.b64encode(sig).decode("ascii")
            try:
                ref = await self.publisher.publish_checkpoint(
                    head=head_obj, signature=signature_b64,
                    signature_kid=self.signing_key_id)
            except Exception:  # noqa: BLE001
                logger.exception("checkpoint publisher failed")
                # Still record the checkpoint locally — publisher
                # failure is non-fatal for the saga.
                ref = None
            await self.ctlog.record_checkpoint(
                head_seq=head_obj.head_seq, tree_size=head_obj.tree_size,
                root_hash=head_obj.root_hash, signature=signature_b64,
                signature_kid=self.signing_key_id,
                locator=ref.locator if ref else None)
            # Emit event.
            from kernel.events.envelope import new_envelope
            env = new_envelope(
                event_type="evidence.ctlog.checkpoint_published",
                event_version=1, aggregate_type="CtlogTree",
                aggregate_id=f"ctlog:{head_obj.head_seq}",
                aggregate_version=head_obj.head_seq,
                payload={"head_seq": head_obj.head_seq,
                         "tree_size": head_obj.tree_size,
                         "root_hash": head_obj.root_hash,
                         "signature_kid": self.signing_key_id,
                         "locator": ref.locator if ref else None},
                producer="evidence",
                tenant_id=None, country=None, actor="system.checkpointer")
            await publish(env)
            await audit(action="evidence.ctlog.checkpoint_published",
                         resource_type="ctlog", resource_id=str(head_obj.head_seq),
                         decision="EXECUTED",
                         payload={"tree_size": head_obj.tree_size})
            return ref.locator if ref else f"local:{head_obj.head_seq}"
        finally:
            reset_context(token)


# ---- Loop bootstrap -----------------------------------------------------

_loops_task: Optional[asyncio.Task] = None
_loops_stop: Optional[asyncio.Event] = None


async def _saga_loop(saga: AnchorSagaService,
                      integrity: IntegrityScheduler,
                      checkpointer: CtlogCheckpointer,
                      stop: asyncio.Event) -> None:
    logger.info("Phase 3.6 anchor saga loop started "
                "(batcher=%ss confirmer=%ss integrity=%dd checkpointer=%ss)",
                BATCHER_INTERVAL_S, CONFIRMER_INTERVAL_S,
                INTEGRITY_INTERVAL_DAYS, CHECKPOINTER_INTERVAL_S)
    last_batch = 0.0
    last_integrity = 0.0
    last_checkpoint = 0.0
    while not stop.is_set():
        now = asyncio.get_event_loop().time()
        try:
            await saga.confirmer_tick()
        except Exception:  # noqa: BLE001
            logger.exception("confirmer tick crashed")
        if now - last_batch >= BATCHER_INTERVAL_S:
            try:
                await saga.batcher_tick()
            except Exception:  # noqa: BLE001
                logger.exception("batcher tick crashed")
            last_batch = now
        if now - last_checkpoint >= CHECKPOINTER_INTERVAL_S:
            try:
                await checkpointer.tick()
            except Exception:  # noqa: BLE001
                logger.exception("checkpointer tick crashed")
            last_checkpoint = now
        if now - last_integrity >= INTEGRITY_INTERVAL_DAYS * 86400:
            try:
                await integrity.tick()
            except Exception:  # noqa: BLE001
                logger.exception("integrity tick crashed")
            last_integrity = now
        try:
            await asyncio.wait_for(stop.wait(),
                                     timeout=CONFIRMER_INTERVAL_S)
        except asyncio.TimeoutError:
            pass
    logger.info("Phase 3.6 anchor saga loop stopped.")


async def start_anchor_saga(saga: AnchorSagaService,
                              integrity: IntegrityScheduler,
                              checkpointer: CtlogCheckpointer) -> None:
    global _loops_task, _loops_stop
    if _loops_task and not _loops_task.done():
        return
    _loops_stop = asyncio.Event()
    _loops_task = asyncio.create_task(
        _saga_loop(saga, integrity, checkpointer, _loops_stop))


async def stop_anchor_saga() -> None:
    global _loops_task, _loops_stop
    if _loops_stop:
        _loops_stop.set()
    if _loops_task:
        try:
            await asyncio.wait_for(_loops_task, timeout=5)
        except asyncio.TimeoutError:
            _loops_task.cancel()
    _loops_task = None
    _loops_stop = None
