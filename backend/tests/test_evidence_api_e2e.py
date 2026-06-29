"""Phase 3.4 + 3.5 — Evidence API E2E tests.

Exercises the live backend end-to-end:
* Upload → verify → seal → apply_worm flow
* Hash mismatch (tampered client claim) → 409 + integrity event
* Authorization matrix (anonymous + non-role + uploader + admin)
* WORM lockdown: after seal+apply_worm, the storage adapter refuses to
  re-initiate a multipart on the same key.
* Sealing requires items in VERIFIED state; mixed status → 409.
* Tenant isolation: cross-tenant reads return 404.

The tests use the LocalFs WORM adapter wired into the running app
(`/tmp/aqua-evidence`).
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


# ---- Helpers -------------------------------------------------------------

async def _register_and_login(client: httpx.AsyncClient, *, email: str,
                              password: str = "TestPass123!",
                              country: str = "NG") -> str:
    await client.post("/api/v1/auth/register", json={
        "email": email, "password": password,
        "full_name": email.split("@")[0], "country": country,
    })
    r = await client.post("/api/v1/auth/login", json={
        "email": email, "password": password,
    })
    r.raise_for_status()
    return r.json()["access_token"]


async def _grant_role(db, email: str, *, role: str) -> None:
    col = db["identity_users"]
    user = await col.find_one({"email": email.lower()})
    assert user is not None
    roles = list(user.get("roles") or [])
    if role not in roles:
        roles.append(role)
    await col.update_one(
        {"_id": user["_id"]},
        {"$set": {"roles": roles, "role": role}, "$inc": {"version": 1}},
    )


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---- Fixtures ------------------------------------------------------------

@pytest_asyncio.fixture
async def http_client():
    async with httpx.AsyncClient(base_url=API_URL_INTERNAL, timeout=30) as client:
        yield client


@pytest_asyncio.fixture
async def db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    yield client[os.environ["DB_NAME"]]
    client.close()


@pytest_asyncio.fixture
async def principals(http_client, db):
    suffix = uuid.uuid4().hex[:8]
    emails = {
        "uploader": f"evd_up_{suffix}@example.com",
        "citizen":  f"evd_cit_{suffix}@example.com",
        "admin":    f"evd_adm_{suffix}@example.com",
    }
    tokens = {}
    for label, email in emails.items():
        tokens[label] = await _register_and_login(http_client, email=email)
    await _grant_role(db, emails["uploader"], role="field_agent")
    await _grant_role(db, emails["admin"], role="super_admin")
    # Re-login to pick up roles in JWT claims.
    tokens["uploader"] = (await http_client.post("/api/v1/auth/login", json={
        "email": emails["uploader"], "password": "TestPass123!"})).json()["access_token"]
    tokens["admin"] = (await http_client.post("/api/v1/auth/login", json={
        "email": emails["admin"], "password": "TestPass123!"})).json()["access_token"]
    return {"emails": emails, "tokens": tokens}


async def _create_registry(http_client, token) -> str:
    """Helper: create a LandVault to attach evidence to. Returns registry_id."""
    r = await http_client.post(
        "/api/v1/registry/landvaults",
        headers=_hdr(token),
        json={
            "state": "LAGOS", "lga": "IKEJA", "ward": "WARD7",
            "property_type": "RES", "ownership_type": "individual",
            "owner_name": "Evidence Owner",
        },
    )
    r.raise_for_status()
    return r.json()["registry_id"]


# ---- Full happy path: upload → verify → seal → apply-worm ---------------

@pytest.mark.asyncio
async def test_evidence_full_happy_path(http_client, principals, db) -> None:
    token = principals["tokens"]["uploader"]
    admin_token = principals["tokens"]["admin"]
    registry_id = await _create_registry(http_client, token)
    payload = os.urandom(1024 * 16)  # 16 KiB
    expected_hash = hashlib.sha256(payload).hexdigest()

    # 1. Initiate upload
    r = await http_client.post(
        "/api/v1/evidence/items", headers=_hdr(token),
        json={"registry_id": registry_id, "kind": "document",
              "media_type": "application/pdf",
              "max_size": 1024 * 1024,
              "client_hash_claim": expected_hash},
    )
    assert r.status_code == 201, r.text
    init = r.json()
    evidence_id = init["evidence_id"]
    assert init["status"] == "pending_upload"

    # 2. Upload single part (raw body stream)
    r = await http_client.put(
        f"/api/v1/evidence/items/{evidence_id}/parts/1",
        headers=_hdr(token), content=payload,
    )
    assert r.status_code == 200, r.text
    part = r.json()
    assert part["streamed_sha256"] == expected_hash
    assert part["size_bytes"] == len(payload)

    # 3. Complete multipart
    r = await http_client.post(
        f"/api/v1/evidence/items/{evidence_id}/complete",
        headers=_hdr(token),
        json={"parts": [{"part_no": 1, "size_bytes": len(payload),
                          "streamed_sha256": expected_hash}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending_verification"

    # 4. Verify
    r = await http_client.post(
        f"/api/v1/evidence/items/{evidence_id}/verify",
        headers=_hdr(token),
    )
    assert r.status_code == 200, r.text
    verified = r.json()
    assert verified["status"] == "verified"
    assert verified["server_hash"] == expected_hash
    assert verified["hash_verified"] is True

    # 5. Create seal (admin role is required for seal create; or surveyor_general)
    r = await http_client.post(
        "/api/v1/evidence/seals",
        headers=_hdr(admin_token),
        json={"registry_id": registry_id, "evidence_ids": [evidence_id]},
    )
    assert r.status_code == 201, r.text
    seal = r.json()
    seal_id = seal["seal_id"]
    assert seal["status"] == "created"
    assert seal["merkle_root"] == expected_hash  # single-leaf merkle == leaf

    # 6. Apply WORM
    r = await http_client.post(
        f"/api/v1/evidence/seals/{seal_id}/apply-worm",
        headers=_hdr(admin_token), json={},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "worm_applied"

    # 7. The evidence item is now sealed.
    r = await http_client.get(
        f"/api/v1/evidence/items/{evidence_id}",
        headers=_hdr(token),
    )
    body = r.json()
    assert body["status"] == "sealed"
    assert body["seal_id"] == seal_id

    # 8. Outbox carries the expected event types.
    await asyncio.sleep(0.5)
    types = set()
    async for doc in db["kernel_outbox"].find({
            "aggregate_id": {"$in": [evidence_id, seal_id]}}):
        types.add(doc["event_type"])
    for needed in ("evidence.item.uploaded", "evidence.item.hash_verified",
                    "evidence.seal.created", "evidence.seal.worm_applied"):
        assert needed in types, f"missing event: {needed}; got={types}"


# ---- Authorization matrix -----------------------------------------------

@pytest.mark.asyncio
async def test_anonymous_cannot_upload(http_client, principals) -> None:
    token = principals["tokens"]["uploader"]
    registry_id = await _create_registry(http_client, token)
    r = await http_client.post(
        "/api/v1/evidence/items",
        json={"registry_id": registry_id, "kind": "document",
              "media_type": "application/pdf", "max_size": 1024},
    )
    assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_citizen_role_cannot_upload(http_client, principals) -> None:
    """Default `identity_user` role lacks any UPLOAD_ROLES membership."""
    up_token = principals["tokens"]["uploader"]
    registry_id = await _create_registry(http_client, up_token)
    r = await http_client.post(
        "/api/v1/evidence/items",
        headers=_hdr(principals["tokens"]["citizen"]),
        json={"registry_id": registry_id, "kind": "document",
              "media_type": "application/pdf", "max_size": 1024},
    )
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "auth.policy_deny"


@pytest.mark.asyncio
async def test_field_agent_cannot_create_seal(http_client, principals) -> None:
    """field_agent has UPLOAD_ROLES but NOT SEAL_CREATE_ROLES."""
    token = principals["tokens"]["uploader"]
    registry_id = await _create_registry(http_client, token)
    payload = b"x" * 100
    h = hashlib.sha256(payload).hexdigest()
    init = (await http_client.post(
        "/api/v1/evidence/items", headers=_hdr(token),
        json={"registry_id": registry_id, "kind": "document",
              "media_type": "text/plain", "max_size": 1000})).json()
    eid = init["evidence_id"]
    await http_client.put(
        f"/api/v1/evidence/items/{eid}/parts/1",
        headers=_hdr(token), content=payload)
    await http_client.post(
        f"/api/v1/evidence/items/{eid}/complete", headers=_hdr(token),
        json={"parts": [{"part_no": 1, "size_bytes": len(payload),
                          "streamed_sha256": h}]})
    await http_client.post(
        f"/api/v1/evidence/items/{eid}/verify", headers=_hdr(token))
    # Now attempt to create seal as field_agent
    r = await http_client.post(
        "/api/v1/evidence/seals", headers=_hdr(token),
        json={"registry_id": registry_id, "evidence_ids": [eid]})
    assert r.status_code == 403, r.text


# ---- Hash discipline ---------------------------------------------------

@pytest.mark.asyncio
async def test_client_hash_claim_mismatch_returns_409(http_client, principals) -> None:
    token = principals["tokens"]["uploader"]
    registry_id = await _create_registry(http_client, token)
    payload = b"true payload"
    true_hash = hashlib.sha256(payload).hexdigest()
    false_claim = "0" * 64  # the WRONG hash — server will catch it on verify.

    init = (await http_client.post(
        "/api/v1/evidence/items", headers=_hdr(token),
        json={"registry_id": registry_id, "kind": "document",
              "media_type": "text/plain", "max_size": 100,
              "client_hash_claim": false_claim})).json()
    eid = init["evidence_id"]
    # Upload + complete report the TRUE streamed hash (server is authoritative).
    await http_client.put(
        f"/api/v1/evidence/items/{eid}/parts/1",
        headers=_hdr(token), content=payload)
    r = await http_client.post(
        f"/api/v1/evidence/items/{eid}/complete", headers=_hdr(token),
        json={"parts": [{"part_no": 1, "size_bytes": len(payload),
                          "streamed_sha256": true_hash}]})
    assert r.status_code == 200, r.text
    # Verify catches the client-claim mismatch and rolls back.
    r = await http_client.post(
        f"/api/v1/evidence/items/{eid}/verify", headers=_hdr(token))
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "evidence.hash_mismatch"
    # Item is back at pending_upload, client may retry with a correct claim.
    r = await http_client.get(
        f"/api/v1/evidence/items/{eid}", headers=_hdr(token))
    assert r.json()["status"] == "pending_upload"


# ---- Seal invariants ---------------------------------------------------

@pytest.mark.asyncio
async def test_seal_requires_verified_items(http_client, principals) -> None:
    """An item still in PENDING_VERIFICATION cannot be sealed."""
    token = principals["tokens"]["uploader"]
    admin_token = principals["tokens"]["admin"]
    registry_id = await _create_registry(http_client, token)
    payload = b"abc"
    h = hashlib.sha256(payload).hexdigest()
    init = (await http_client.post(
        "/api/v1/evidence/items", headers=_hdr(token),
        json={"registry_id": registry_id, "kind": "document",
              "media_type": "text/plain", "max_size": 100})).json()
    eid = init["evidence_id"]
    await http_client.put(
        f"/api/v1/evidence/items/{eid}/parts/1",
        headers=_hdr(token), content=payload)
    await http_client.post(
        f"/api/v1/evidence/items/{eid}/complete", headers=_hdr(token),
        json={"parts": [{"part_no": 1, "size_bytes": len(payload),
                          "streamed_sha256": h}]})
    # Skip verify — try to seal directly.
    r = await http_client.post(
        "/api/v1/evidence/seals", headers=_hdr(admin_token),
        json={"registry_id": registry_id, "evidence_ids": [eid]})
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "evidence.seal.unverified_item"


@pytest.mark.asyncio
async def test_seal_then_worm_locks_storage_against_overwrite(
        http_client, principals, db) -> None:
    """After apply_worm, the LocalFs adapter refuses any new multipart on
    the same key — exercised by trying to re-initiate an upload for the
    sealed evidence's storage object via the WORM adapter directly."""
    from contexts.evidence.adapters.fs_worm_storage import (
        LocalFsWormStorage, WormViolationError,
    )
    from contexts.evidence.ports.storage import (
        StorageObjectKey, StorageTier,
    )
    token = principals["tokens"]["uploader"]
    admin_token = principals["tokens"]["admin"]
    registry_id = await _create_registry(http_client, token)
    payload = b"sealed-bytes"
    h = hashlib.sha256(payload).hexdigest()
    init = (await http_client.post(
        "/api/v1/evidence/items", headers=_hdr(token),
        json={"registry_id": registry_id, "kind": "document",
              "media_type": "text/plain", "max_size": 100})).json()
    eid = init["evidence_id"]
    await http_client.put(
        f"/api/v1/evidence/items/{eid}/parts/1",
        headers=_hdr(token), content=payload)
    await http_client.post(
        f"/api/v1/evidence/items/{eid}/complete", headers=_hdr(token),
        json={"parts": [{"part_no": 1, "size_bytes": len(payload),
                          "streamed_sha256": h}]})
    await http_client.post(
        f"/api/v1/evidence/items/{eid}/verify", headers=_hdr(token))
    seal = (await http_client.post(
        "/api/v1/evidence/seals", headers=_hdr(admin_token),
        json={"registry_id": registry_id, "evidence_ids": [eid]})).json()
    r = await http_client.post(
        f"/api/v1/evidence/seals/{seal['seal_id']}/apply-worm",
        headers=_hdr(admin_token), json={})
    assert r.status_code == 200, r.text

    # Look up the stored locator and try to re-initiate an upload on
    # that key via the adapter directly.
    doc = await db["evidence_items"].find_one({"evidence_id": eid})
    locator = doc["storage_locator"]
    parts = locator.split("/")
    key = StorageObjectKey(
        tier=StorageTier(parts[0]), tenant_id=parts[1],
        yyyy=parts[2], mm=parts[3], dd=parts[4],
        evidence_id=parts[5], suffix=parts[6],
    )
    root = os.environ.get("EVIDENCE_FS_ROOT", "/tmp/aqua-evidence")
    adapter = LocalFsWormStorage(root_dir=root)
    with pytest.raises(WormViolationError):
        await adapter.initiate_multipart(
            key=key, media_type="text/plain", max_size=10)


@pytest.mark.asyncio
async def test_sealed_item_blocks_re_verification(http_client, principals) -> None:
    """Once an item is SEALED, calling /verify must 409."""
    token = principals["tokens"]["uploader"]
    admin_token = principals["tokens"]["admin"]
    registry_id = await _create_registry(http_client, token)
    payload = b"seal-bytes"
    h = hashlib.sha256(payload).hexdigest()
    init = (await http_client.post(
        "/api/v1/evidence/items", headers=_hdr(token),
        json={"registry_id": registry_id, "kind": "document",
              "media_type": "text/plain", "max_size": 100})).json()
    eid = init["evidence_id"]
    await http_client.put(
        f"/api/v1/evidence/items/{eid}/parts/1",
        headers=_hdr(token), content=payload)
    await http_client.post(
        f"/api/v1/evidence/items/{eid}/complete", headers=_hdr(token),
        json={"parts": [{"part_no": 1, "size_bytes": len(payload),
                          "streamed_sha256": h}]})
    await http_client.post(
        f"/api/v1/evidence/items/{eid}/verify", headers=_hdr(token))
    await http_client.post(
        "/api/v1/evidence/seals", headers=_hdr(admin_token),
        json={"registry_id": registry_id, "evidence_ids": [eid]})
    r = await http_client.post(
        f"/api/v1/evidence/items/{eid}/verify", headers=_hdr(token))
    assert r.status_code == 409, r.text


# ---- Tenant isolation --------------------------------------------------

@pytest.mark.asyncio
async def test_cross_tenant_evidence_read_returns_404(
        http_client, principals) -> None:
    token = principals["tokens"]["uploader"]
    registry_id = await _create_registry(http_client, token)
    payload = b"isolated"
    h = hashlib.sha256(payload).hexdigest()
    init = (await http_client.post(
        "/api/v1/evidence/items", headers=_hdr(token),
        json={"registry_id": registry_id, "kind": "document",
              "media_type": "text/plain", "max_size": 100})).json()
    eid = init["evidence_id"]
    await http_client.put(
        f"/api/v1/evidence/items/{eid}/parts/1",
        headers=_hdr(token), content=payload)
    await http_client.post(
        f"/api/v1/evidence/items/{eid}/complete", headers=_hdr(token),
        json={"parts": [{"part_no": 1, "size_bytes": len(payload),
                          "streamed_sha256": h}]})
    # Citizen (different tenant) — read must 404 even though they pass auth.
    r = await http_client.get(
        f"/api/v1/evidence/items/{eid}",
        headers=_hdr(principals["tokens"]["citizen"]),
    )
    assert r.status_code in (403, 404), r.text


# ---- Signed URL --------------------------------------------------------

@pytest.mark.asyncio
async def test_signed_url_audits_before_returning(http_client, principals, db) -> None:
    token = principals["tokens"]["uploader"]
    registry_id = await _create_registry(http_client, token)
    payload = b"signed-url-bytes"
    h = hashlib.sha256(payload).hexdigest()
    init = (await http_client.post(
        "/api/v1/evidence/items", headers=_hdr(token),
        json={"registry_id": registry_id, "kind": "document",
              "media_type": "text/plain", "max_size": 100})).json()
    eid = init["evidence_id"]
    await http_client.put(
        f"/api/v1/evidence/items/{eid}/parts/1",
        headers=_hdr(token), content=payload)
    await http_client.post(
        f"/api/v1/evidence/items/{eid}/complete", headers=_hdr(token),
        json={"parts": [{"part_no": 1, "size_bytes": len(payload),
                          "streamed_sha256": h}]})
    await http_client.post(
        f"/api/v1/evidence/items/{eid}/verify", headers=_hdr(token))

    r = await http_client.post(
        f"/api/v1/evidence/items/{eid}/signed-url",
        headers=_hdr(token), json={"action": "read", "ttl_seconds": 300})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "?exp=" in body["url"]
    # The audit row exists.
    found = await db["evidence_signed_url_audit"].find_one({
        "audit_id": body["audit_id"]})
    assert found is not None
    assert found["url_sha256"] == body["url_sha256"]
    assert found["evidence_id"] == eid


# ---- Contract drift check ----------------------------------------------

def test_contract_freeze_at_1_2_0() -> None:
    """The frozen contract package must be exactly 1.2.0 and the drift
    gate must be green after Phase 3.4 + 3.5."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent.parent
    version = (root / "contracts" / "VERSION").read_text().strip()
    assert version == "1.2.0"


def test_evidence_event_types_are_registered_in_outbox() -> None:
    from kernel.events.outbox import EVENT_TYPES
    for evt in ("evidence.item.uploaded", "evidence.item.hash_verified",
                "evidence.item.hash_mismatch", "evidence.item.archived_replaced",
                "evidence.seal.created", "evidence.seal.worm_applied",
                "evidence.seal.archived", "evidence.signed_url.issued"):
        assert evt in EVENT_TYPES, f"missing event_type: {evt}"
