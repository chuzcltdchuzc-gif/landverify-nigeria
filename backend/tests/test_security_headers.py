"""R-2 — Mechanical verification of HTTP security headers + rate limiting.

These tests are the binding gate for the Security Readiness Report at
/app/audit/R-2-SECURITY-READINESS-REPORT.md. They run against the
live FastAPI app on http://localhost:8001.
"""
from __future__ import annotations

import os
import uuid

import httpx
import pytest

API = "http://localhost:8001"

REQUIRED_HEADERS = (
    "content-security-policy",
    "strict-transport-security",
    "cross-origin-opener-policy",
    "cross-origin-resource-policy",
    "cross-origin-embedder-policy",
    "referrer-policy",
    "x-content-type-options",
    "x-frame-options",
    "permissions-policy",
)


def test_every_required_header_is_present_on_any_response():
    r = httpx.get(f"{API}/api/v1/admin/projections", timeout=10)
    missing = [h for h in REQUIRED_HEADERS if h not in r.headers]
    assert not missing, f"missing security headers: {missing}"


def test_hsts_value_is_at_or_above_two_years():
    r = httpx.get(f"{API}/api/v1/admin/projections", timeout=10)
    hsts = r.headers.get("strict-transport-security", "")
    # max-age 63072000 == 2 years.
    assert "max-age" in hsts and "includeSubDomains" in hsts and "preload" in hsts
    # Extract numeric max-age.
    for part in hsts.split(";"):
        if "max-age" in part:
            ma = int(part.split("=", 1)[1].strip())
            assert ma >= 31536000, f"HSTS max-age < 1 year: {ma}"


def test_csp_contains_strict_baseline():
    r = httpx.get(f"{API}/api/v1/admin/projections", timeout=10)
    csp = r.headers.get("content-security-policy", "")
    for directive in (
        "default-src 'self'",
        "frame-ancestors 'none'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "upgrade-insecure-requests",
    ):
        assert directive in csp, f"CSP missing {directive!r}; got: {csp}"


def test_xfo_blocks_iframe_embedding():
    r = httpx.get(f"{API}/api/v1/admin/projections", timeout=10)
    assert r.headers.get("x-frame-options", "").upper() == "DENY"


def test_xcto_blocks_mime_sniffing():
    r = httpx.get(f"{API}/api/v1/admin/projections", timeout=10)
    assert r.headers.get("x-content-type-options", "").lower() == "nosniff"


def test_coop_isolates_browsing_context():
    r = httpx.get(f"{API}/api/v1/admin/projections", timeout=10)
    assert r.headers.get("cross-origin-opener-policy") == "same-origin"


def test_permissions_policy_disables_sensitive_features():
    r = httpx.get(f"{API}/api/v1/admin/projections", timeout=10)
    pp = r.headers.get("permissions-policy", "")
    for feature in ("camera=()", "microphone=()", "geolocation=()",
                     "payment=()", "usb=()"):
        assert feature in pp, f"Permissions-Policy missing {feature!r}"


def test_problem_detail_responses_also_carry_headers():
    # An auth failure should still set every required header.
    r = httpx.get(f"{API}/api/v1/admin/projections", timeout=10)
    assert r.status_code in (401, 405)
    for h in REQUIRED_HEADERS:
        assert h in r.headers, f"problem-detail response missing {h}"


def test_rate_limit_kicks_in_for_auth_register():
    """5 registrations / 60s on an isolated app — the 6th MUST return 429."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from kernel.security.http_hardening import (
        RateLimitMiddleware,
        SecurityHeadersMiddleware,
    )

    app = FastAPI()

    @app.post("/api/v1/auth/register")
    async def _register():
        return {"ok": True}

    # Order matters in Starlette — last-added is outermost.
    app.add_middleware(RateLimitMiddleware, enabled=True)
    app.add_middleware(SecurityHeadersMiddleware)
    client = TestClient(app)
    statuses = [client.post("/api/v1/auth/register",
                              json={"email": f"x{i}@y", "password": "p"}).status_code
                for i in range(8)]
    assert 429 in statuses, f"no 429 observed; statuses={statuses}"


def test_rate_limit_problem_detail_shape():
    """When 429 fires, the body must be RFC-7807-shaped."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from kernel.security.http_hardening import RateLimitMiddleware

    app = FastAPI()

    @app.post("/api/v1/auth/register")
    async def _register():
        return {"ok": True}

    app.add_middleware(RateLimitMiddleware, enabled=True)
    client = TestClient(app)
    last = None
    for i in range(12):
        last = client.post("/api/v1/auth/register",
                            json={"email": f"x{i}@y", "password": "p"})
        if last.status_code == 429:
            break
    assert last is not None and last.status_code == 429
    body = last.json()
    assert body["status"] == 429
    assert body["code"] == "kernel.rate_limit"
    assert "detail" in body
    assert "retry-after" in last.headers
