"""Tenant isolation regression tests.

Validates that the structural `tenant_id` injection enforced by
`core.safe_db.tdb` blocks every cross-tenant read/write attempt — even when a
caller crafts a request payload that targets another tenant's resource by ID.

These tests fork a brand-new tenant for each user via the dev-login endpoint
extension, create resources, then verify the other tenant cannot read them.
"""
from __future__ import annotations

import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _new_isolated_citizen():
    """Create a fresh citizen with a unique tenant_id via the bootstrap endpoint."""
    email = f"tenanttest_{uuid.uuid4().hex[:8]}@landvault.test"
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/test-bootstrap-citizen", json={"email": email}, timeout=15)
    assert r.status_code == 200, f"bootstrap failed: {r.status_code} {r.text}"
    data = r.json()
    s.headers.update({"Authorization": f"Bearer {data['session_token']}"})
    return s, data


@pytest.fixture(scope="module")
def tenant_a():
    return _new_isolated_citizen()


@pytest.fixture(scope="module")
def tenant_b():
    return _new_isolated_citizen()


class TestTenantIsolation:
    def test_distinct_tenants_assigned(self, tenant_a, tenant_b):
        _, da = tenant_a
        _, db = tenant_b
        assert da["user"]["tenant_id"] != db["user"]["tenant_id"]

    def test_parcel_invisible_across_tenants(self, tenant_a, tenant_b):
        sa, _ = tenant_a
        sb, _ = tenant_b

        # Tenant A creates a parcel
        body = {"community": f"ISO_A_{uuid.uuid4().hex[:6]}",
                "ward": "W", "lga": "L", "state": "Lagos"}
        ra = sa.post(f"{API}/parcels", json=body, timeout=30)
        assert ra.status_code == 200, ra.text
        parcel_a = ra.json()["parcel"]

        # Tenant A sees it
        ga = sa.get(f"{API}/parcels/{parcel_a['id']}", timeout=15)
        assert ga.status_code == 200
        assert ga.json()["parcel"]["id"] == parcel_a["id"]

        # Tenant B must NOT see it by direct id
        gb = sb.get(f"{API}/parcels/{parcel_a['id']}", timeout=15)
        assert gb.status_code == 404, (
            f"Tenant B was able to read Tenant A's parcel: {gb.status_code} {gb.text}"
        )

        # Tenant B's list must NOT include it
        lb = sb.get(f"{API}/parcels", timeout=15)
        assert lb.status_code == 200
        ids_b = {p["id"] for p in lb.json().get("items", [])}
        assert parcel_a["id"] not in ids_b, (
            "Tenant B listed Tenant A's parcel — tenant isolation broken!"
        )

    def test_evidence_isolated_across_tenants(self, tenant_a, tenant_b):
        sa, _ = tenant_a
        sb, _ = tenant_b
        # A creates a parcel then uploads evidence
        body = {"community": f"ISO_A2_{uuid.uuid4().hex[:6]}",
                "ward": "W", "lga": "L", "state": "Lagos"}
        ra = sa.post(f"{API}/parcels", json=body, timeout=30)
        assert ra.status_code == 200
        pid = ra.json()["parcel"]["id"]
        ev = sa.post(f"{API}/evidence", json={
            "parcel_id": pid,
            "evidence_type": "FAMILY_DOCUMENT",
            "file_url": "https://example.com/iso.pdf",
            "file_name": "iso.pdf",
        }, timeout=15)
        assert ev.status_code == 200, ev.text

        # B tries to attach evidence to A's parcel — must 404
        bad = sb.post(f"{API}/evidence", json={
            "parcel_id": pid,
            "evidence_type": "FAMILY_DOCUMENT",
            "file_url": "https://attacker.example.com/x.pdf",
            "file_name": "x.pdf",
        }, timeout=15)
        assert bad.status_code == 404, (
            f"Tenant B uploaded evidence to Tenant A's parcel: {bad.status_code} {bad.text}"
        )

        # B's dashboard timeline does NOT contain A's parcel events
        db_dash = sb.get(f"{API}/dashboard/citizen", timeout=15)
        assert db_dash.status_code == 200
        for p in db_dash.json().get("parcels", []):
            assert p["id"] != pid

    def test_credit_wallet_isolated(self, tenant_a, tenant_b):
        sa, _ = tenant_a
        sb, _ = tenant_b
        wa = sa.get(f"{API}/credits/balance", timeout=15).json()["wallet"]
        wb = sb.get(f"{API}/credits/balance", timeout=15).json()["wallet"]
        assert wa is not None and wb is not None
        assert wa["user_id"] != wb["user_id"]
        assert wa["tenant_id"] != wb["tenant_id"]

    def test_notifications_isolated(self, tenant_a, tenant_b):
        sa, _ = tenant_a
        sb, _ = tenant_b
        na = sa.get(f"{API}/notifications", timeout=15)
        nb = sb.get(f"{API}/notifications", timeout=15)
        assert na.status_code == 200 and nb.status_code == 200
        # All notifications belong to the respective tenant — they cannot overlap on a
        # per-parcel basis (each tenant only has its own parcels).
        # Best-effort: at minimum the lists are independently scoped.
        a_titles = {(n.get("id")) for n in na.json().get("items", [])}
        b_titles = {(n.get("id")) for n in nb.json().get("items", [])}
        # No notification id may appear in both feeds.
        assert not (a_titles & b_titles), (
            "Notification feeds overlap across tenants!"
        )
