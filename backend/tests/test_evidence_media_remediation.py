"""Phase 3.3 — Media Remediation acceptance tests.

Maps 1:1 to the operator directives §3.3:

* Idempotent Verify → Copy → Verify → Cutover saga
* Source bytes are NEVER deleted before reverification succeeds
* Every migrated object retains provenance metadata
* Migration is reversible until final verification completes (the
  inline source is only nulled at cutover, after reverify success)
* Failed migrations enter the orphan-remediation queue
* All remediation actions are fully auditable
"""
from __future__ import annotations

import base64
import hashlib
import os
import tempfile
import uuid

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from contexts.evidence.adapters.fs_worm_storage import LocalFsWormStorage
from contexts.evidence.application.media_remediation import (
    ORPHANS_COLLECTION,
    PROVENANCE_COLLECTION,
    SAGAS_COLLECTION,
    MediaRemediationSaga,
    MediaSource,
    SagaState,
)


@pytest_asyncio.fixture
async def harness():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db_name = os.environ["DB_NAME"] + "_mrem_" + uuid.uuid4().hex[:6]
    db = client[db_name]
    with tempfile.TemporaryDirectory() as tmp:
        storage = LocalFsWormStorage(root_dir=tmp)
        saga = MediaRemediationSaga(db=db, storage=storage, actor="usr_test")
        await saga.ensure_indexes()
        yield saga, db, storage
    await client.drop_database(db_name)
    client.close()


def _seed_legacy(db, *, collection: str, doc_id: str, field: str,
                  payload: bytes, tenant: str = "t1", country: str = "NG"):
    return db[collection].insert_one({
        "id": doc_id,
        field: base64.b64encode(payload).decode("ascii"),
        "tenant_id": tenant, "country": country,
        "content_type": "image/png",
    })


# ---- Happy path ---------------------------------------------------------

@pytest.mark.asyncio
async def test_happy_path_verify_copy_reverify_cutover(harness) -> None:
    saga, db, _ = harness
    payload = os.urandom(64 * 1024)
    expected = hashlib.sha256(payload).hexdigest()
    await _seed_legacy(db, collection="parcels", doc_id="lp_001",
                        field="boundary_image", payload=payload)

    src = MediaSource(legacy_collection="parcels", legacy_doc_id="lp_001",
                       legacy_field="boundary_image",
                       tenant_id="t1", country="NG",
                       media_type="image/png")
    result = await saga.remediate_one(source=src, import_batch="happy-1")

    assert result["state"] == SagaState.CUTOVER_COMMITTED.value
    assert result["server_hash"] == expected
    # Provenance row exists with the expected fields
    prov = await db[PROVENANCE_COLLECTION].find_one({
        "legacy_collection": "parcels", "legacy_doc_id": "lp_001",
        "legacy_field": "boundary_image",
    })
    assert prov is not None
    assert prov["server_hash"] == expected
    assert prov["storage_provider"] == "local_fs_worm"
    assert prov["recorded_by"] == "usr_test"
    # Inline source replaced by a reference dict, NEVER deleted entirely
    doc = await db["parcels"].find_one({"id": "lp_001"})
    assert isinstance(doc["boundary_image"], dict)
    assert doc["boundary_image"]["remediated"] is True
    assert doc["boundary_image"]["server_hash"] == expected
    assert doc["boundary_image"]["storage_key"] == prov["storage_key"]


# ---- Idempotency --------------------------------------------------------

@pytest.mark.asyncio
async def test_running_twice_is_a_noop(harness) -> None:
    saga, db, _ = harness
    payload = b"hello world" * 1024
    await _seed_legacy(db, collection="evidence_vault", doc_id="ev_001",
                        field="file_b64", payload=payload)
    src = MediaSource(legacy_collection="evidence_vault",
                       legacy_doc_id="ev_001",
                       legacy_field="file_b64",
                       tenant_id="t1", country="NG")
    r1 = await saga.remediate_one(source=src, import_batch="idem-1")
    r2 = await saga.remediate_one(source=src, import_batch="idem-2")
    assert r1["state"] == SagaState.CUTOVER_COMMITTED.value
    assert r2["state"] == "already_done"
    assert r2["server_hash"] == r1["server_hash"]
    # Provenance row remains exactly one
    count = await db[PROVENANCE_COLLECTION].count_documents({
        "legacy_collection": "evidence_vault", "legacy_doc_id": "ev_001",
        "legacy_field": "file_b64",
    })
    assert count == 1


# ---- Dry-run leaves source intact --------------------------------------

@pytest.mark.asyncio
async def test_dry_run_does_not_touch_source(harness) -> None:
    saga, db, _ = harness
    payload = os.urandom(2048)
    await _seed_legacy(db, collection="parcels", doc_id="lp_dry",
                        field="boundary_image", payload=payload)
    src = MediaSource(legacy_collection="parcels", legacy_doc_id="lp_dry",
                       legacy_field="boundary_image",
                       tenant_id="t1", country="NG")
    r = await saga.remediate_one(source=src, import_batch="dry",
                                   commit=False)
    assert r["state"] == "dry_run"
    # Source still inline base64
    doc = await db["parcels"].find_one({"id": "lp_dry"})
    assert isinstance(doc["boundary_image"], str)
    # No provenance row, no orphan row
    assert await db[PROVENANCE_COLLECTION].count_documents({}) == 0
    assert await db[ORPHANS_COLLECTION].count_documents({}) == 0


# ---- Source unreadable → orphan ---------------------------------------

@pytest.mark.asyncio
async def test_missing_inline_field_is_orphaned(harness) -> None:
    saga, db, _ = harness
    await db["parcels"].insert_one({"id": "lp_no_media", "tenant_id": "t1",
                                      "country": "NG"})
    src = MediaSource(legacy_collection="parcels",
                       legacy_doc_id="lp_no_media",
                       legacy_field="boundary_image",
                       tenant_id="t1", country="NG")
    r = await saga.remediate_one(source=src, import_batch="orphan-1")
    assert r["state"] == SagaState.ORPHANED.value
    assert r["prior_state"] == SagaState.SOURCE_UNREADABLE.value
    # Orphan row recorded
    orph = await db[ORPHANS_COLLECTION].find_one({
        "legacy_collection": "parcels", "legacy_doc_id": "lp_no_media"})
    assert orph is not None
    assert orph["state"] == SagaState.SOURCE_UNREADABLE.value
    # Source untouched
    doc = await db["parcels"].find_one({"id": "lp_no_media"})
    assert "boundary_image" not in doc or doc.get("boundary_image") is None


# ---- Reverify mismatch → orphan, source intact -------------------------

@pytest.mark.asyncio
async def test_reverify_mismatch_keeps_source_intact(harness, monkeypatch) -> None:
    """Inject a fault: the read-back pass returns DIFFERENT bytes than
    were written. Source must remain intact; orphan row recorded."""
    saga, db, storage = harness
    payload = b"verify-me" * 4096
    await _seed_legacy(db, collection="parcels", doc_id="lp_mismatch",
                        field="boundary_image", payload=payload)
    src = MediaSource(legacy_collection="parcels",
                       legacy_doc_id="lp_mismatch",
                       legacy_field="boundary_image",
                       tenant_id="t1", country="NG")

    # Monkey-patch the storage adapter's read-back to yield corrupted bytes.
    async def _corrupt(key):  # pragma: no cover - exercised by saga
        yield b"corrupted bytes"

    monkeypatch.setattr(storage, "open_for_streaming_hash", _corrupt)
    r = await saga.remediate_one(source=src, import_batch="mismatch-1")
    assert r["state"] == SagaState.ORPHANED.value
    assert r["prior_state"] == SagaState.REVERIFICATION_FAILED.value
    # Source MUST still be readable as base64 (the binding rule)
    doc = await db["parcels"].find_one({"id": "lp_mismatch"})
    assert isinstance(doc["boundary_image"], str)
    src_bytes = base64.b64decode(doc["boundary_image"])
    assert hashlib.sha256(src_bytes).hexdigest() == hashlib.sha256(payload).hexdigest()
    # No provenance row
    assert await db[PROVENANCE_COLLECTION].count_documents({}) == 0


# ---- Auditability: saga history is append-only ------------------------

@pytest.mark.asyncio
async def test_saga_history_records_every_transition(harness) -> None:
    saga, db, _ = harness
    payload = b"audit-trail" * 1024
    await _seed_legacy(db, collection="evidence_vault", doc_id="ev_aud",
                        field="file_b64", payload=payload)
    src = MediaSource(legacy_collection="evidence_vault",
                       legacy_doc_id="ev_aud",
                       legacy_field="file_b64",
                       tenant_id="t1", country="NG")
    await saga.remediate_one(source=src, import_batch="audit-1")
    saga_doc = await db[SAGAS_COLLECTION].find_one({
        "source.legacy_collection": "evidence_vault",
        "source.legacy_doc_id": "ev_aud",
    })
    assert saga_doc is not None
    states = [h["state"] for h in saga_doc["history"]]
    # Expected transitions in order
    assert states == [
        SagaState.REQUESTED.value,
        SagaState.SRC_VERIFIED.value,
        SagaState.COPYING.value,
        SagaState.COPIED.value,
        SagaState.REVERIFIED.value,
        SagaState.CUTOVER_COMMITTED.value,
    ]
    # Every entry carries a timestamp + actor
    for h in saga_doc["history"]:
        assert "at" in h and "actor" in h


# ---- Scan a whole legacy collection -----------------------------------

@pytest.mark.asyncio
async def test_scan_collection_processes_all_inline_fields(harness) -> None:
    saga, db, _ = harness
    for i in range(5):
        await _seed_legacy(db, collection="parcels",
                            doc_id=f"lp_scan_{i}",
                            field="boundary_image",
                            payload=os.urandom(1024))
    # Add one doc without the field (will not match the scan filter — and
    # that's correct behaviour; the scan only inspects docs that have the
    # field, which is the intended cheap-path).
    await db["parcels"].insert_one({"id": "lp_no_field", "tenant_id": "t1",
                                      "country": "NG"})
    report = await saga.scan_collection(
        collection="parcels", field="boundary_image",
        import_batch="scan-1", commit=True)
    assert report.scanned == 5
    assert report.migrated == 5
    assert report.skipped_no_inline == 0
    assert report.orphaned == 0
    assert await db[PROVENANCE_COLLECTION].count_documents({}) == 5
