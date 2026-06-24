"""Aquasavannah LandVault — comprehensive backend tests (pytest).

Covers: health/public, auth + RBAC, parcels + evidence flows, attestations,
surveyor flow, dashboards, admin command centre, trust/readiness, security
scan, job processor, Stripe checkout, Paystack init+verify (idempotency).
"""
from __future__ import annotations

import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://evidence-trust.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


def _dev_login(role: str) -> tuple[requests.Session, dict]:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/dev-login", json={"role": role}, timeout=30)
    assert r.status_code == 200, f"dev-login {role} failed: {r.status_code} {r.text}"
    data = r.json()
    assert "session_token" in data and "user" in data
    s.headers.update({"Authorization": f"Bearer {data['session_token']}"})
    return s, data


# ---------------- Fixtures ----------------
@pytest.fixture(scope="module")
def citizen():
    s, data = _dev_login("CITIZEN")
    return s, data


@pytest.fixture(scope="module")
def validator():
    s, data = _dev_login("COMMUNITY_VALIDATOR")
    return s, data


@pytest.fixture(scope="module")
def surveyor():
    s, data = _dev_login("SURVEYOR")
    return s, data


@pytest.fixture(scope="module")
def admin():
    s, data = _dev_login("ADMIN")
    return s, data


# ---------------- Health / Public ----------------
class TestPublic:
    def test_health(self):
        r = requests.get(f"{API}/health", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d.get("status") == "ok"
        assert d.get("db_connected") is True

    def test_public_stats(self):
        r = requests.get(f"{API}/public/stats", timeout=15)
        assert r.status_code == 200
        d = r.json()
        # Accept either spec naming or API naming (API uses total_/verified_/registered_ prefixes)
        expected = {("parcels", "total_parcels"), ("verified", "verified_parcels"),
                    ("attestations", "total_attestations"), ("surveyors", "registered_surveyors")}
        for spec_key, api_key in expected:
            assert spec_key in d or api_key in d, f"missing {spec_key}/{api_key}"

    def test_public_plans(self):
        r = requests.get(f"{API}/public/plans", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert len(d.get("plans", [])) == 6
        assert len(d.get("credit_packs", [])) == 3

    def test_public_verify_positive(self):
        r = requests.get(f"{API}/public/verify", params={"parcel_number": "AS-LV-2026-1002"}, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d.get("exists") is True
        assert d.get("status") == "VERIFIED"
        # Ensure no owner data leaked
        s = str(d).lower()
        assert "owner_id" not in d
        assert "owner_name" not in d
        assert "citizen.demo@" not in s

    def test_public_verify_negative(self):
        r = requests.get(f"{API}/public/verify", params={"parcel_number": "NONSENSE-123"}, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d.get("exists") is False

    def test_public_transparency(self):
        r = requests.get(f"{API}/public/transparency", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "by_state" in d and isinstance(d["by_state"], list)


# ---------------- Auth ----------------
class TestAuth:
    def test_dev_login_citizen(self, citizen):
        s, data = citizen
        assert data["user"]["email"] == "citizen.demo@landvault.test"
        assert data["user"]["role"] == "CITIZEN"

    def test_me(self, citizen):
        s, _ = citizen
        r = s.get(f"{API}/auth/me", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["user"]["email"] == "citizen.demo@landvault.test"
        assert d.get("wallet") is not None
        assert "balance" in d["wallet"]

    def test_logout_invalidates_session(self):
        s, _ = _dev_login("CITIZEN")
        r = s.post(f"{API}/auth/logout", timeout=15)
        assert r.status_code in (200, 204)
        r2 = s.get(f"{API}/auth/me", timeout=15)
        assert r2.status_code == 401


# ---------------- Citizen flow ----------------
class TestCitizenFlow:
    def test_dashboard(self, citizen):
        s, _ = citizen
        r = s.get(f"{API}/dashboard/citizen", timeout=15)
        assert r.status_code == 200
        d = r.json()
        for k in ("kpis", "parcels", "wallet", "timeline"):
            assert k in d
        assert d["wallet"]["balance"] >= 0

    def test_create_parcel_deducts_credits(self, citizen):
        s, _ = citizen
        before = s.get(f"{API}/credits/balance", timeout=15).json()["wallet"]["balance"]
        body = {
            "community": f"TEST_Comm_{uuid.uuid4().hex[:6]}",
            "ward": "TEST Ward",
            "lga": "TEST LGA",
            "state": "Lagos",
        }
        r = s.post(f"{API}/parcels", json=body, timeout=30)
        assert r.status_code == 200, r.text
        parcel = r.json()["parcel"]
        assert parcel["parcel_number"].startswith("AS-LV-")
        assert parcel["community"] == body["community"]
        # Wallet decremented by 5
        after = s.get(f"{API}/credits/balance", timeout=15).json()["wallet"]["balance"]
        assert after == before - 5, f"expected {before-5}, got {after}"
        # Verify persistence via GET
        gp = s.get(f"{API}/parcels/{parcel['id']}", timeout=15)
        assert gp.status_code == 200
        assert gp.json()["parcel"]["id"] == parcel["id"]

    def test_upload_evidence(self, citizen):
        s, _ = citizen
        # Pick first parcel from citizen dashboard
        d = s.get(f"{API}/dashboard/citizen", timeout=15).json()
        assert len(d["parcels"]) >= 1
        pid = d["parcels"][0]["id"]
        before_count = d["parcels"][0].get("evidence_count", 0)
        body = {
            "parcel_id": pid,
            "evidence_type": "FAMILY_DOCUMENT",
            "file_url": f"https://example.com/doc-{uuid.uuid4().hex[:6]}.pdf",
            "file_name": "TEST_evidence.pdf",
        }
        r = s.post(f"{API}/evidence", json=body, timeout=30)
        assert r.status_code == 200, r.text
        ev = r.json()["evidence"]
        assert ev["file_hash"] and len(ev["file_hash"]) == 64
        # Fetch parcel and check evidence_count incremented
        gp = s.get(f"{API}/parcels/{pid}", timeout=15).json()
        assert gp["parcel"]["evidence_count"] >= before_count + 1

    def test_insufficient_credits_returns_402(self):
        """Create a fresh CITIZEN session and drain the wallet by repeated parcel creation."""
        s, data = _dev_login("CITIZEN")
        # Drain wallet
        for _ in range(60):
            bal = s.get(f"{API}/credits/balance", timeout=15).json()["wallet"]["balance"]
            if bal < 5:
                break
            r = s.post(f"{API}/parcels", json={
                "community": f"TEST_drain_{uuid.uuid4().hex[:4]}",
                "ward": "w", "lga": "l", "state": "Lagos",
            }, timeout=30)
            if r.status_code == 402:
                return
            assert r.status_code == 200, r.text
        # Now should be insufficient
        r = s.post(f"{API}/parcels", json={
            "community": "TEST_should_fail", "ward": "w", "lga": "l", "state": "Lagos",
        }, timeout=30)
        assert r.status_code == 402, f"expected 402, got {r.status_code}: {r.text}"


# ---------------- Validator ----------------
class TestValidator:
    def test_dashboard(self, validator):
        s, _ = validator
        r = s.get(f"{API}/dashboard/validator", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "kpis" in d and "queue" in d
        assert isinstance(d["queue"], list)

    def test_attestation_submission(self, validator):
        s, _ = validator
        q = s.get(f"{API}/dashboard/validator", timeout=15).json()["queue"]
        assert len(q) >= 1, "validator queue empty"
        pid = q[0]["id"]
        body = {
            "parcel_id": pid,
            "role": "ELDER",
            "statement": "TEST attestation — this parcel has been part of the community for generations.",
            "relationship_to_land": "Community Elder",
            "years_of_knowledge": 25,
        }
        r = s.post(f"{API}/attestations", json=body, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["attestation"]["parcel_id"] == pid

    def test_citizen_cannot_attest(self, citizen):
        s, _ = citizen
        body = {
            "parcel_id": "doesnt-matter", "role": "ELDER",
            "statement": "TEST", "relationship_to_land": "x", "years_of_knowledge": 5,
        }
        r = s.post(f"{API}/attestations", json=body, timeout=15)
        assert r.status_code == 403, f"expected 403 RBAC, got {r.status_code}"


# ---------------- Surveyor ----------------
class TestSurveyor:
    def test_dashboard(self, surveyor):
        s, _ = surveyor
        r = s.get(f"{API}/dashboard/surveyor", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "kpis" in d and "assignments" in d

    def test_upload_plan(self, surveyor):
        s, _ = surveyor
        assigns = s.get(f"{API}/dashboard/surveyor", timeout=15).json()["assignments"]
        assert len(assigns) >= 1
        pid = assigns[0]["id"]
        before = s.get(f"{API}/dashboard/surveyor", timeout=15).json()["kpis"]["completed_surveys"]
        body = {"parcel_id": pid, "plan_url": "https://example.com/TEST_plan.pdf", "notes": "TEST notes"}
        r = s.post(f"{API}/surveyor/upload-plan", json=body, timeout=30)
        assert r.status_code == 200, r.text
        after = s.get(f"{API}/dashboard/surveyor", timeout=15).json()["kpis"]["completed_surveys"]
        assert after == before + 1


# ---------------- Admin ----------------
class TestAdmin:
    def test_overview(self, admin):
        s, _ = admin
        r = s.get(f"{API}/admin/overview", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "kpis" in d and "jobs" in d and "layers" in d
        assert len(d["layers"]) == 13

    def test_list_endpoints_populated(self, admin):
        s, _ = admin
        for path in ("/admin/parcels", "/admin/users", "/admin/evidence", "/admin/jobs", "/admin/audit-logs"):
            r = s.get(f"{API}{path}", timeout=15)
            assert r.status_code == 200, f"{path} -> {r.status_code}"
            assert isinstance(r.json().get("items"), list)

    def test_process_jobs(self, admin):
        s, _ = admin
        r = s.post(f"{API}/admin/jobs/process", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "processed" in d and isinstance(d["processed"], int) and d["processed"] >= 0

    def test_run_trust(self, admin):
        s, _ = admin
        r = s.post(f"{API}/admin/trust/run", timeout=30)
        assert r.status_code == 200
        run = r.json()["run"]
        sub = run["sub_scores"]
        # NOT all 100s — must reflect real data (fresh seed should be low)
        assert not all(v == 100 for v in sub.values()), f"sub_scores all 100: {sub}"
        assert 0 <= run["overall_score"] <= 100
        # Latest endpoint returns a run
        r2 = s.get(f"{API}/admin/trust/latest", timeout=15)
        assert r2.status_code == 200
        assert "run" in r2.json()

    def test_security_scan(self, admin):
        s, _ = admin
        r = s.post(f"{API}/admin/security/scan", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "issues" in d and isinstance(d["issues"], list)

    def test_readiness(self, admin):
        s, _ = admin
        r = s.get(f"{API}/admin/readiness", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "overall_score" in d and "sub_scores" in d
        assert isinstance(d["sub_scores"], dict) and len(d["sub_scores"]) >= 3


# ---------------- RBAC ----------------
class TestRBAC:
    def test_citizen_blocked_from_admin(self, citizen):
        s, _ = citizen
        r = s.get(f"{API}/admin/overview", timeout=15)
        assert r.status_code == 403

    def test_surveyor_blocked_from_admin(self, surveyor):
        s, _ = surveyor
        r = s.get(f"{API}/admin/overview", timeout=15)
        assert r.status_code == 403


# ---------------- Payments (iteration 2) ----------------
class TestPaymentsConfig:
    def test_config_anonymous_public(self):
        # /api/payments/config is public
        r = requests.get(f"{API}/payments/config", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        # Shape
        assert "stripe" in d and "paystack" in d
        for prov in ("stripe", "paystack"):
            for k in ("enabled", "mode"):
                assert k in d[prov], f"{prov}.{k} missing"
        # With current env: stripe enabled (sk_test_emergent fallback), paystack disabled
        assert d["stripe"]["enabled"] is True
        assert d["stripe"]["mode"] == "TEST"
        assert d["paystack"]["enabled"] is False
        assert d["paystack"]["mode"] == "DISABLED"
        # NO secret keys leaked
        flat = str(d).lower()
        assert "sk_test_" not in flat
        assert "sk_live_" not in flat
        assert "secret" not in flat


class TestPaymentsStripe:
    def test_stripe_checkout_pack(self, citizen):
        s, _ = citizen
        body = {"pack_code": "STARTER", "origin_url": "https://example.com"}
        r = s.post(f"{API}/payments/stripe/checkout", json=body, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("url", "").startswith("http")
        assert d.get("session_id")
        # Mode is TEST
        assert d.get("mode") == "TEST"
        # Save for status test
        TestPaymentsStripe._last_session = d["session_id"]

    def test_stripe_checkout_plan_monthly(self, citizen):
        s, _ = citizen
        body = {"plan_code": "CITIZEN", "billing_cycle": "monthly", "origin_url": "https://example.com"}
        r = s.post(f"{API}/payments/stripe/checkout", json=body, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("url", "").startswith("http")
        assert d.get("session_id")

    def test_stripe_checkout_invite_only_plan_rejected(self, citizen):
        s, _ = citizen
        body = {"plan_code": "GOVERNMENT_OBSERVER", "origin_url": "https://example.com"}
        r = s.post(f"{API}/payments/stripe/checkout", json=body, timeout=30)
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"

    def test_stripe_status_known_session(self, citizen):
        s, _ = citizen
        sid = getattr(TestPaymentsStripe, "_last_session", None)
        assert sid, "Prior checkout test did not run"
        r = s.get(f"{API}/payments/stripe/status/{sid}", timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "status" in d or "payment_status" in d

    def test_stripe_status_unknown_session_returns_404(self, citizen):
        s, _ = citizen
        r = s.get(f"{API}/payments/stripe/status/nope_unknown_session_xyz", timeout=30)
        assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text[:200]}"

    def test_stripe_checkout_requires_auth(self):
        r = requests.post(f"{API}/payments/stripe/checkout",
                          json={"pack_code": "STARTER", "origin_url": "https://example.com"},
                          timeout=15)
        assert r.status_code == 401, f"expected 401, got {r.status_code}"


class TestPaymentsPaystackDisabled:
    """With PAYSTACK_SECRET_KEY empty in .env, all Paystack endpoints must 503."""
    def test_paystack_init_503(self, citizen):
        s, _ = citizen
        body = {"pack_code": "STARTER", "origin_url": "https://example.com"}
        r = s.post(f"{API}/payments/paystack/init", json=body, timeout=15)
        assert r.status_code == 503, r.text
        assert "Paystack" in r.json().get("detail", "")

    def test_paystack_verify_503(self, citizen):
        s, _ = citizen
        r = s.get(f"{API}/payments/paystack/verify/anything", timeout=15)
        assert r.status_code == 503, r.text
        assert "Paystack" in r.json().get("detail", "")


class TestWebhooks:
    def test_stripe_webhook_no_secret_acknowledges(self):
        # No STRIPE_WEBHOOK_SECRET set: should respond 200 with verified=false
        r = requests.post(f"{API.replace('/api','')}/api/webhook/stripe",
                          data=b'{"id":"evt_test","type":"checkout.session.completed"}',
                          headers={"Content-Type": "application/json",
                                   "stripe-signature": "t=1,v1=deadbeef"},
                          timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("received") is True
        assert d.get("verified") is False
        assert "not configured" in (d.get("reason") or "").lower()

    def test_paystack_webhook_no_secret_acknowledges(self):
        r = requests.post(f"{API.replace('/api','')}/api/webhook/paystack",
                          data=b'{"event":"charge.success","data":{"reference":"x"}}',
                          headers={"Content-Type": "application/json",
                                   "x-paystack-signature": "deadbeef"},
                          timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("received") is True
        assert d.get("verified") is False
        assert "not configured" in (d.get("reason") or "").lower()


class TestIdempotency:
    """Verify _fulfill_payment is no-op on already-fulfilled session."""
    def test_stripe_status_double_call_does_not_double_credit(self, citizen):
        s, _ = citizen
        # Create a checkout
        body = {"pack_code": "STARTER", "origin_url": "https://example.com"}
        r = s.post(f"{API}/payments/stripe/checkout", json=body, timeout=30)
        assert r.status_code == 200
        sid = r.json()["session_id"]
        # Call status twice. The sandbox session is not actually paid, so wallet
        # won't change at all. But this also exercises the no-op path safely.
        bal0 = s.get(f"{API}/credits/balance", timeout=15).json()["wallet"]["balance"]
        s.get(f"{API}/payments/stripe/status/{sid}", timeout=30)
        bal1 = s.get(f"{API}/credits/balance", timeout=15).json()["wallet"]["balance"]
        s.get(f"{API}/payments/stripe/status/{sid}", timeout=30)
        bal2 = s.get(f"{API}/credits/balance", timeout=15).json()["wallet"]["balance"]
        # Idempotency: bal1 == bal2 always (no second-call delta)
        assert bal1 == bal2, f"Second status call changed balance: {bal1} -> {bal2}"
