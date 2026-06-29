"""Phase 3.7 — Timeline + Custody + Legal Hold + Supersession tests."""
from __future__ import annotations

import asyncio
import hashlib
import os
import uuid

import httpx
import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from contexts.evidence.domain.chain import compute_entry_hash
from contexts.evidence.domain.invariants import (
    ImmutableFieldError,
    InvariantViolation,
    TransitionError,
)
from contexts.evidence.domain.timeline import (
    CustodyEntry,
    LegalHold,
    LegalHoldStatus,
    TimelineEntry,
    TimelineEventKind,
)

API_URL_INTERNAL = "http://localhost:8001"


# ============================================================================
# Domain invariant tests
# ============================================================================

def test_timeline_genesis_requires_prev_hash_none() -> None:
    with pytest.raises(InvariantViolation):
        TimelineEntry.create(evidence_id="evd_x", tenant_id="t",
                              country_code="NG",
                              kind=TimelineEventKind.UPLOAD.value,
                              actor="u", seq=0, prev_hash="a" * 64,
                              summary="x", payload={})


def test_timeline_non_genesis_requires_prev_hash() -> None:
    with pytest.raises(InvariantViolation):
        TimelineEntry.create(evidence_id="evd_x", tenant_id="t",
                              country_code="NG",
                              kind=TimelineEventKind.UPLOAD.value,
                              actor="u", seq=1, prev_hash=None,
                              summary="x", payload={})


def test_timeline_invalid_kind_rejected() -> None:
    with pytest.raises(InvariantViolation):
        TimelineEntry.create(evidence_id="evd_x", tenant_id="t",
                              country_code="NG", kind="bogus",
                              actor="u", seq=0, prev_hash=None,
                              summary="x", payload={})


def test_timeline_chain_reconstruction_is_deterministic() -> None:
    """Property test: rebuild the entry_hash from prev + payload and
    confirm bit-identity. This is the core acceptance gate for
    reconstruction."""
    entry = TimelineEntry.create(
        evidence_id="evd_z", tenant_id="t", country_code="NG",
        kind=TimelineEventKind.UPLOAD.value, actor="u", seq=0,
        prev_hash=None, summary="x", payload={"k": "v"})
    expected = compute_entry_hash(None, {
        "timeline_id": entry.timeline_id, "evidence_id": "evd_z",
        "kind": TimelineEventKind.UPLOAD.value,
        "actor": "u", "occurred_at": entry.occurred_at, "seq": 0,
        "summary": "x", "payload": {"k": "v"},
    })
    assert entry.entry_hash == expected


def test_custody_requires_justification() -> None:
    with pytest.raises(InvariantViolation):
        CustodyEntry.create(evidence_id="evd_x", tenant_id="t",
                              country_code="NG", actor="u", role="r",
                              action="accessed", justification="",
                              seq=0, prev_hash=None)


def test_custody_rejects_unknown_action() -> None:
    with pytest.raises(InvariantViolation):
        CustodyEntry.create(evidence_id="evd_x", tenant_id="t",
                              country_code="NG", actor="u", role="r",
                              action="invalid", justification="ok",
                              seq=0, prev_hash=None)


def test_legal_hold_initial_state_active() -> None:
    h = LegalHold.create(evidence_id="evd_x", tenant_id="t",
                         country_code="NG", case_reference="CR-123",
                         issued_by="usr_admin", reason="court order")
    assert h.is_active
    assert h.status == LegalHoldStatus.ACTIVE.value
    types = [e.event_type for e in h.pull_events()]
    assert types == ["evidence.legal_hold.applied"]


def test_legal_hold_release_is_one_way() -> None:
    h = LegalHold.create(evidence_id="evd_x", tenant_id="t",
                         country_code="NG", case_reference="CR-123",
                         issued_by="u123", reason="court order initial")
    h.pull_events()
    h.release(released_by="usr_admin", release_reason="case closed")
    assert h.status == LegalHoldStatus.RELEASED.value
    with pytest.raises(TransitionError):
        h.release(released_by="u2", release_reason="again")
    types = [e.event_type for e in h.pull_events()]
    assert types == ["evidence.legal_hold.released"]


def test_legal_hold_release_requires_reason() -> None:
    h = LegalHold.create(evidence_id="evd_x", tenant_id="t",
                         country_code="NG", case_reference="CR-AB",
                         issued_by="usr1", reason="initial reason long enough")
    with pytest.raises(InvariantViolation):
        h.release(released_by="u", release_reason="")


# ============================================================================
# E2E — timeline + custody + legal hold + supersession
# ============================================================================

async def _register_and_login(client, *, email: str,
                              password: str = "TestPass123!") -> str:
    await client.post("/api/v1/auth/register", json={
        "email": email, "password": password,
        "full_name": email.split("@")[0], "country": "NG"})
    r = await client.post("/api/v1/auth/login",
                          json={"email": email, "password": password})
    r.raise_for_status()
    return r.json()["access_token"]


async def _grant_role(db, email: str, *, role: str) -> None:
    col = db["identity_users"]
    user = await col.find_one({"email": email.lower()})
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
    emails = {"uploader": f"p37_up_{suffix}@example.com",
              "admin": f"p37_adm_{suffix}@example.com"}
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


async def _seal_one_evidence(http_client, principals):
    up_t = principals["tokens"]["uploader"]
    ad_t = principals["tokens"]["admin"]
    r = await http_client.post(
        "/api/v1/registry/landvaults", headers=_hdr(up_t),
        json={"state": "LAGOS", "lga": "IKEJA", "ward": "WARD9",
              "property_type": "RES", "ownership_type": "individual",
              "owner_name": "Phase37 Owner"})
    reg = r.json()["registry_id"]
    payload = b"phase37-bytes-" + uuid.uuid4().bytes
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


@pytest.mark.asyncio
async def test_timeline_is_auto_projected_from_event_stream(
        http_client, principals, db) -> None:
    eid, sid = await _seal_one_evidence(http_client, principals)
    # Allow the outbox publisher + subscriber to run.
    await asyncio.sleep(1.0)
    r = await http_client.get(
        f"/api/v1/evidence/items/{eid}/timeline",
        headers=_hdr(principals["tokens"]["admin"]))
    assert r.status_code == 200, r.text
    chain = r.json()["chain"]
    kinds = [e["kind"] for e in chain]
    assert "upload" in kinds, f"expected upload event in timeline; got {kinds}"
    assert "seal" in kinds, f"expected seal event in timeline; got {kinds}"
    assert "lock" in kinds, f"expected lock event in timeline; got {kinds}"
    # Chain is strictly ordered by seq.
    seqs = [e["seq"] for e in chain]
    assert seqs == sorted(seqs)
    # entry_hash links: each entry's prev_hash equals the previous entry_hash.
    for prev, curr in zip(chain, chain[1:]):
        assert curr["prev_hash"] == prev["entry_hash"]


@pytest.mark.asyncio
async def test_custody_records_signed_url_access(http_client, principals,
                                                    db) -> None:
    eid, sid = await _seal_one_evidence(http_client, principals)
    # Issue a signed URL — this should produce a custody 'accessed' entry.
    await http_client.post(
        f"/api/v1/evidence/items/{eid}/signed-url",
        headers=_hdr(principals["tokens"]["uploader"]),
        json={"action": "read", "ttl_seconds": 300})
    await asyncio.sleep(1.0)
    r = await http_client.get(
        f"/api/v1/evidence/items/{eid}/custody",
        headers=_hdr(principals["tokens"]["admin"]))
    assert r.status_code == 200, r.text
    chain = r.json()["chain"]
    assert any(e["action"] == "accessed" for e in chain)


@pytest.mark.asyncio
async def test_record_custody_endpoint_appends_link(http_client, principals,
                                                       db) -> None:
    eid, sid = await _seal_one_evidence(http_client, principals)
    r = await http_client.post(
        f"/api/v1/evidence/items/{eid}/custody",
        headers=_hdr(principals["tokens"]["admin"]),
        json={"role": "compliance_officer", "action": "signed",
              "justification": "deposition signed",
              "signature_kid": "jwks-1",
              "signature": "0xdeadbeef"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["action"] == "signed"
    assert body["justification"] == "deposition signed"


@pytest.mark.asyncio
async def test_apply_and_release_legal_hold(http_client, principals,
                                                db) -> None:
    eid, sid = await _seal_one_evidence(http_client, principals)
    ad = principals["tokens"]["admin"]
    r = await http_client.post(
        f"/api/v1/evidence/items/{eid}/legal-holds",
        headers=_hdr(ad),
        json={"case_reference": "FHC/L/2026/001",
              "reason": "Federal High Court order"})
    assert r.status_code == 201, r.text
    hid = r.json()["hold_id"]
    # List holds
    r2 = await http_client.get(
        f"/api/v1/evidence/items/{eid}/legal-holds",
        headers=_hdr(ad))
    holds = r2.json()["holds"]
    assert any(h["hold_id"] == hid and h["status"] == "active" for h in holds)
    # Release
    r3 = await http_client.post(
        f"/api/v1/evidence/legal-holds/{hid}/release",
        headers=_hdr(ad), json={"release_reason": "case dismissed"})
    assert r3.status_code == 200, r3.text
    assert r3.json()["status"] == "released"
    # Second release MUST fail with 409.
    r4 = await http_client.post(
        f"/api/v1/evidence/legal-holds/{hid}/release",
        headers=_hdr(ad), json={"release_reason": "again"})
    assert r4.status_code in (409, 400), r4.text


@pytest.mark.asyncio
async def test_legal_hold_requires_privileged_role(http_client, principals,
                                                       db) -> None:
    """Constitutional invariant: only super_admin + compliance_officer
    can apply/release Legal Holds."""
    eid, _ = await _seal_one_evidence(http_client, principals)
    # field_agent (UPLOAD_ROLES) MUST be denied.
    r = await http_client.post(
        f"/api/v1/evidence/items/{eid}/legal-holds",
        headers=_hdr(principals["tokens"]["uploader"]),
        json={"case_reference": "CR-X",
              "reason": "field agent should not be allowed"})
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_supersession_chain_endpoint(http_client, principals,
                                              db) -> None:
    eid, sid = await _seal_one_evidence(http_client, principals)
    r = await http_client.get(
        f"/api/v1/evidence/items/{eid}/supersession-chain",
        headers=_hdr(principals["tokens"]["admin"]))
    assert r.status_code == 200, r.text
    chain = r.json()["chain"]
    # Single-item chain — no successor (since we haven't superseded).
    assert chain[0]["evidence_id"] == eid
    assert chain[0]["superseded_by"] is None


@pytest.mark.asyncio
async def test_timeline_no_pii_leak_in_payloads(http_client, principals,
                                                  db) -> None:
    """Constitutional invariant: timeline payload must not leak PII."""
    eid, _ = await _seal_one_evidence(http_client, principals)
    await asyncio.sleep(1.0)
    r = await http_client.get(
        f"/api/v1/evidence/items/{eid}/timeline",
        headers=_hdr(principals["tokens"]["admin"]))
    chain = r.json()["chain"]
    text = str(chain).lower()
    for pii in ("owner_name", "owner_email", "owner_phone", "owner_nin"):
        assert pii not in text, f"PII '{pii}' leaked into timeline payload"


# ============================================================================
# Contract verification
# ============================================================================

def test_phase37_events_in_outbox_registry() -> None:
    from kernel.events.outbox import EVENT_TYPES
    for e in ("evidence.timeline.appended", "evidence.custody.appended",
              "evidence.legal_hold.applied",
              "evidence.legal_hold.released",
              "evidence.supersession.recorded"):
        assert e in EVENT_TYPES, f"missing event_type: {e}"


def test_contract_at_or_above_1_4_0() -> None:
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent.parent
    version = (root / "contracts" / "VERSION").read_text().strip()
    major, minor, _ = version.split(".")
    assert int(major) == 1 and int(minor) >= 4, f"got {version}"
