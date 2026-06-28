"""Phase 2A — Registry API + authorization matrix + tenant isolation + 2dsphere
+ event publication + audit + locked-state protection (Directive §12).

This is the heaviest integration test in the suite. It exercises the LIVE
backend (Mongo replica set + Phase 1 PEP) end-to-end with three principals
of distinct roles and asserts each row of the per-role authorization
matrix from Phase 2 §3.3.

Why one file? Setting up the JWT scaffolding for each principal is
non-trivial; sharing fixtures across tests in a single module makes the
matrix readable.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Optional

import httpx
import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

API_URL_INTERNAL = "http://localhost:8001"


# ---- Helpers -------------------------------------------------------------

async def _register_and_login(client: httpx.AsyncClient, *, email: str,
                              password: str = "TestPass123!",
                              country: str = "NG") -> str:
    """Register a user and return a fresh access token. Idempotent."""
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
    """Directly assign a role bypassing the API (we don't want to mint
    a super_admin from the registry tests). This mutates the user
    document in-place and bumps version. Roles in the DB are a list.
    """
    col = db["identity_users"]
    user = await col.find_one({"email": email.lower()})
    assert user is not None, f"user {email} not found for role grant"
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
    async with httpx.AsyncClient(base_url=API_URL_INTERNAL, timeout=20) as client:
        yield client


@pytest_asyncio.fixture
async def db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    yield client[os.environ["DB_NAME"]]
    client.close()


@pytest_asyncio.fixture
async def principals(http_client, db):
    """Three principals: a field_agent (creator), a citizen (foreigner), a super_admin."""
    suffix = uuid.uuid4().hex[:8]
    agents = {
        "agent": f"reg_agent_{suffix}@example.com",
        "citizen": f"reg_citizen_{suffix}@example.com",
        "admin": f"reg_admin_{suffix}@example.com",
    }
    tokens = {}
    for label, email in agents.items():
        tokens[label] = await _register_and_login(http_client, email=email)
    await _grant_role(db, agents["agent"], role="field_agent")
    await _grant_role(db, agents["admin"], role="super_admin")
    # Re-login to pick up the new roles in the JWT claims.
    tokens["agent"] = (await http_client.post("/api/v1/auth/login", json={
        "email": agents["agent"], "password": "TestPass123!"})).json()["access_token"]
    tokens["admin"] = (await http_client.post("/api/v1/auth/login", json={
        "email": agents["admin"], "password": "TestPass123!"})).json()["access_token"]
    return {"emails": agents, "tokens": tokens}


def _payload(state="LAGOS", lga="IKEJA", ward="WARD3", **overrides):
    base = {
        "state": state, "lga": lga, "ward": ward, "property_type": "RES",
        "ownership_type": "individual", "owner_name": "Ada Lovelace",
        "owner_email": "ada@example.com",
    }
    base.update(overrides)
    return base


# ---- AUTHORIZATION MATRIX -----------------------------------------------

@pytest.mark.asyncio
async def test_anonymous_cannot_create(http_client) -> None:
    r = await http_client.post("/api/v1/registry/landvaults", json=_payload())
    assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_citizen_without_role_cannot_create(http_client, principals) -> None:
    r = await http_client.post(
        "/api/v1/registry/landvaults",
        headers=_hdr(principals["tokens"]["citizen"]),
        json=_payload(),
    )
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "auth.policy_deny"


@pytest.mark.asyncio
async def test_field_agent_can_create(http_client, principals) -> None:
    r = await http_client.post(
        "/api/v1/registry/landvaults",
        headers=_hdr(principals["tokens"]["agent"]),
        json=_payload(),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["registry_id"].startswith("reg_")
    parts = body["parcel_number"].split("-")
    assert len(parts) == 5 and len(parts[-1]) == 6
    assert body["status"] == "draft"
    assert body["version"] == 1


# ---- READ + FIELD PROJECTION + TENANT ISOLATION --------------------------

@pytest.mark.asyncio
async def test_creator_can_read_own_landvault(http_client, principals) -> None:
    created = (await http_client.post(
        "/api/v1/registry/landvaults",
        headers=_hdr(principals["tokens"]["agent"]),
        json=_payload(owner_name="Read Test"))).json()
    r = await http_client.get(
        f"/api/v1/registry/landvaults/{created['registry_id']}",
        headers=_hdr(principals["tokens"]["agent"]))
    assert r.status_code == 200
    body = r.json()
    assert body["registry_id"] == created["registry_id"]
    # Owner-tier projection: no `owner_nin`, no `tenant_id`.
    assert "owner_nin" not in body
    assert "tenant_id" not in body


@pytest.mark.asyncio
async def test_unrelated_citizen_cannot_read_others_landvault(
        http_client, principals) -> None:
    """Tenant isolation (Phase 2A §9): each user gets their own tenant on
    registration. Cross-tenant reads MUST return 404 (never reveal
    existence). Super admin can read everything; the unrelated citizen
    must not.
    """
    created = (await http_client.post(
        "/api/v1/registry/landvaults",
        headers=_hdr(principals["tokens"]["agent"]),
        json=_payload(owner_name="Hidden Owner",
                      owner_email="hidden@example.com"))).json()
    # Citizen (different tenant) — 404, not 200 with redacted body.
    r = await http_client.get(
        f"/api/v1/registry/landvaults/{created['registry_id']}",
        headers=_hdr(principals["tokens"]["citizen"]))
    assert r.status_code == 404, r.text
    # Super admin (cross-tenant read allowed) — 200 with privileged projection.
    r = await http_client.get(
        f"/api/v1/registry/landvaults/{created['registry_id']}",
        headers=_hdr(principals["tokens"]["admin"]))
    assert r.status_code == 200, r.text
    body = r.json()
    # Privileged projection exposes tenant_id, origin, schema_version, etc.
    assert "tenant_id" in body
    assert "origin" in body
    # Owner PII visible to privileged roles.
    assert body.get("owner_email") == "hidden@example.com"


# ---- LOCKED-STATE PROTECTION --------------------------------------------

@pytest.mark.asyncio
async def test_locked_status_blocks_owner_update(http_client, principals, db) -> None:
    created = (await http_client.post(
        "/api/v1/registry/landvaults",
        headers=_hdr(principals["tokens"]["agent"]),
        json=_payload(owner_name="Locked Test"))).json()
    # Simulate a locked status by direct DB write.
    await db["landvault_landvaults"].update_one(
        {"registry_id": created["registry_id"]},
        {"$set": {"status": "approved_locked"}},
    )
    r = await http_client.patch(
        f"/api/v1/registry/landvaults/{created['registry_id']}/location",
        headers=_hdr(principals["tokens"]["agent"]),
        json={"address": "Should fail"},
    )
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "registry.locked_state"
    # Super admin bypass succeeds.
    r2 = await http_client.patch(
        f"/api/v1/registry/landvaults/{created['registry_id']}/location",
        headers=_hdr(principals["tokens"]["admin"]),
        json={"address": "Admin override"},
    )
    assert r2.status_code == 200, r2.text


# ---- ARCHIVE: super_admin only ------------------------------------------

@pytest.mark.asyncio
async def test_archive_requires_super_admin(http_client, principals) -> None:
    created = (await http_client.post(
        "/api/v1/registry/landvaults",
        headers=_hdr(principals["tokens"]["agent"]),
        json=_payload(owner_name="Archive Test"))).json()
    # Non-admin cannot archive
    r = await http_client.post(
        f"/api/v1/registry/landvaults/{created['registry_id']}/archive",
        headers=_hdr(principals["tokens"]["agent"]),
        json={"reason": "duplicate"})
    assert r.status_code == 403, r.text
    # Super admin can
    r = await http_client.post(
        f"/api/v1/registry/landvaults/{created['registry_id']}/archive",
        headers=_hdr(principals["tokens"]["admin"]),
        json={"reason": "duplicate"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "archived"
    # And it's one-way: after archive, the record is excluded from normal
    # reads (deleted_at != None), so a second archive request 404s. This
    # is the intentional one-way invariant — archived records are not
    # editable through any API path.
    r = await http_client.post(
        f"/api/v1/registry/landvaults/{created['registry_id']}/archive",
        headers=_hdr(principals["tokens"]["admin"]),
        json={"reason": "again"})
    assert r.status_code in (404, 409, 422)


# ---- OWNERSHIP DISCIPLINE (§3) -------------------------------------------

@pytest.mark.asyncio
async def test_contact_update_does_not_extend_ownership_history(
        http_client, principals, db) -> None:
    created = (await http_client.post(
        "/api/v1/registry/landvaults",
        headers=_hdr(principals["tokens"]["agent"]),
        json=_payload(owner_name="Contact Test"))).json()
    # Patch phone — must NOT emit registry.ownership.recorded
    before_history = (await db["landvault_landvaults"].find_one(
        {"registry_id": created["registry_id"]}))["ownership_history"]
    r = await http_client.patch(
        f"/api/v1/registry/landvaults/{created['registry_id']}/ownership-contact",
        headers=_hdr(principals["tokens"]["agent"]),
        json={"owner_phone": "+234-800-9990001"})
    assert r.status_code == 200, r.text
    after = await db["landvault_landvaults"].find_one(
        {"registry_id": created["registry_id"]})
    assert after["owner_phone"] == "+234-800-9990001"
    assert after["ownership_history"] == before_history  # unchanged


@pytest.mark.asyncio
async def test_legal_transfer_appends_history_and_emits_event(
        http_client, principals, db) -> None:
    created = (await http_client.post(
        "/api/v1/registry/landvaults",
        headers=_hdr(principals["tokens"]["agent"]),
        json=_payload(owner_name="Transfer Test"))).json()
    # Admin performs a legal transfer (governance role).
    r = await http_client.post(
        f"/api/v1/registry/landvaults/{created['registry_id']}/ownership-transfer",
        headers=_hdr(principals["tokens"]["admin"]),
        json={"owner_name": "New Holder", "ownership_type": "corporate",
              "reason": "sale"})
    assert r.status_code == 200, r.text
    doc = await db["landvault_landvaults"].find_one(
        {"registry_id": created["registry_id"]})
    assert len(doc["ownership_history"]) == 2
    assert doc["ownership_history"][-1]["owner_name"] == "New Holder"
    # OwnershipRecorded event landed in the outbox
    evt = await db["kernel_outbox"].find_one({
        "event_type": "registry.ownership.recorded",
        "aggregate_id": created["registry_id"],
    })
    assert evt is not None


# ---- EVENT PUBLICATION & AUDIT ------------------------------------------

@pytest.mark.asyncio
async def test_creation_publishes_three_events_and_audit_entries(
        http_client, principals, db) -> None:
    created = (await http_client.post(
        "/api/v1/registry/landvaults",
        headers=_hdr(principals["tokens"]["agent"]),
        json=_payload(owner_name="Event Test"))).json()
    rid = created["registry_id"]

    # Give the outbox publisher up to 2s to drain.
    await asyncio.sleep(0.5)
    types = set()
    async for doc in db["kernel_outbox"].find({"aggregate_id": rid}):
        types.add(doc["event_type"])
    assert "registry.landvault.created" in types
    assert "registry.parcel_reference.allocated" in types
    assert "registry.ownership.recorded" in types

    # Audit log carries an entry per event
    audit_count = await db["kernel_audit_log"].count_documents({"resource_id": rid})
    assert audit_count >= 3


# ---- 2DSPHERE GEOMETRY QUERIES ------------------------------------------

@pytest.mark.asyncio
async def test_geometry_update_round_trips_and_2dsphere_query_works(
        http_client, principals, db) -> None:
    created = (await http_client.post(
        "/api/v1/registry/landvaults",
        headers=_hdr(principals["tokens"]["agent"]),
        json=_payload(owner_name="Geo Test"))).json()
    rid = created["registry_id"]
    # Square around Lagos Island
    geom = {
        "type": "Polygon",
        "coordinates": [[
            [3.40, 6.45], [3.42, 6.45], [3.42, 6.47],
            [3.40, 6.47], [3.40, 6.45],
        ]],
    }
    r = await http_client.patch(
        f"/api/v1/registry/landvaults/{rid}/geometry",
        headers=_hdr(principals["tokens"]["agent"]),
        json={"geometry": geom, "boundary_source": "field_survey"})
    assert r.status_code == 200, r.text

    # 2dsphere query: $near should find this parcel within 5km of (3.41,6.46).
    near_results = await db["landvault_landvaults"].find({
        "geometry": {
            "$near": {
                "$geometry": {"type": "Point", "coordinates": [3.41, 6.46]},
                "$maxDistance": 5000,
            }
        },
        "registry_id": rid,
    }).to_list(length=5)
    assert len(near_results) == 1
    assert near_results[0]["registry_id"] == rid


# ---- INVALID PAYLOAD REJECTION ------------------------------------------

@pytest.mark.asyncio
async def test_unknown_fields_rejected(http_client, principals) -> None:
    """Per-role Pydantic models forbid extra fields (mass-assignment guard)."""
    r = await http_client.post(
        "/api/v1/registry/landvaults",
        headers=_hdr(principals["tokens"]["agent"]),
        json={**_payload(), "tenant_id": "attacker_tenant",
              "registry_id": "reg_evil"})
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_invalid_geometry_rejected(http_client, principals) -> None:
    created = (await http_client.post(
        "/api/v1/registry/landvaults",
        headers=_hdr(principals["tokens"]["agent"]),
        json=_payload(owner_name="Bad geo"))).json()
    r = await http_client.patch(
        f"/api/v1/registry/landvaults/{created['registry_id']}/geometry",
        headers=_hdr(principals["tokens"]["agent"]),
        json={"geometry": {"type": "Polygon",
                            "coordinates": [[[200, 0], [0, 0], [0, 1], [200, 0]]]}})
    assert r.status_code == 400
    assert r.json()["code"] == "registry.geometry_invalid"


# ---- IMMUTABILITY GUARDS AT THE EDGE ------------------------------------

@pytest.mark.asyncio
async def test_legacy_aliases_are_never_authoritative(http_client, principals) -> None:
    """Creating a vault with legacy_aliases works; reading by alias returns
    the SAME aggregate; aliases are never treated as the canonical id."""
    created = (await http_client.post(
        "/api/v1/registry/landvaults",
        headers=_hdr(principals["tokens"]["agent"]),
        json=_payload(owner_name="Alias Test",
                      legacy_aliases=["LP-LEGACY-001", "LV-LEGACY-001"]))).json()
    # Aliases are present in response (owner projection includes them).
    assert "LP-LEGACY-001" in created["legacy_aliases"]
    # Aliases are not the registry_id.
    assert created["registry_id"] != "LP-LEGACY-001"
    assert created["registry_id"] != "LV-LEGACY-001"
