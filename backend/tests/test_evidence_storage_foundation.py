"""Phase 3.1 — Storage foundation acceptance tests.

Maps 1:1 to `/app/memory/PHASE3_SPEC.md` §3.1 acceptance gate:

* Two-tier storage (public/private) — covered by canonical_key tests
* Multipart streaming upload + streamed SHA-256 (foundation for ADR-0004)
* WORM contract: cannot overwrite, cannot extend backwards, cannot use
  governance mode
* Read-back independent stream produces identical bytes to upload
* Signed URLs: TTL clamped, audit-row-before-URL invariant, role tier caps
* Remediation move never deletes the source

These tests use the LocalFs adapter (dev/test default). The R2 adapter
is intentionally stubbed and is exercised only when operator credentials
are present (Phase 3.10).
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from contexts.evidence.adapters.fs_worm_storage import (
    LocalFsWormStorage,
    WormViolationError,
)
from contexts.evidence.adapters.r2_storage import R2StorageAdapter
from contexts.evidence.adapters.signed_url_motor import (
    SIGNED_URL_AUDIT_COLLECTION,
    SignedUrlMotorAdapter,
)
from contexts.evidence.ports.storage import (
    DEFAULT_SIGNED_URL_TTL_SECONDS,
    MAX_SIGNED_URL_TTL_SECONDS,
    SignedUrlAuditCtx,
    StorageObjectKey,
    StorageTier,
    canonical_key,
    clamp_ttl,
)


# ---- Fixtures -------------------------------------------------------------

@pytest_asyncio.fixture
async def fs_storage():
    with tempfile.TemporaryDirectory() as tmp:
        yield LocalFsWormStorage(root_dir=tmp), tmp


@pytest_asyncio.fixture
async def signed_url_db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db_name = os.environ["DB_NAME"] + "_signed_url_test_" + uuid.uuid4().hex[:6]
    db = client[db_name]
    yield db
    await client.drop_database(db_name)
    client.close()


def _key(suffix: str = "final", tier: StorageTier = StorageTier.PRIVATE
          ) -> StorageObjectKey:
    return canonical_key(tier=tier, tenant_id="t_test",
                         evidence_id="evd_" + uuid.uuid4().hex[:8],
                         suffix=suffix)


async def _stream(payload: bytes, chunk: int = 1024):
    for i in range(0, len(payload), chunk):
        yield payload[i:i + chunk]


# ---- Value object invariants -------------------------------------------

def test_canonical_key_layout_is_tier_first() -> None:
    k = canonical_key(tier=StorageTier.PRIVATE, tenant_id="t1",
                       evidence_id="evd_123", suffix="final")
    parts = k.as_str().split("/")
    assert parts[0] == "private"
    assert parts[1] == "t1"
    assert parts[-2] == "evd_123"
    assert parts[-1] == "final"
    # YYYY MM DD positions
    assert len(parts[2]) == 4 and parts[2].isdigit()
    assert len(parts[3]) == 2 and parts[3].isdigit()


def test_storage_tier_is_two_valued() -> None:
    # Compile-time exhaustiveness: no third tier.
    assert {t.value for t in StorageTier} == {"public", "private"}


def test_storage_key_rejects_empties_and_invalid_dates() -> None:
    with pytest.raises(ValueError):
        StorageObjectKey(tier=StorageTier.PRIVATE, tenant_id="",
                          yyyy="2026", mm="06", dd="28",
                          evidence_id="evd", suffix="final")
    with pytest.raises(ValueError):
        StorageObjectKey(tier=StorageTier.PRIVATE, tenant_id="t",
                          yyyy="26", mm="06", dd="28",
                          evidence_id="evd", suffix="final")
    with pytest.raises(ValueError):
        StorageObjectKey(tier=StorageTier.PRIVATE, tenant_id="t",
                          yyyy="2026", mm="06", dd="28",
                          evidence_id="evd", suffix="bad/suffix")


# ---- Multipart streaming + streamed-during-write SHA-256 ---------------

@pytest.mark.asyncio
async def test_multipart_upload_streams_and_produces_canonical_hash(fs_storage) -> None:
    storage, _ = fs_storage
    payload = os.urandom(3 * 1024 * 1024)  # 3 MiB
    expected = hashlib.sha256(payload).hexdigest()

    key = _key()
    handle = await storage.initiate_multipart(
        key=key, media_type="application/pdf", max_size=10 * 1024 * 1024)
    # Two parts
    p1 = await storage.upload_part(handle, part_no=1,
                                    stream=_stream(payload[:1 * 1024 * 1024]))
    p2 = await storage.upload_part(handle, part_no=2,
                                    stream=_stream(payload[1 * 1024 * 1024:]))
    stored = await storage.complete_multipart(handle, parts=[p1, p2])
    assert stored.streamed_sha256 == expected
    assert stored.size_bytes == len(payload)


@pytest.mark.asyncio
async def test_part_size_exceeds_max_is_rejected(fs_storage) -> None:
    storage, _ = fs_storage
    key = _key()
    handle = await storage.initiate_multipart(
        key=key, media_type="application/octet-stream", max_size=1024)

    async def big():
        yield b"x" * 2048

    with pytest.raises(Exception):
        await storage.upload_part(handle, part_no=1, stream=big())


@pytest.mark.asyncio
async def test_empty_multipart_complete_is_rejected(fs_storage) -> None:
    storage, _ = fs_storage
    key = _key()
    handle = await storage.initiate_multipart(
        key=key, media_type="text/plain", max_size=1024)
    with pytest.raises(Exception):
        await storage.complete_multipart(handle, parts=[])


# ---- Independent read-back stream (ADR-0004) ---------------------------

@pytest.mark.asyncio
async def test_read_back_stream_matches_upload_byte_for_byte(fs_storage) -> None:
    storage, _ = fs_storage
    payload = b"hello evidence world " * 2048  # ~42KiB
    expected = hashlib.sha256(payload).hexdigest()
    key = _key()
    handle = await storage.initiate_multipart(
        key=key, media_type="text/plain", max_size=len(payload) + 1)
    p1 = await storage.upload_part(handle, part_no=1, stream=_stream(payload))
    await storage.complete_multipart(handle, parts=[p1])

    h = hashlib.sha256()
    async for chunk in storage.open_for_streaming_hash(key):
        h.update(chunk)
    assert h.hexdigest() == expected  # plaintext-identical read-back pass


# ---- WORM contract -----------------------------------------------------

@pytest.mark.asyncio
async def test_worm_apply_then_overwrite_is_blocked(fs_storage) -> None:
    storage, _ = fs_storage
    key = _key()
    handle = await storage.initiate_multipart(
        key=key, media_type="text/plain", max_size=1024)
    p1 = await storage.upload_part(handle, part_no=1,
                                    stream=_stream(b"original"))
    await storage.complete_multipart(handle, parts=[p1])
    await storage.apply_object_lock(
        key, retention_until=datetime.now(timezone.utc) + timedelta(days=30),
        applied_by="usr_super_admin")
    # Any attempt to re-initiate a multipart on the same key must fail.
    with pytest.raises(WormViolationError):
        await storage.initiate_multipart(
            key=key, media_type="text/plain", max_size=1024)


@pytest.mark.asyncio
async def test_worm_governance_mode_rejected(fs_storage) -> None:
    storage, _ = fs_storage
    key = _key()
    h = await storage.initiate_multipart(key=key, media_type="text/plain",
                                          max_size=10)
    r = await storage.upload_part(h, part_no=1, stream=_stream(b"x"))
    await storage.complete_multipart(h, parts=[r])
    with pytest.raises(Exception):
        await storage.apply_object_lock(
            key,
            retention_until=datetime.now(timezone.utc) + timedelta(days=1),
            mode="governance", applied_by="usr_admin")


@pytest.mark.asyncio
async def test_worm_extend_must_be_forward(fs_storage) -> None:
    storage, _ = fs_storage
    key = _key()
    h = await storage.initiate_multipart(key=key, media_type="text/plain",
                                          max_size=10)
    r = await storage.upload_part(h, part_no=1, stream=_stream(b"x"))
    await storage.complete_multipart(h, parts=[r])
    later = datetime.now(timezone.utc) + timedelta(days=10)
    await storage.apply_object_lock(
        key, retention_until=later, applied_by="usr_a")
    earlier = datetime.now(timezone.utc) + timedelta(days=5)
    with pytest.raises(Exception):
        await storage.extend_object_lock(
            key, retention_until=earlier, extended_by="usr_b")


@pytest.mark.asyncio
async def test_worm_status_reports_expired_lock_as_unlocked(fs_storage) -> None:
    storage, _ = fs_storage
    key = _key()
    h = await storage.initiate_multipart(key=key, media_type="text/plain",
                                          max_size=10)
    r = await storage.upload_part(h, part_no=1, stream=_stream(b"x"))
    await storage.complete_multipart(h, parts=[r])
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    # apply_object_lock requires a strictly forward retention; we test by
    # writing the sidecar directly to simulate expiry.
    lock_path = storage._lock_path(key)  # type: ignore[attr-defined]
    import json
    lock_path.write_text(json.dumps({
        "key": key.as_str(), "mode": "compliance",
        "retention_until": past.isoformat(),
        "applied_at": (past - timedelta(days=1)).isoformat(),
        "applied_by": "usr_test",
    }))
    status = await storage.lock_status(key)
    assert status.locked is False


# ---- Remediation move preserves source --------------------------------

@pytest.mark.asyncio
async def test_move_streams_through_verify_callback_and_keeps_source(fs_storage) -> None:
    storage, _ = fs_storage
    src = _key(suffix="final")
    dst = canonical_key(tier=StorageTier.PRIVATE, tenant_id="t_test",
                         evidence_id="evd_new", suffix="final")
    payload = os.urandom(64 * 1024)
    expected = hashlib.sha256(payload).hexdigest()
    h = await storage.initiate_multipart(key=src, media_type="application/octet-stream",
                                          max_size=len(payload) + 1)
    r = await storage.upload_part(h, part_no=1, stream=_stream(payload))
    await storage.complete_multipart(h, parts=[r])

    cb_hash = hashlib.sha256()

    async def cb(chunk: bytes) -> None:
        cb_hash.update(chunk)

    stored = await storage.move(src=src, dst=dst, verify_callback=cb)
    assert stored.streamed_sha256 == expected
    assert cb_hash.hexdigest() == expected  # callback saw every byte
    # Source MUST still be present (Phase 2A directive §10 / ADR-0006).
    src_h = hashlib.sha256()
    async for ch in storage.open_for_streaming_hash(src):
        src_h.update(ch)
    assert src_h.hexdigest() == expected


# ---- R2 adapter is port-clean (skeleton) -------------------------------

@pytest.mark.asyncio
async def test_r2_adapter_raises_not_implemented_with_clear_message() -> None:
    r2 = R2StorageAdapter(account_id="x", access_key_id="x",
                          secret_access_key="x", bucket_private="b")
    with pytest.raises(NotImplementedError) as ei:
        await r2.initiate_multipart(
            key=_key(), media_type="application/pdf", max_size=1)
    msg = str(ei.value)
    assert "R2_ACCOUNT_ID" in msg
    assert "LocalFsWormStorage" in msg


# ---- Signed URL: TTL clamps + audit-before-return ----------------------

def test_clamp_ttl_respects_role_tier_caps() -> None:
    # field_agent capped at 300; super_admin at 3600; lower bound 30
    assert clamp_ttl(10_000, role="super_admin") == MAX_SIGNED_URL_TTL_SECONDS
    assert clamp_ttl(10_000, role="field_agent") == 300
    assert clamp_ttl(5, role="super_admin") == 30  # lower clamp


@pytest.mark.asyncio
async def test_signed_url_writes_audit_before_returning(signed_url_db) -> None:
    adapter = SignedUrlMotorAdapter(
        db=signed_url_db, secret=b"x" * 32,
        base_url="http://test.local")
    await adapter.ensure_indexes()
    key = _key()
    ctx = SignedUrlAuditCtx(
        principal_id="usr_creator", principal_role="field_agent",
        tenant_id="t_test", country="NG",
        evidence_id=key.evidence_id, action="read",
        requested_ttl_seconds=DEFAULT_SIGNED_URL_TTL_SECONDS,
    )
    url = await adapter.issue(key=key,
                               ttl_seconds=DEFAULT_SIGNED_URL_TTL_SECONDS,
                               audit=ctx)
    # 1) URL is well-formed
    assert "?exp=" in url.url and "&sig=" in url.url
    assert url.url.startswith("http://test.local/api/v1/evidence/blobs/")
    # 2) Audit row exists by the time issue() returned
    found = await signed_url_db[SIGNED_URL_AUDIT_COLLECTION].find_one({
        "audit_id": url.audit_id,
    })
    assert found is not None
    assert found["url_sha256"] == url.url_sha256
    assert found["evidence_id"] == key.evidence_id
    assert found["action"] == "read"
    # 3) URL plaintext is NEVER stored
    assert "url" not in found
    # 4) url_sha256 is unique-indexed; re-issuing the SAME URL would fail.
    # (Re-issuing a different URL for the same evidence works fine —
    # tested by issuing a second one and observing a fresh audit row.)
    url2 = await adapter.issue(
        key=key, ttl_seconds=DEFAULT_SIGNED_URL_TTL_SECONDS, audit=ctx)
    assert url2.url_sha256 != url.url_sha256


@pytest.mark.asyncio
async def test_signed_url_rejects_invalid_ttl(signed_url_db) -> None:
    adapter = SignedUrlMotorAdapter(db=signed_url_db, secret=b"y" * 32,
                                     base_url="http://test.local")
    await adapter.ensure_indexes()
    key = _key()
    ctx = SignedUrlAuditCtx(
        principal_id="u", principal_role="field_agent",
        tenant_id="t", country="NG", evidence_id=key.evidence_id,
        action="read", requested_ttl_seconds=0,
    )
    with pytest.raises(Exception):
        await adapter.issue(key=key, ttl_seconds=0, audit=ctx)
    ctx2 = SignedUrlAuditCtx(
        principal_id="u", principal_role="super_admin",
        tenant_id="t", country="NG", evidence_id=key.evidence_id,
        action="read", requested_ttl_seconds=MAX_SIGNED_URL_TTL_SECONDS + 60,
    )
    with pytest.raises(Exception):
        await adapter.issue(key=key,
                             ttl_seconds=MAX_SIGNED_URL_TTL_SECONDS + 60,
                             audit=ctx2)
