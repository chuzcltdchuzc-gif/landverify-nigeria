"""Phase 3.6 router — anchor + lock + integrity + ct-log endpoints.

Mounted under ``/api/v1/evidence`` (router prefix matches the Phase
3.4/3.5 router so we share the OpenAPI tag).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Path, Query, status

from contexts.evidence.adapters.ctlog_internal import CtlogInternalAdapter
from contexts.evidence.adapters.mongo_anchor_repository import (
    MongoAnchorBatchRepository,
    MongoEvidenceLockRepository,
    MongoIntegrityCheckRepository,
)
from contexts.evidence.api.anchor_dtos import (
    AnchorBatchResponse,
    CtlogCheckpointResponse,
    EvidenceLockListResponse,
    EvidenceLockResponse,
    ExtendLockRetentionRequest,
    IntegrityChainResponse,
    IntegrityCheckResponse,
    InclusionProofBundleResponse,
    ReplayAnchorBatchRequest,
    TriggerIntegrityCheckRequest,
)
from contexts.evidence.application.anchor_saga import (
    AnchorSagaService,
    IntegrityScheduler,
)
from contexts.evidence.domain.value_objects import now_iso
from kernel.authorization.pep import enforce, require_auth
from kernel.errors.problem import bad_request, not_found
from kernel.persistence.context import ExecutionContext, current_context

router = APIRouter(prefix="/v1/evidence", tags=["evidence-anchoring"])

_saga: Optional[AnchorSagaService] = None
_locks: Optional[MongoEvidenceLockRepository] = None
_integrity: Optional[MongoIntegrityCheckRepository] = None
_anchor: Optional[MongoAnchorBatchRepository] = None
_integrity_scheduler: Optional[IntegrityScheduler] = None
_ctlog: Optional[CtlogInternalAdapter] = None


def configure_router(*, saga: AnchorSagaService,
                     locks: MongoEvidenceLockRepository,
                     integrity: MongoIntegrityCheckRepository,
                     anchor: MongoAnchorBatchRepository,
                     integrity_scheduler: IntegrityScheduler,
                     ctlog: CtlogInternalAdapter) -> None:
    global _saga, _locks, _integrity, _anchor, _integrity_scheduler, _ctlog
    _saga = saga
    _locks = locks
    _integrity = integrity
    _anchor = anchor
    _integrity_scheduler = integrity_scheduler
    _ctlog = ctlog


def _need(obj, name):
    if obj is None:
        raise RuntimeError(f"{name} not configured")
    return obj


# ---- Anchor batches -----------------------------------------------------

@router.get("/anchor-batches/{batch_id}", response_model=AnchorBatchResponse)
async def get_batch(batch_id: str,
                     _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("evidence.anchor.batch.read",
                  resource={"resource_type": "anchor_batch",
                            "resource_id": batch_id})
    batch = await _need(_anchor, "anchor").get(batch_id)
    if not batch:
        raise not_found(f"AnchorBatch {batch_id} not found",
                         code="evidence.anchor.not_found")
    return batch.to_state()


@router.get("/anchor-batches/by-seal/{seal_id}",
             response_model=list[AnchorBatchResponse])
async def get_batches_by_seal(seal_id: str,
                               _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("evidence.anchor.batch.read",
                  resource={"resource_type": "anchor_batch_set"})
    batches = await _need(_anchor, "anchor").list_by_seal(seal_id)
    return [b.to_state() for b in batches]


@router.get("/anchor-batches", response_model=list[AnchorBatchResponse])
async def list_batches(state: Optional[str] = Query(default=None),
                        limit: int = Query(default=50, ge=1, le=200),
                        skip: int = Query(default=0, ge=0),
                        _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("evidence.anchor.batch.read",
                  resource={"resource_type": "anchor_batch_set"})
    batches = await _need(_anchor, "anchor").list_batches(
        state=state, limit=limit, skip=skip)
    return [b.to_state() for b in batches]


@router.post("/anchor-batches/{batch_id}/replay",
              response_model=AnchorBatchResponse,
              status_code=status.HTTP_201_CREATED)
async def replay_batch(batch_id: str, payload: ReplayAnchorBatchRequest,
                        _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("evidence.anchor.batch.replay_dlq",
                  resource={"resource_type": "anchor_batch",
                            "resource_id": batch_id})
    try:
        new_batch = await _need(_saga, "saga").replay(batch_id=batch_id)
    except ValueError as exc:
        raise bad_request(str(exc), code="evidence.anchor.replay_rejected")
    return new_batch.to_state()


# ---- Locks --------------------------------------------------------------

@router.get("/locks/{lock_id}", response_model=EvidenceLockResponse)
async def get_lock(lock_id: str,
                    _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("evidence.lock.read",
                  resource={"resource_type": "evidence_lock",
                            "resource_id": lock_id})
    lock = await _need(_locks, "locks").get(lock_id)
    if not lock:
        raise not_found(f"EvidenceLock {lock_id} not found",
                         code="evidence.lock.not_found")
    return lock.to_state()


@router.get("/locks/by-evidence/{evidence_id}",
             response_model=EvidenceLockListResponse)
async def list_locks_for_evidence(evidence_id: str,
                                    _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("evidence.lock.read",
                  resource={"resource_type": "evidence_lock_set"})
    items = await _need(_locks, "locks").list_for_evidence(evidence_id)
    return {"locks": [lock.to_state() for lock in items]}


@router.post("/locks/{lock_id}/extend", response_model=EvidenceLockResponse)
async def extend_lock(lock_id: str, payload: ExtendLockRetentionRequest,
                       _ctx: ExecutionContext = Depends(require_auth)):
    ctx = current_context()
    await enforce("evidence.lock.extend",
                  resource={"resource_type": "evidence_lock",
                            "resource_id": lock_id})
    lock = await _need(_locks, "locks").get(lock_id)
    if not lock:
        raise not_found(f"EvidenceLock {lock_id} not found",
                         code="evidence.lock.not_found")
    prev_v = lock.version
    try:
        lock.extend_retention(new_until=payload.new_until,
                               by=ctx.principal_id,
                               reason=payload.reason)
    except Exception as exc:  # noqa: BLE001
        raise bad_request(str(exc), code="evidence.lock.invalid_extension")
    updated = await _need(_locks, "locks").replace(
        lock, expected_version=prev_v)
    # Fan out events.
    from kernel.events.outbox import publish
    for evt in lock.pull_events():
        env = evt.to_envelope(tenant_id=lock.tenant_id,
                                country=lock.country_code,
                                actor=ctx.principal_id)
        await publish(env)
    return updated.to_state()


# ---- Integrity ----------------------------------------------------------

@router.post("/integrity-checks", response_model=IntegrityCheckResponse,
              status_code=status.HTTP_201_CREATED)
async def trigger_integrity_check(payload: TriggerIntegrityCheckRequest,
                                     _ctx: ExecutionContext = Depends(require_auth)):
    ctx = current_context()
    await enforce("evidence.integrity.trigger",
                  resource={"resource_type": "integrity_check",
                            "resource_id": payload.evidence_id})
    sched = _need(_integrity_scheduler, "integrity_scheduler")
    items = sched.db[sched.items_collection_name]
    item = await items.find_one({"evidence_id": payload.evidence_id},
                                  {"_id": 0, "evidence_id": 1,
                                    "tenant_id": 1, "country_code": 1,
                                    "server_hash": 1, "storage_locator": 1,
                                    "status": 1})
    if not item:
        raise not_found(f"evidence {payload.evidence_id} not found",
                         code="evidence.not_found")
    if not item.get("server_hash"):
        raise bad_request("evidence has no server_hash yet — verify first",
                            code="evidence.integrity.no_hash")
    check = await sched.run_check_for_item(
        item, trigger=payload.trigger.value, principal=ctx.principal_id)
    return check.to_state()


@router.get("/integrity-checks/{check_id}",
             response_model=IntegrityCheckResponse)
async def get_integrity_check(check_id: str,
                                _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("evidence.integrity.read",
                  resource={"resource_type": "integrity_check",
                            "resource_id": check_id})
    check = await _need(_integrity, "integrity").get(check_id)
    if not check:
        raise not_found(f"check {check_id} not found",
                         code="evidence.integrity.not_found")
    return check.to_state()


@router.get("/integrity-checks/by-evidence/{evidence_id}",
             response_model=IntegrityChainResponse)
async def get_integrity_chain(evidence_id: str,
                                _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("evidence.integrity.read",
                  resource={"resource_type": "integrity_check_set",
                            "resource_id": evidence_id})
    chain = await _need(_integrity, "integrity").chain_for_evidence(evidence_id)
    return {"evidence_id": evidence_id,
            "chain": [c.to_state() for c in chain]}


# ---- CT-log -------------------------------------------------------------

@router.get("/ctlog/checkpoints/latest",
             response_model=CtlogCheckpointResponse)
async def latest_checkpoint(_ctx: ExecutionContext = Depends(require_auth)):
    await enforce("evidence.ctlog.checkpoint.read",
                  resource={"resource_type": "ctlog_checkpoint"})
    doc = await _need(_ctlog, "ctlog").latest_checkpoint()
    if not doc:
        raise not_found("no checkpoint published yet",
                         code="evidence.ctlog.no_checkpoint")
    return doc
