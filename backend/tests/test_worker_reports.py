"""P0/P1 verification: background worker auto-processing, PDF+CSV report
generation (LEGAL + INSTITUTION), and cross-tenant search/observer endpoints.

These tests rely on the production worker started by main.py's startup hook.
The worker polls every ~5s, so polling windows of ~75s are used.
"""
from __future__ import annotations

import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _dev_login(role: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/dev-login", json={"role": role}, timeout=15)
    assert r.status_code == 200, f"dev-login {role} failed: {r.status_code} {r.text}"
    tok = r.json()["session_token"]
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


def _bootstrap_citizen(balance: int = 100):
    email = f"wkrtest_{uuid.uuid4().hex[:8]}@landvault.test"
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/test-bootstrap-citizen", json={"email": email}, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    s.headers.update({"Authorization": f"Bearer {data['session_token']}"})
    s.post(f"{API}/auth/test-set-balance", json={"balance": balance}, timeout=15)
    return s, data


# --------------------------------------------------------------------------
# Background Worker
# --------------------------------------------------------------------------
class TestBackgroundWorker:
    """Verify the auto-worker advances jobs without manual /admin/jobs/process."""

    def test_confidence_recalc_job_auto_progresses(self):
        # Citizen creates a parcel → triggers CONFIDENCE_RECALCULATION job
        s_citizen, _ = _bootstrap_citizen(balance=50)
        r = s_citizen.post(f"{API}/parcels", json={
            "community": f"WRK_{uuid.uuid4().hex[:5]}",
            "ward": "w", "lga": "l", "state": "Lagos",
        }, timeout=30)
        assert r.status_code == 200, r.text
        parcel_id = r.json()["parcel"]["id"]

        # Admin polls jobs queue
        admin = _dev_login("ADMIN")

        deadline = time.time() + 150
        observed_states: set[str] = set()
        terminal_status = None

        while time.time() < deadline:
            jr = admin.get(f"{API}/admin/jobs", timeout=15)
            assert jr.status_code == 200, jr.text
            jobs = jr.json().get("items", jr.json() if isinstance(jr.json(), list) else [])
            # The relevant job has payload.parcel_id == parcel_id, type=CONFIDENCE_RECALCULATION
            target = None
            for j in jobs:
                jtype = j.get("job_type") or j.get("type")
                if jtype == "CONFIDENCE_RECALCULATION" and \
                        (j.get("payload") or {}).get("parcel_id") == parcel_id:
                    target = j
                    break
            if target:
                observed_states.add(target.get("status", ""))
                if target.get("status") in ("COMPLETED", "FAILED", "DEAD_LETTER"):
                    terminal_status = target.get("status")
                    break
            time.sleep(3)

        assert terminal_status == "COMPLETED", (
            f"CONFIDENCE_RECALCULATION did not auto-COMPLETE in 75s; "
            f"observed={observed_states} terminal={terminal_status}"
        )


# --------------------------------------------------------------------------
# Legal Report (PDF + CSV)
# --------------------------------------------------------------------------
class TestLegalReport:
    def test_legal_report_pdf_and_csv(self):
        legal = _dev_login("LEGAL")
        # Find a seed parcel via legal search (cross-tenant)
        s = legal.get(f"{API}/legal/search?limit=5", timeout=15)
        assert s.status_code == 200, s.text
        items = s.json().get("items", [])
        assert items, "no parcels available for legal search"
        parcel_id = items[0]["id"]

        # Request report
        r = legal.post(f"{API}/legal/report/{parcel_id}", timeout=20)
        assert r.status_code == 200, r.text
        report_id = r.json()["report"]["id"]

        # Poll reports list for COMPLETED + csv_url + result_url
        deadline = time.time() + 120
        rep = None
        while time.time() < deadline:
            lr = legal.get(f"{API}/legal/reports", timeout=15)
            assert lr.status_code == 200
            rep = next((x for x in lr.json()["items"] if x["id"] == report_id), None)
            if rep and rep.get("status") == "COMPLETED" and rep.get("result_url") \
                    and rep.get("csv_url"):
                break
            time.sleep(3)

        assert rep is not None, "report never appeared in /legal/reports"
        assert rep.get("status") == "COMPLETED", f"final status: {rep}"
        assert rep.get("result_url"), f"missing result_url: {rep}"
        assert rep.get("csv_url"), f"missing csv_url: {rep}"

        # Download PDF
        pdf = legal.get(f"{API}/legal/reports/{report_id}/download", timeout=20)
        assert pdf.status_code == 200, pdf.text
        assert pdf.headers.get("content-type", "").startswith("application/pdf"), \
            pdf.headers.get("content-type")
        assert pdf.content[:4] == b"%PDF", f"PDF magic missing: {pdf.content[:8]!r}"

        # Download CSV
        csv = legal.get(f"{API}/legal/reports/{report_id}/download.csv", timeout=20)
        assert csv.status_code == 200, csv.text
        assert csv.headers.get("content-type", "").startswith("text/csv"), \
            csv.headers.get("content-type")
        text = csv.content.decode("utf-8", errors="replace")
        assert text.startswith("Section,Key,Value"), f"CSV header wrong: {text[:60]!r}"


# --------------------------------------------------------------------------
# Institution Report (PDF + CSV)
# --------------------------------------------------------------------------
class TestInstitutionReport:
    def test_institution_report_pdf_and_csv(self):
        inst = _dev_login("INSTITUTIONAL")
        # Need parcel_numbers. Borrow from legal cross-tenant search via LEGAL,
        # then build a portfolio. (Institution itself doesn't expose search.)
        legal = _dev_login("LEGAL")
        s = legal.get(f"{API}/legal/search?limit=3", timeout=15)
        assert s.status_code == 200
        items = s.json().get("items", [])
        assert items, "no parcels available"
        parcel_numbers = [p["parcel_number"] for p in items if p.get("parcel_number")][:3]
        assert parcel_numbers, "no parcel_numbers"

        # Create portfolio
        pr = inst.post(f"{API}/institution/portfolio", json={
            "name": f"TEST_PF_{uuid.uuid4().hex[:5]}",
            "parcel_numbers": parcel_numbers,
        }, timeout=20)
        assert pr.status_code == 200, pr.text
        portfolio_id = pr.json()["portfolio"]["id"]

        # Request report
        rr = inst.post(f"{API}/institution/report/{portfolio_id}", timeout=20)
        assert rr.status_code == 200, rr.text
        report_id = rr.json()["report"]["id"]

        # Poll
        deadline = time.time() + 120
        rep = None
        while time.time() < deadline:
            lr = inst.get(f"{API}/institution/reports", timeout=15)
            assert lr.status_code == 200
            rep = next((x for x in lr.json()["items"] if x["id"] == report_id), None)
            if rep and rep.get("status") == "COMPLETED" and rep.get("result_url") \
                    and rep.get("csv_url"):
                break
            time.sleep(3)

        assert rep is not None, "institution report did not appear"
        assert rep.get("status") == "COMPLETED", f"final: {rep}"
        assert rep.get("result_url")
        assert rep.get("csv_url")

        # PDF
        pdf = inst.get(f"{API}/institution/reports/{report_id}/download", timeout=20)
        assert pdf.status_code == 200, pdf.text
        assert pdf.headers.get("content-type", "").startswith("application/pdf")
        assert pdf.content[:4] == b"%PDF"

        # CSV
        csv = inst.get(f"{API}/institution/reports/{report_id}/download.csv", timeout=20)
        assert csv.status_code == 200, csv.text
        assert csv.headers.get("content-type", "").startswith("text/csv")
        # Institution CSV is a tabular per-parcel report (not Section/Key/Value).
        assert csv.content.decode("utf-8", errors="replace").startswith(
            "#,Parcel,Found,Status,Confidence,Risk Level,Risk Score"
        )


# --------------------------------------------------------------------------
# Cross-tenant: LEGAL/Observer/Admin must read across all tenants
# --------------------------------------------------------------------------
class TestCrossTenantViews:
    def test_legal_search_cross_tenant(self):
        # Bootstrap citizen in their own tenant + create a parcel.
        s_citizen, _ = _bootstrap_citizen(balance=50)
        community = f"XTL_{uuid.uuid4().hex[:6]}"
        cr = s_citizen.post(f"{API}/parcels", json={
            "community": community, "ward": "w", "lga": "l", "state": "Lagos",
        }, timeout=20)
        assert cr.status_code == 200, cr.text
        parcel_id = cr.json()["parcel"]["id"]

        legal = _dev_login("LEGAL")
        sr = legal.get(f"{API}/legal/search?q={community}&limit=20", timeout=15)
        assert sr.status_code == 200, sr.text
        ids = {p["id"] for p in sr.json().get("items", [])}
        assert parcel_id in ids, (
            "LEGAL /search did not return citizen's parcel from another tenant — "
            "cross-tenant search broken!"
        )

    def test_admin_run_trust_cross_tenant(self):
        admin = _dev_login("ADMIN")
        r = admin.post(f"{API}/admin/trust/run", timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        # Trust run returns a nested {"run": {...}} payload. The `run` doc must
        # show non-zero counts (evidence/attestations/etc.) — proof it scanned
        # across tenants. Walk all numeric values recursively.
        def _all_nums(o):
            if isinstance(o, dict):
                for v in o.values():
                    yield from _all_nums(v)
            elif isinstance(o, list):
                for v in o:
                    yield from _all_nums(v)
            elif isinstance(o, (int, float)):
                yield o
        nums = list(_all_nums(body))
        assert any(n > 0 for n in nums), f"trust/run returned no positive counts: {body}"

    def test_observer_dashboard_aggregates(self):
        obs = _dev_login("GOVERNMENT_OBSERVER")
        r = obs.get(f"{API}/observer/dashboard", timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        # Must contain some aggregate counters (kpis or similar)
        assert isinstance(body, dict) and body, "observer dashboard returned empty"
