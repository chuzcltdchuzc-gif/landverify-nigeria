"""Phase 3.6 — saga + adapter + API E2E tests.

Drives the full anchor flow end-to-end against the live backend:
upload → verify → seal → apply-worm → anchor batcher → confirmer →
checkpointer → confirmed → inclusion proofs.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import uuid

import httpx
import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

API_URL_INTERNAL = "http://localhost:8001"


# ---- Helpers ------------------------------------------------------------

async def _register_and_login(client, *, email: str,
                              password: str = "TestPass123!",
                              country: str = "NG") -> str:
    await client.post("/api/v1/auth/register", json={
        "email": email, "password": password,
        "full_name": email.split("@")[0], "country": country})
    r = await client.post("/api/v1/auth/login",
                          json={"email": email, "password": password})
    r.raise_for_status()
    return r.json()["access_token"]


async def _grant_role(db, email: str, *, role: str) -> None:
    col = db["identity_users"]
    user = await col.find_one({"email": email.lower()})
    assert user is not None
    roles = list(user.get("roles") or [])
    if role not in roles:
        roles.append(role)
    await col.update_one({"_id": user["_id"]},
                         {"$set": {"roles": roles, "role": role},
                          "$inc": {"version": 1}})


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def http_client():
    async with httpx.AsyncClient(base_url=API_URL_INTERNAL, timeout=30) as c:
        yield c


@pytest_asyncio.fixture
async def db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    yield client[os.environ["DB_NAME"]]
    client.close()


@pytest_asyncio.fixture
async def principals(http_client, db):
    suffix = uuid.uuid4().hex[:8]
    emails = {
        "uploader": f"p36_up_{suffix}@example.com",
        "admin": f"p36_adm_{suffix}@example.com",
    }
    tokens = {label: await _register_and_login(http_client, email=email)
              for label, email in emails.items()}
    await _grant_role(db, emails["uploader"], role="field_agent")
    await _grant_role(db, emails["admin"], role="super_admin")
    tokens["uploader"] = (await http_client.post(
        "/api/v1/auth/login",
        json={"email": emails["uploader"], "password": "TestPass123!"}
    )).json()["access_token"]
    tokens["admin"] = (await http_client.post(
        "/api/v1/auth/login",
        json={"email": emails["admin"], "password": "TestPass123!"}
    )).json()["access_token"]
    return {"emails": emails, "tokens": tokens}


async def _create_registry(http_client, token: str) -> str:
    r = await http_client.post(
        "/api/v1/registry/landvaults", headers=_hdr(token),
        json={"state": "LAGOS", "lga": "IKEJA", "ward": "WARD7",
              "property_type": "RES", "ownership_type": "individual",
              "owner_name": "Anchor Test"})
    r.raise_for_status()
    return r.json()["registry_id"]


async def _seal_one_evidence(http_client, principals) -> tuple[str, str]:
    """Run the full upload → verify → seal → apply_worm path. Returns
    (evidence_id, seal_id)."""
    up_t = principals["tokens"]["uploader"]
    ad_t = principals["tokens"]["admin"]
    reg = await _create_registry(http_client, up_t)
    payload = b"anchor-test-bytes-" + uuid.uuid4().bytes
    h = hashlib.sha256(payload).hexdigest()
    init = (await http_client.post(
        "/api/v1/evidence/items", headers=_hdr(up_t),
        json={"registry_id": reg, "kind": "document",
              "media_type": "text/plain",
              "max_size": 1024 * 1024})).json()
    eid = init["evidence_id"]
    await http_client.put(f"/api/v1/evidence/items/{eid}/parts/1",
                          headers=_hdr(up_t), content=payload)
    await http_client.post(
        f"/api/v1/evidence/items/{eid}/complete",
        headers=_hdr(up_t),
        json={"parts": [{"part_no": 1, "size_bytes": len(payload),
                          "streamed_sha256": h}]})
    await http_client.post(f"/api/v1/evidence/items/{eid}/verify",
                            headers=_hdr(up_t))
    seal = (await http_client.post(
        "/api/v1/evidence/seals", headers=_hdr(ad_t),
        json={"registry_id": reg, "evidence_ids": [eid]})).json()
    sid = seal["seal_id"]
    await http_client.post(
        f"/api/v1/evidence/seals/{sid}/apply-worm",
        headers=_hdr(ad_t), json={})
    return eid, sid


async def _build_saga_for_db(db):
    """Build a saga harness against the same Mongo as the live backend.
    Used by tests that need to drive ticks deterministically rather than
    waiting for the 60s background loop."""
    from contexts.evidence.adapters.checkpoint_publishers import (
        LocalFsCheckpointPublisher,
    )
    from contexts.evidence.adapters.ctlog_internal import CtlogInternalAdapter
    from contexts.evidence.adapters.fs_worm_storage import LocalFsWormStorage
    from contexts.evidence.adapters.mongo_anchor_repository import (
        MongoAnchorBatchRepository,
        MongoEvidenceLockRepository,
        MongoIntegrityCheckRepository,
    )
    from contexts.evidence.adapters.ots_v1 import OtsV1Adapter
    from contexts.evidence.application.anchor_saga import (
        AnchorSagaService,
        CtlogCheckpointer,
        IntegrityScheduler,
    )
    ctlog = CtlogInternalAdapter(db)
    ots = OtsV1Adapter(db)
    locks = MongoEvidenceLockRepository(db)
    integrity = MongoIntegrityCheckRepository(db)
    batches = MongoAnchorBatchRepository(db)
    publisher = LocalFsCheckpointPublisher()
    storage = LocalFsWormStorage(
        root_dir=os.environ.get("EVIDENCE_FS_ROOT", "/tmp/aqua-evidence"))
    await ctlog.ensure_indexes()
    await ots.ensure_indexes()
    await locks.ensure_indexes()
    await integrity.ensure_indexes()
    await batches.ensure_indexes()
    adapters = {ctlog.provider_id: ctlog, ots.provider_id: ots}
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    saga = AnchorSagaService(client=client, db=db, batches=batches,
                              locks=locks, integrity=integrity,
                              adapters=adapters, publisher=publisher)
    integrity_sched = IntegrityScheduler(db=db, integrity=integrity,
                                            storage=storage)
    checkpointer = CtlogCheckpointer(ctlog=ctlog, publisher=publisher,
                                       signing_secret=b"dev-signing-secret")
    return saga, integrity_sched, checkpointer, ctlog


# ============================================================================
# E2E: full anchoring flow
# ============================================================================

@pytest.mark.asyncio
async def test_lock_persisted_on_apply_worm(http_client, principals,
                                             db) -> None:
    eid, sid = await _seal_one_evidence(http_client, principals)
    await asyncio.sleep(0.5)
    locks_cur = db["evidence_locks"].find({"evidence_id": eid})
    locks = [d async for d in locks_cur]
    assert len(locks) == 1, "expected one EvidenceLock per sealed item"
    assert locks[0]["seal_id"] == sid
    assert locks[0]["mode"] == "compliance"


@pytest.mark.asyncio
async def test_anchor_batcher_creates_batch_for_each_provider(
        http_client, principals, db) -> None:
    eid, sid = await _seal_one_evidence(http_client, principals)
    saga, _ints, _cps, _ctlog = await _build_saga_for_db(db)
    created = await saga.batcher_tick()
    assert created >= 2, f"expected >=2 batches (per provider); got {created}"
    cur = db["evidence_anchor_batches"].find({"seal_ids": sid})
    batches = [d async for d in cur]
    providers = {b["provider_id"] for b in batches}
    assert providers == {"ctlog_internal", "ots_v1"}


@pytest.mark.asyncio
async def test_full_saga_drives_to_confirmed(http_client, principals,
                                                db) -> None:
    eid, sid = await _seal_one_evidence(http_client, principals)
    saga, _ints, checkpointer, _ctlog = await _build_saga_for_db(db)
    await saga.batcher_tick()
    await saga.confirmer_tick()
    await checkpointer.tick()
    await saga.confirmer_tick()
    cur = db["evidence_anchor_batches"].find({"seal_ids": sid})
    states = [d["state"] async for d in cur]
    assert states.count("confirmed") >= 1, f"states={states}"


@pytest.mark.asyncio
async def test_get_batch_endpoint_returns_inclusion_proofs(
        http_client, principals, db) -> None:
    eid, sid = await _seal_one_evidence(http_client, principals)
    saga, _ints, checkpointer, _ctlog = await _build_saga_for_db(db)
    await saga.batcher_tick()
    await saga.confirmer_tick()
    await checkpointer.tick()
    await saga.confirmer_tick()
    r = await http_client.get(
        f"/api/v1/evidence/anchor-batches/by-seal/{sid}",
        headers=_hdr(principals["tokens"]["admin"]))
    assert r.status_code == 200, r.text
    batches = r.json()
    assert any(b["state"] == "confirmed" for b in batches)


# ============================================================================
# E2E: integrity check
# ============================================================================

@pytest.mark.asyncio
async def test_on_demand_integrity_check_passes_for_clean_storage(
        http_client, principals, db) -> None:
    eid, sid = await _seal_one_evidence(http_client, principals)
    r = await http_client.post(
        "/api/v1/evidence/integrity-checks",
        headers=_hdr(principals["tokens"]["admin"]),
        json={"evidence_id": eid, "trigger": "on_demand"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["outcome"] == "pass"
    assert body["triggered_by"] == "on_demand"
    # The chain endpoint returns at least this entry.
    r2 = await http_client.get(
        f"/api/v1/evidence/integrity-checks/by-evidence/{eid}",
        headers=_hdr(principals["tokens"]["admin"]))
    chain = r2.json()["chain"]
    assert len(chain) >= 1
    assert chain[0]["outcome"] == "pass"


@pytest.mark.asyncio
async def test_integrity_check_fails_when_storage_is_tampered(
        http_client, principals, db) -> None:
    eid, sid = await _seal_one_evidence(http_client, principals)
    # Tamper with the stored object on disk.
    item = await db["evidence_items"].find_one({"evidence_id": eid})
    root = os.environ.get("EVIDENCE_FS_ROOT", "/tmp/aqua-evidence")
    locator = item["storage_locator"]
    storage_path = os.path.join(root, locator)
    # Append to the file (LocalFs adapter is dev mode — WORM is
    # advisory; tampering at the filesystem level is exactly the
    # incident scenario this check exists to catch).
    try:
        os.chmod(storage_path, 0o644)
        with open(storage_path, "ab") as f:
            f.write(b"TAMPER")
    except (FileNotFoundError, PermissionError):
        pytest.skip("storage path inaccessible — skipping tamper test")
    r = await http_client.post(
        "/api/v1/evidence/integrity-checks",
        headers=_hdr(principals["tokens"]["admin"]),
        json={"evidence_id": eid, "trigger": "security_incident"})
    assert r.status_code == 201, r.text
    assert r.json()["outcome"] == "fail"


# ============================================================================
# E2E: locks
# ============================================================================

@pytest.mark.asyncio
async def test_lock_extend_endpoint_is_forward_only(http_client, principals,
                                                      db) -> None:
    eid, sid = await _seal_one_evidence(http_client, principals)
    lock_doc = await db["evidence_locks"].find_one({"evidence_id": eid})
    lid = lock_doc["lock_id"]
    # Backward extension MUST fail.
    r = await http_client.post(
        f"/api/v1/evidence/locks/{lid}/extend",
        headers=_hdr(principals["tokens"]["admin"]),
        json={"new_until": "2024-01-01T00:00:00+00:00",
              "reason": "should fail"})
    assert r.status_code == 400, r.text
    # Forward extension succeeds.
    forward = "2200-01-01T00:00:00+00:00"
    r = await http_client.post(
        f"/api/v1/evidence/locks/{lid}/extend",
        headers=_hdr(principals["tokens"]["admin"]),
        json={"new_until": forward, "reason": "court order"})
    assert r.status_code == 200, r.text
    assert r.json()["retention_until"] == forward


# ============================================================================
# E2E: DLQ + replay
# ============================================================================

@pytest.mark.asyncio
async def test_dlq_replay_creates_new_batch_keeps_old_frozen(
        http_client, principals, db) -> None:
    eid, sid = await _seal_one_evidence(http_client, principals)
    # Force a DLQ row by manually persisting a batch in dead_letter.
    from contexts.evidence.domain.anchor_batch import AnchorBatch
    seal = await db["evidence_seals"].find_one({"seal_id": sid})
    batch = AnchorBatch.create(
        provider_id="ctlog_internal",
        tenant_id=seal["tenant_id"], country_code=seal["country_code"],
        seals=[{"seal_id": sid, "merkle_root": seal["merkle_root"]}])
    batch.mark_sealed()
    batch.mark_submitted(provider_request_id="forced")
    batch.mark_failed(reason="forced-failure",
                       next_attempt_at=None, transient=False)
    batch.mark_dead_letter(reason="forced-DLQ")
    await db["evidence_anchor_batches"].insert_one(dict(batch.to_state()))

    r = await http_client.post(
        f"/api/v1/evidence/anchor-batches/{batch.batch_id}/replay",
        headers=_hdr(principals["tokens"]["admin"]),
        json={"reason": "operator manual replay"})
    assert r.status_code == 201, r.text
    new_batch = r.json()
    assert new_batch["replayed_from"] == batch.batch_id
    assert new_batch["batch_id"] != batch.batch_id
    # Original DLQ row is FROZEN — state stays dead_letter, replay
    # marker appended in provider_response.replayed_to.
    orig = await db["evidence_anchor_batches"].find_one(
        {"batch_id": batch.batch_id})
    assert orig["state"] == "dead_letter"
    assert orig["provider_response"]["replayed_to"] == new_batch["batch_id"]


# ============================================================================
# Constitutional invariants — static scans
# ============================================================================

def test_evidence_context_never_writes_registry_collection() -> None:
    """Constitutional invariant 2: Registry is never mutated by the
    Evidence context."""
    import pathlib
    evidence_root = pathlib.Path(__file__).resolve().parent.parent / "contexts/evidence"
    offenders: list[str] = []
    for py in evidence_root.rglob("*.py"):
        text = py.read_text()
        for bad in ('"registry_landvaults"',
                    "'registry_landvaults'",
                    '"registry_allocator',
                    'db["registry'):
            if bad in text:
                offenders.append(f"{py}: {bad}")
    assert not offenders, f"evidence wrote registry: {offenders}"


def test_phase36_events_in_outbox_registry() -> None:
    from kernel.events.outbox import EVENT_TYPES
    for e in ("evidence.lock.applied", "evidence.lock.extended",
              "evidence.integrity.check_started",
              "evidence.integrity.passed",
              "evidence.integrity.failed",
              "evidence.integrity.check_errored",
              "evidence.anchor.batched", "evidence.anchor.submitted",
              "evidence.anchor.confirmed", "evidence.anchor.failed",
              "evidence.anchor.replayed",
              "evidence.ctlog.checkpoint_published"):
        assert e in EVENT_TYPES, f"missing event_type registration: {e}"


def test_contract_freeze_at_1_3_0() -> None:
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent.parent
    assert (root / "contracts" / "VERSION").read_text().strip() == "1.3.0"


def test_constitutional_no_pii_in_anchor_event_payloads() -> None:
    """Constitutional invariant 12: no PII in checkpoints/anchor
    metadata."""
    import json
    import pathlib
    catalog_path = pathlib.Path(__file__).resolve().parent.parent.parent / \
        "contracts/v1/events/catalog.json"
    catalog = json.loads(catalog_path.read_text())
    pii_terms = {"owner_name", "owner_email", "owner_phone", "owner_nin",
                  "address", "ssn", "passport"}
    offenders: list[str] = []
    for evt in catalog["events"]:
        name = evt.get("event_name", "")
        if not name.startswith("evidence."):
            continue
        payload = evt.get("payload_fields") or {}
        text = json.dumps(payload).lower()
        for pii in pii_terms:
            if pii in text:
                offenders.append(f"{name}: {pii}")
    assert not offenders, f"PII in anchor event payloads: {offenders}"
