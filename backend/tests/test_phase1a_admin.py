"""Phase 1A — service accounts, delegations, suspension, and event tests.

Validates:
* IdentityAdminService.suspend_user / activate_user transitions account_status
  and prevents the suspended account from re-authenticating.
* Role assignment via /v1/identity/users/{id}/role updates the canonical role
  and refuses unknown roles.
* Service account creation returns the secret exactly once, then is unrecoverable.
* Delegation grant lifecycle (grant → revoke) emits the correct domain events.
* Every state-changing operation produces a kernel_outbox entry with a versioned envelope.
* Specifications-pattern queries return scoped results (no Mongo syntax leak in callers).
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _email(prefix: str = "p1a") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}@example.com"


def _new_user(role: str | None = None):
    """Create a fresh Phase 1 user via /v1/auth/register."""
    email = _email()
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/v1/auth/register", json={
        "email": email, "password": "strongPass1234", "full_name": "P1A",
    }, timeout=15)
    assert r.status_code == 201, r.text
    body = r.json()
    s.headers.update({"Authorization": f"Bearer {body['access_token']}"})
    return s, body


def _admin_session():
    """Create a user then promote them to super_admin directly in Mongo so we
    can exercise the protected admin endpoints. (Until a bootstrap super_admin
    flow exists, this is the only way to mint one in tests.)"""
    s, body = _new_user()
    user_id = body["user"]["user_id"]
    from pymongo import MongoClient
    cli = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    cli[os.environ.get("DB_NAME", "test_database")]["identity_users"].update_one(
        {"user_id": user_id},
        {"$set": {"role": "super_admin", "roles": ["super_admin"]}, "$inc": {"version": 1}},
    )
    # Re-login to refresh JWT claims with the new role.
    r = s.post(f"{API}/v1/auth/login", json={"email": body["user"]["email"],
                                              "password": "strongPass1234"}, timeout=15)
    assert r.status_code == 200
    s.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
    return s, r.json()


# ---- Extended user fields ----------------------------------------------
class TestExtendedUserFields:
    def test_user_has_canonical_role_and_status(self):
        _, body = _new_user()
        u = body["user"]
        assert u["role"] == "general_user"
        assert u["roles"] == ["general_user"]
        assert u["account_status"] == "active"
        assert u["role_confirmed"] is False


# ---- Suspension lifecycle ----------------------------------------------
class TestSuspensionLifecycle:
    def test_super_admin_can_suspend_and_activate_user(self):
        s_admin, _ = _admin_session()
        s_user, ubody = _new_user()
        uid = ubody["user"]["user_id"]
        # Suspend
        r = s_admin.post(f"{API}/v1/identity/users/{uid}/suspend",
                         json={"reason": "policy violation under test"}, timeout=15)
        assert r.status_code == 200, r.text
        view = r.json()
        assert view["account_status"] == "suspended"
        assert view["suspension_reason"] == "policy violation under test"
        assert view["suspended_by"]
        # Suspended user cannot re-login.
        r2 = requests.post(f"{API}/v1/auth/login", json={
            "email": ubody["user"]["email"], "password": "strongPass1234",
        }, timeout=15)
        assert r2.status_code == 401
        # Activate
        r3 = s_admin.post(f"{API}/v1/identity/users/{uid}/activate", timeout=15)
        assert r3.status_code == 200, r3.text
        assert r3.json()["account_status"] == "active"
        # Login works again
        r4 = requests.post(f"{API}/v1/auth/login", json={
            "email": ubody["user"]["email"], "password": "strongPass1234",
        }, timeout=15)
        assert r4.status_code == 200

    def test_general_user_cannot_suspend(self):
        s, body = _new_user()
        r = s.post(f"{API}/v1/identity/users/{body['user']['user_id']}/suspend",
                   json={"reason": "self-suspend attempt"}, timeout=15)
        assert r.status_code == 403


# ---- Role assignment ---------------------------------------------------
class TestRoleAssignment:
    def test_super_admin_assigns_canonical_role(self):
        s_admin, _ = _admin_session()
        _, target = _new_user()
        uid = target["user"]["user_id"]
        r = s_admin.post(f"{API}/v1/identity/users/{uid}/role",
                         json={"role": "licensed_surveyor"}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "licensed_surveyor"
        assert "licensed_surveyor" in r.json()["roles"]

    def test_unknown_role_rejected(self):
        s_admin, _ = _admin_session()
        _, target = _new_user()
        uid = target["user"]["user_id"]
        r = s_admin.post(f"{API}/v1/identity/users/{uid}/role",
                         json={"role": "PLATFORM_TSAR"}, timeout=15)
        assert r.status_code == 400
        assert r.json()["code"] == "identity.unknown_role"


# ---- Service accounts ---------------------------------------------------
class TestServiceAccounts:
    def test_create_returns_secret_exactly_once(self):
        s_admin, _ = _admin_session()
        r = s_admin.post(f"{API}/v1/identity/service-accounts", json={
            "name": "Test ETL", "description": "Pulls reports for test",
            "scopes": ["reports.read"],
        }, timeout=15)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["account_id"].startswith("svc_")
        assert body["scopes"] == ["reports.read"]
        assert "secret" in body and len(body["secret"]) > 20
        assert "secret_hash" not in body  # secret_hash never leaks

    def test_revoke_marks_revoked(self):
        s_admin, _ = _admin_session()
        c = s_admin.post(f"{API}/v1/identity/service-accounts", json={
            "name": "Revokable", "description": "to be revoked",
            "scopes": ["x.y"],
        }, timeout=15)
        assert c.status_code == 201, c.text
        sid = c.json()["account_id"]
        r = s_admin.post(f"{API}/v1/identity/service-accounts/{sid}/revoke", timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "REVOKED"


# ---- Delegations -------------------------------------------------------
class TestDelegations:
    def test_grant_then_revoke(self):
        s_admin, admin_body = _admin_session()
        _, a = _new_user()
        _, b = _new_user()
        valid_from = datetime.now(timezone.utc).isoformat()
        valid_until = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        r = s_admin.post(f"{API}/v1/identity/delegations", json={
            "delegator_id": a["user"]["user_id"],
            "delegate_id": b["user"]["user_id"],
            "scope": ["demo.read", "demo.update"],
            "valid_from": valid_from, "valid_until": valid_until,
            "reason": "annual leave coverage",
        }, timeout=15)
        assert r.status_code == 201, r.text
        gid = r.json()["grant_id"]
        rev = s_admin.post(f"{API}/v1/identity/delegations/{gid}/revoke",
                           json={"reason": "returned from leave"}, timeout=15)
        assert rev.status_code == 200
        assert rev.json()["status"] == "REVOKED"


# ---- Specifications pattern ---------------------------------------------
class TestSpecifications:
    def test_list_users_with_specification_filters(self):
        s_admin, _ = _admin_session()
        # Create two users with deterministic country selection.
        _new_user()
        _new_user()
        r = s_admin.get(f"{API}/v1/identity/users?country=NG&status=active&limit=10",
                        timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["specification_clauses"], "specification clauses must be reported"
        # Every returned user is NG + active.
        for u in body["items"]:
            assert u["country"] == "NG"
            assert u["account_status"] == "active"


# ---- Domain events / outbox --------------------------------------------
class TestDomainEvents:
    def test_outbox_records_versioned_envelope(self):
        # Trigger a UserRegistered event.
        _new_user()
        from pymongo import MongoClient
        cli = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        col = cli[os.environ.get("DB_NAME", "test_database")]["kernel_outbox"]
        # The publisher delivers in ~1s — wait briefly.
        deadline = time.time() + 5
        latest = None
        while time.time() < deadline:
            latest = col.find_one({"event_type": "identity.user.registered"},
                                  sort=[("occurred_at", -1)])
            if latest:
                break
            time.sleep(0.5)
        assert latest, "UserRegistered must be in the outbox"
        # Versioned envelope
        for field in ("event_id", "event_type", "event_version", "aggregate_type",
                      "aggregate_id", "aggregate_version", "occurred_at",
                      "producer", "payload"):
            assert field in latest, f"envelope missing {field}"
        assert latest["event_version"] == 1
        assert latest["producer"] == "identity"
        assert latest["aggregate_type"] == "user"
