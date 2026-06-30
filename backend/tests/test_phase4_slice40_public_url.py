"""Phase 4 Slice 4.0 — public-URL acceptance probe.

Exercises every acceptance bullet in the review_request through the
external REACT_APP_BACKEND_URL (i.e. what the user actually sees),
to confirm Kubernetes ingress + /api routing + PEP all line up.

Bullets covered here (in addition to the 29 in-process slice tests):
  - suspend then reactivate over HTTP
  - GET /workflow/timers + GET /workflow/tasks scoped lists
  - POST /workflow/admin/timers/{nonexistent}/fire → 404
  - POST /workflow/instances with nonexistent definition → 404
  - GET /api/v1/admin/projections lists both evidence.timeline and
    workflow.instance after an instance has been started
"""
from __future__ import annotations

import os
import uuid

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


def _register(email: str, password: str = "TestPass123!") -> dict:
    r = requests.post(
        f"{BASE_URL}/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "T1 Probe"},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def _login(email: str, password: str = "TestPass123!") -> str:
    r = requests.post(
        f"{BASE_URL}/api/v1/auth/login",
        json={"email": email, "password": password},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["access_token"]


async def _promote_super_admin(email: str) -> None:
    client = AsyncIOMotorClient(MONGO_URL)
    try:
        db = client[DB_NAME]
        await db.identity_users.update_one(
            {"email": email},
            {"$set": {"roles": ["super_admin"], "role": "super_admin"},
             "$inc": {"version": 1}},
        )
    finally:
        client.close()


@pytest.fixture(scope="module")
def super_admin_token() -> str:
    email = f"sa_probe_{uuid.uuid4().hex[:10]}@test.com"
    _register(email)
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_promote_super_admin(email))
    finally:
        loop.close()
    return _login(email)


@pytest.fixture(scope="module")
def plain_user_token() -> str:
    email = f"user_probe_{uuid.uuid4().hex[:10]}@test.com"
    _register(email)
    return _login(email)


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


# ---------------------------------------------------------------------------
# Auth & PEP
# ---------------------------------------------------------------------------

def test_definitions_unauthenticated_returns_401() -> None:
    r = requests.get(f"{BASE_URL}/api/v1/workflow/definitions", timeout=15)
    assert r.status_code == 401, r.text


def test_definitions_lists_echo_v1(super_admin_token: str) -> None:
    r = requests.get(
        f"{BASE_URL}/api/v1/workflow/definitions",
        headers=_h(super_admin_token),
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    items = body if isinstance(body, list) else body.get("items") or body.get("definitions") or []
    names = [d.get("name") for d in items]
    assert "echo.v1" in names, f"echo.v1 not in {names}"


def test_plain_user_cannot_start_instance(plain_user_token: str) -> None:
    r = requests.post(
        f"{BASE_URL}/api/v1/workflow/instances",
        headers=_h(plain_user_token),
        json={"definition_name": "echo.v1", "payload": {}},
        timeout=20,
    )
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# Lifecycle: start → tasks → claim → complete → cancel; suspend/reactivate
# ---------------------------------------------------------------------------

def _start_instance(token: str) -> dict:
    r = requests.post(
        f"{BASE_URL}/api/v1/workflow/instances",
        headers=_h(token),
        json={"definition_name": "echo.v1", "payload": {"probe": True}},
        timeout=20,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_start_instance_returns_received_state(super_admin_token: str) -> None:
    inst = _start_instance(super_admin_token)
    assert "instance_id" in inst
    assert inst.get("business_state") == "received"


def test_tasks_list_scoped(super_admin_token: str) -> None:
    inst = _start_instance(super_admin_token)
    r = requests.get(
        f"{BASE_URL}/api/v1/workflow/tasks",
        headers=_h(super_admin_token),
        params={"instance_id": inst["instance_id"]},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    items = body if isinstance(body, list) else body.get("items") or body.get("tasks") or []
    assert any(t.get("assigned_to_role") == "compliance_officer" for t in items), items


def test_timers_list_endpoint(super_admin_token: str) -> None:
    r = requests.get(
        f"{BASE_URL}/api/v1/workflow/timers",
        headers=_h(super_admin_token),
        timeout=15,
    )
    assert r.status_code == 200, r.text


def test_fire_nonexistent_timer_returns_404(super_admin_token: str) -> None:
    r = requests.post(
        f"{BASE_URL}/api/v1/workflow/admin/timers/{uuid.uuid4()}/fire",
        headers=_h(super_admin_token),
        timeout=15,
    )
    assert r.status_code == 404, r.text


def test_start_with_unknown_definition_returns_404(super_admin_token: str) -> None:
    r = requests.post(
        f"{BASE_URL}/api/v1/workflow/instances",
        headers=_h(super_admin_token),
        json={"definition_name": "nonexistent.v9", "payload": {}},
        timeout=15,
    )
    assert r.status_code == 404, r.text


def test_cancel_instance(super_admin_token: str) -> None:
    inst = _start_instance(super_admin_token)
    r = requests.post(
        f"{BASE_URL}/api/v1/workflow/instances/{inst['instance_id']}/cancel",
        headers=_h(super_admin_token),
        json={"reason": "probe"},
        timeout=15,
    )
    assert r.status_code in (200, 202), r.text
    body = r.json()
    assert body.get("lifecycle") in ("cancelled", "terminated"), body


def test_suspend_then_reactivate(super_admin_token: str) -> None:
    inst = _start_instance(super_admin_token)
    iid = inst["instance_id"]

    s = requests.post(
        f"{BASE_URL}/api/v1/workflow/instances/{iid}/suspend",
        headers=_h(super_admin_token),
        json={"reason": "probe"},
        timeout=15,
    )
    assert s.status_code in (200, 202), s.text
    assert s.json().get("lifecycle") == "suspended"

    rr = requests.post(
        f"{BASE_URL}/api/v1/workflow/instances/{iid}/reactivate",
        headers=_h(super_admin_token),
        json={},
        timeout=15,
    )
    assert rr.status_code in (200, 202), rr.text
    assert rr.json().get("lifecycle") == "running"


# ---------------------------------------------------------------------------
# Replay determinism + PEP on admin endpoints
# ---------------------------------------------------------------------------

def test_replay_matches_committed(super_admin_token: str) -> None:
    inst = _start_instance(super_admin_token)
    # Give the outbox publisher a moment to deliver the started event.
    import time
    time.sleep(3.0)
    r = requests.post(
        f"{BASE_URL}/api/v1/workflow/admin/instances/{inst['instance_id']}/replay",
        headers=_h(super_admin_token),
        timeout=20,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("matches_committed") is True, body


def test_replay_denied_to_plain_user(super_admin_token: str, plain_user_token: str) -> None:
    inst = _start_instance(super_admin_token)
    r = requests.post(
        f"{BASE_URL}/api/v1/workflow/admin/instances/{inst['instance_id']}/replay",
        headers=_h(plain_user_token),
        timeout=15,
    )
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# Projection coexistence with Phase 3
# ---------------------------------------------------------------------------

def test_admin_projections_lists_both(super_admin_token: str) -> None:
    _start_instance(super_admin_token)  # ensure workflow.instance has ≥1 event
    r = requests.get(
        f"{BASE_URL}/api/v1/admin/projections",
        headers=_h(super_admin_token),
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    items = body if isinstance(body, list) else body.get("items") or body.get("projections") or []
    names = {p.get("name") for p in items}
    assert "evidence.timeline" in names, names
    assert "workflow.instance" in names, names


def test_workflow_instance_projection_status(super_admin_token: str) -> None:
    _start_instance(super_admin_token)
    r = requests.get(
        f"{BASE_URL}/api/v1/admin/projections/workflow.instance",
        headers=_h(super_admin_token),
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    delivered = body.get("delivered_count") or body.get("delivered") or 0
    assert int(delivered) >= 1, body
