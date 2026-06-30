"""Phase 3.8 — Projection Engine, Read Models & Replay tests.

Acceptance gates (ADR-0010):
* Projection Purity Invariant (zero business logic, zero aggregate
  mutation, zero command publishing).
* Cursor + lag tracking persists across deliveries.
* Full delete + replay produces byte-identical state.
* Replay endpoint is super_admin gated.
* Snapshot endpoint records a baseline timestamp.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from kernel.events.envelope import Envelope, new_envelope
from kernel.events.outbox import OUTBOX_COLLECTION
from kernel.projections import (
    InvariantError,
    Projection,
    ProjectionEngine,
    assert_projection_purity,
)

API_URL_INTERNAL = "http://localhost:8001"


# ============================================================================
# ADR-0010 §1 — Projection Purity Invariant
# ============================================================================

class _PureProjection:
    """Reference legal projection: pure event-to-row mapping, no mutators."""

    name = "test.pure"
    version = 1
    event_glob = "test.*"

    def __init__(self) -> None:
        self.rows: list[Envelope] = []

    async def on_event(self, env: Envelope) -> None:
        self.rows.append(env)

    async def reset(self) -> None:
        self.rows.clear()


class _ImpureProjection:
    """A projection that smuggles aggregate mutation — MUST be rejected."""

    name = "test.impure"
    version = 1
    event_glob = "test.*"

    async def on_event(self, env: Envelope) -> None:
        # Forbidden: a projection MUST NOT archive aggregates.
        self.archive(env)

    async def archive(self, env: Envelope) -> None:
        # ``.archive(`` is a forbidden mutator token (ADR-0010 §1).
        pass

    async def reset(self) -> None:
        pass


def test_purity_accepts_pure_projection() -> None:
    """A clean projection passes the static check."""
    assert_projection_purity(_PureProjection())


def test_purity_rejects_aggregate_mutation_token() -> None:
    """Source contains ``.archive(`` — must raise InvariantError."""
    with pytest.raises(InvariantError):
        assert_projection_purity(_ImpureProjection())


def test_purity_rejects_publish_token() -> None:
    """A projection that calls ``await publish(...)`` MUST be rejected."""

    class _PublishingProjection:
        name = "test.publishing"
        version = 1
        event_glob = "*"

        async def on_event(self, env):
            # Forbidden: projections never publish commands.
            from kernel.events.outbox import publish  # noqa: F401
            await publish(env)  # noqa: F821

        async def reset(self):
            pass

    with pytest.raises(InvariantError):
        assert_projection_purity(_PublishingProjection())


# ============================================================================
# Engine unit tests — cursor + replay + snapshot + health
# ============================================================================

@pytest_asyncio.fixture
async def mongo_db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    yield client[os.environ["DB_NAME"]]
    client.close()


@pytest_asyncio.fixture
async def isolated_engine(mongo_db):
    """A clean engine + isolated outbox slice keyed by a unique event_type
    prefix so the test never touches the production timeline projection."""
    eng = ProjectionEngine(db=mongo_db)
    await eng.ensure_indexes()
    yield eng
    # Cleanup
    await mongo_db["kernel_projection_cursors"].delete_many(
        {"name": {"$regex": "^test\\."}})


async def _insert_test_events(db, *, event_type: str, n: int) -> list[Envelope]:
    """Drop synthetic events directly into the outbox at status DELIVERED so
    the engine can replay them without the live publisher interfering."""
    envs: list[Envelope] = []
    for i in range(n):
        env = new_envelope(
            event_type=event_type, event_version=1,
            aggregate_type="TestAgg", aggregate_id=f"agg_{uuid.uuid4().hex}",
            aggregate_version=i, payload={"i": i},
            producer="test", tenant_id="t", country="NG", actor="u")
        envs.append(env)
        doc = env.to_doc()
        doc["status"] = "DELIVERED"
        doc["attempts"] = 1
        await db[OUTBOX_COLLECTION].insert_one(dict(doc))
    return envs


@pytest.mark.asyncio
async def test_engine_register_and_deliver_updates_cursor(isolated_engine,
                                                            mongo_db):
    proj = _PureProjection()
    handler = isolated_engine.register(proj)
    # Synthesise a single envelope and feed the wrapper directly.
    env = new_envelope(
        event_type="test.deliver", event_version=1,
        aggregate_type="A", aggregate_id="a1", aggregate_version=0,
        payload={"x": 1}, producer="test")
    await handler(env)
    cur = await mongo_db["kernel_projection_cursors"].find_one(
        {"name": proj.name}, {"_id": 0})
    assert cur is not None
    assert cur["cursor_event_id"] == env.event_id
    assert cur["delivered_count"] == 1
    assert cur["last_event_type"] == "test.deliver"
    assert proj.rows == [env]
    status = await isolated_engine.status(proj.name)
    assert status.delivered_count == 1
    assert status.cursor_event_id == env.event_id


@pytest.mark.asyncio
async def test_replay_rebuild_is_byte_identical(isolated_engine, mongo_db):
    """The constitutional Projection Determinism Gate (ADR-0010 §3).

    Seed N events, deliver them once, snapshot the projection's owned
    rows, then call replay() and assert the new rows are byte-identical
    to the originals.
    """
    et = f"test.replay.{uuid.uuid4().hex[:6]}"
    proj = _PureProjection()
    proj.name = f"test.replay_proj_{uuid.uuid4().hex[:6]}"
    proj.event_glob = et
    handler = isolated_engine.register(proj)
    envs = await _insert_test_events(mongo_db, event_type=et, n=5)
    # Live deliver them (simulates the publisher loop).
    for env in envs:
        await handler(env)
    original = [e.to_doc() for e in proj.rows]
    assert len(original) == 5
    # Now wipe + replay.
    status = await isolated_engine.replay(proj.name)
    assert status.delivered_count == 5
    assert not status.rebuilding
    rebuilt = [e.to_doc() for e in proj.rows]
    assert rebuilt == original, "replay must produce byte-identical rows"


@pytest.mark.asyncio
async def test_replay_after_reset_full_state(isolated_engine, mongo_db):
    """Disposable rebuild: delete all projection rows, run replay,
    assert restored state matches pre-delete state."""
    et = f"test.dispose.{uuid.uuid4().hex[:6]}"
    proj = _PureProjection()
    proj.name = f"test.disposable_{uuid.uuid4().hex[:6]}"
    proj.event_glob = et
    handler = isolated_engine.register(proj)
    envs = await _insert_test_events(mongo_db, event_type=et, n=7)
    for env in envs:
        await handler(env)
    # Snapshot expected state.
    expected = list(proj.rows)
    # Wipe entirely (disposable).
    await proj.reset()
    assert proj.rows == []
    # Replay rebuilds.
    status = await isolated_engine.replay(proj.name)
    assert status.delivered_count == 7
    assert [e.event_id for e in proj.rows] == [e.event_id for e in expected]


@pytest.mark.asyncio
async def test_lag_metric_reflects_undelivered_events(isolated_engine,
                                                       mongo_db):
    """If 10 events are in the outbox and the engine has delivered 4,
    lag_events MUST be 6."""
    et = f"test.lag.{uuid.uuid4().hex[:6]}"
    proj = _PureProjection()
    proj.name = f"test.lag_proj_{uuid.uuid4().hex[:6]}"
    proj.event_glob = et
    handler = isolated_engine.register(proj)
    envs = await _insert_test_events(mongo_db, event_type=et, n=10)
    for env in envs[:4]:
        await handler(env)
    status = await isolated_engine.status(proj.name)
    assert status.delivered_count == 4
    assert status.lag_events == 6


@pytest.mark.asyncio
async def test_snapshot_records_baseline(isolated_engine, mongo_db):
    proj = _PureProjection()
    proj.name = f"test.snapshot_{uuid.uuid4().hex[:6]}"
    isolated_engine.register(proj)
    await isolated_engine.snapshot(proj.name)
    status = await isolated_engine.status(proj.name)
    assert status.last_snapshot_at is not None
    # ISO timestamp parse cleanly.
    datetime.fromisoformat(status.last_snapshot_at)


@pytest.mark.asyncio
async def test_status_for_unknown_projection_raises(isolated_engine):
    with pytest.raises(KeyError):
        await isolated_engine.status("does.not.exist")


# ============================================================================
# Admin router — auth + flow
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
async def admin_token(http_client, mongo_db):
    suffix = uuid.uuid4().hex[:8]
    email = f"p38_admin_{suffix}@example.com"
    await _register_and_login(http_client, email=email)
    await _grant_role(mongo_db, email, role="super_admin")
    r = await http_client.post("/api/v1/auth/login",
                                json={"email": email, "password": "TestPass123!"})
    return r.json()["access_token"]


@pytest_asyncio.fixture
async def field_token(http_client, mongo_db):
    suffix = uuid.uuid4().hex[:8]
    email = f"p38_field_{suffix}@example.com"
    await _register_and_login(http_client, email=email)
    await _grant_role(mongo_db, email, role="field_agent")
    r = await http_client.post("/api/v1/auth/login",
                                json={"email": email, "password": "TestPass123!"})
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_admin_projections_requires_auth(http_client):
    r = await http_client.get("/api/v1/admin/projections")
    assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_admin_projections_denies_non_super_admin(http_client,
                                                          field_token):
    r = await http_client.get("/api/v1/admin/projections",
                               headers=_hdr(field_token))
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_admin_projections_list_super_admin(http_client, admin_token):
    r = await http_client.get("/api/v1/admin/projections",
                               headers=_hdr(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    names = {p["name"] for p in body["projections"]}
    assert "evidence.timeline" in names, (
        "engine must register the evidence.timeline projection at startup")


@pytest.mark.asyncio
async def test_admin_projection_get_unknown_returns_404(http_client,
                                                          admin_token):
    r = await http_client.get("/api/v1/admin/projections/no.such.proj",
                               headers=_hdr(admin_token))
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_admin_projection_snapshot_records_timestamp(http_client,
                                                             admin_token):
    r = await http_client.post(
        "/api/v1/admin/projections/evidence.timeline/snapshot",
        headers=_hdr(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["last_snapshot_at"] is not None
    datetime.fromisoformat(body["last_snapshot_at"])


# ============================================================================
# Replay determinism — end-to-end through the production projection
# ============================================================================

@pytest.mark.asyncio
async def test_timeline_replay_is_byte_identical_end_to_end(http_client,
                                                              admin_token,
                                                              mongo_db):
    """End-to-end Projection Determinism Gate: trigger a real Phase
    3.4–3.6 pipeline, then wipe the timeline collections, replay, and
    assert byte-identical reconstruction.
    """
    # 1. Find an existing evidence item or seed a minimal one via the
    #    public API. We piggyback on the existing seal flow.
    suffix = uuid.uuid4().hex[:8]
    uploader_email = f"p38_uploader_{suffix}@example.com"
    await _register_and_login(http_client, email=uploader_email)
    await _grant_role(mongo_db, uploader_email, role="field_agent")
    up_t = (await http_client.post(
        "/api/v1/auth/login",
        json={"email": uploader_email, "password": "TestPass123!"}
    )).json()["access_token"]

    reg = (await http_client.post(
        "/api/v1/registry/landvaults", headers=_hdr(up_t),
        json={"state": "LAGOS", "lga": "IKEJA", "ward": "WARD8",
              "property_type": "RES", "ownership_type": "individual",
              "owner_name": "Phase38 Owner"})).json()["registry_id"]
    payload = b"phase38-bytes-" + uuid.uuid4().bytes
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
        "/api/v1/evidence/seals", headers=_hdr(admin_token),
        json={"registry_id": reg, "evidence_ids": [eid]})).json()
    sid = seal["seal_id"]
    await http_client.post(
        f"/api/v1/evidence/seals/{sid}/apply-worm",
        headers=_hdr(admin_token), json={})
    # Allow the projector to consume the events.
    await asyncio.sleep(2.5)

    # 2. Capture pre-replay state (timeline + custody collections).
    def _strip(doc):
        d = dict(doc)
        d.pop("_id", None)
        return d

    pre_timeline = sorted(
        [_strip(d) async for d in mongo_db["evidence_timeline"].find(
            {"evidence_id": eid})],
        key=lambda d: d["seq"])
    pre_custody = sorted(
        [_strip(d) async for d in mongo_db["evidence_custody"].find(
            {"evidence_id": eid})],
        key=lambda d: d["seq"])
    assert pre_timeline, "expected timeline rows from the live projector"

    # 3. Trigger replay via the admin endpoint.
    r = await http_client.post(
        "/api/v1/admin/projections/evidence.timeline/replay",
        headers=_hdr(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rebuilding"] is False

    # 4. Compare byte-for-byte.
    post_timeline = sorted(
        [_strip(d) async for d in mongo_db["evidence_timeline"].find(
            {"evidence_id": eid})],
        key=lambda d: d["seq"])
    post_custody = sorted(
        [_strip(d) async for d in mongo_db["evidence_custody"].find(
            {"evidence_id": eid})],
        key=lambda d: d["seq"])
    assert post_timeline == pre_timeline, (
        "Phase 3.8 determinism gate FAILED: timeline rebuild diverged.")
    assert post_custody == pre_custody, (
        "Phase 3.8 determinism gate FAILED: custody rebuild diverged.")


# ============================================================================
# Contract assertions
# ============================================================================

def test_contract_at_or_above_1_5_0() -> None:
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent.parent
    version = (root / "contracts" / "VERSION").read_text().strip()
    major, minor, _ = version.split(".")
    # Accept v1.5+ OR any v2+ — Phase 4 majors the contract.
    assert (int(major) == 1 and int(minor) >= 5) or int(major) >= 2, \
        f"got {version}"


def test_admin_projection_endpoints_in_openapi() -> None:
    """Every admin projection endpoint MUST appear in the live OpenAPI."""
    import httpx as _httpx
    r = _httpx.get(f"{API_URL_INTERNAL}/openapi.json", timeout=10)
    r.raise_for_status()
    spec = r.json()
    for path in (
        "/api/v1/admin/projections",
        "/api/v1/admin/projections/{name}",
        "/api/v1/admin/projections/{name}/replay",
        "/api/v1/admin/projections/{name}/snapshot",
    ):
        assert path in spec["paths"], f"missing {path}"
