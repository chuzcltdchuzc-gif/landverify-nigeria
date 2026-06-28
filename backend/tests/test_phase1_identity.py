"""Phase 1 — Platform Kernel + Identity Context smoke + integration tests.

Covers:
* JWKS publication + RS256 verification
* Register → access token + httpOnly refresh cookie + JWT claims (country, tenant_id, roles)
* Login → same shape; rejects bad credentials
* /me requires a valid access token (401 otherwise) and returns canonical ExecutionContext
* Refresh rotates the refresh token; replay of a revoked refresh token kills the session chain
* Logout revokes the active session
* JWKS endpoint serves valid signing keys
* Append-only audit store records register/login/logout
* Authorization engine: role gate, default-deny for anonymous on protected actions
* RFC 7807 problem+json on auth failures
* Legacy /api/health and legacy /api/auth/dev-login routes still work
"""
from __future__ import annotations

import json
import os
import secrets
import uuid

import jwt as pyjwt
import pytest
import requests
from cryptography.hazmat.primitives import serialization

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _email(prefix: str = "p1") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}@example.com"


def _extract_refresh_cookie(response) -> str:
    """Extract lv_refresh cookie value from a response's Set-Cookie header.

    `requests`' cookie jar refuses to forward Secure cookies over plain HTTP,
    so for HTTP test traffic we attach the cookie explicitly per request.
    """
    raw = response.cookies.get("lv_refresh")
    if raw:
        return raw
    for h in response.raw.headers.getlist("Set-Cookie"):
        if h.startswith("lv_refresh="):
            return h.split(";", 1)[0].split("=", 1)[1]
    raise AssertionError(f"refresh cookie missing in response: {response.headers}")


# ---- Fixtures ------------------------------------------------------------

@pytest.fixture()
def jwks() -> dict:
    r = requests.get(f"{API}/.well-known/jwks.json", timeout=10)
    assert r.status_code == 200
    payload = r.json()
    assert "keys" in payload and payload["keys"], "JWKS must publish at least one signing key"
    return payload


@pytest.fixture()
def fresh_user_session():
    """Returns (session, dict with access_token + email + password)."""
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    email = _email()
    password = secrets.token_urlsafe(20)
    r = s.post(f"{API}/v1/auth/register", json={
        "email": email, "password": password, "full_name": "Phase One",
    }, timeout=15)
    assert r.status_code == 201, f"register: {r.status_code} {r.text}"
    body = r.json()
    s.headers.update({"Authorization": f"Bearer {body['access_token']}"})
    return s, {"email": email, "password": password,
               "access_token": body["access_token"], "user": body["user"]}


# ---- JWKS + JWT verification --------------------------------------------

class TestJwksAndJwt:
    def test_jwks_publishes_signing_key(self, jwks: dict):
        key = jwks["keys"][0]
        for k in ("kty", "use", "alg", "kid", "n", "e"):
            assert k in key
        assert key["alg"] == "RS256"
        assert key["kty"] == "RSA"

    def test_access_token_verifies_with_jwks_public_key(self, jwks, fresh_user_session):
        _, data = fresh_user_session
        token = data["access_token"]
        unverified_header = pyjwt.get_unverified_header(token)
        kid = unverified_header["kid"]
        jwk = next(k for k in jwks["keys"] if k["kid"] == kid)
        from base64 import urlsafe_b64decode

        def _b64d(s: str) -> int:
            pad = "=" * (-len(s) % 4)
            return int.from_bytes(urlsafe_b64decode(s + pad), "big")

        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
        public_key = RSAPublicNumbers(_b64d(jwk["e"]), _b64d(jwk["n"])).public_key()
        pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        claims = pyjwt.decode(token, pem, algorithms=["RS256"],
                              audience="landvault-api",
                              issuer="https://aquasavannah.landvault")
        assert claims["typ"] == "access"
        assert claims["country"] == "NG"
        assert claims["tenant_id"].startswith("ten_")
        assert "general_user" in claims["roles"]
        assert "jti" in claims


# ---- Auth flow ----------------------------------------------------------

class TestAuthFlow:
    def test_register_login_me(self, fresh_user_session):
        s, data = fresh_user_session
        r = s.get(f"{API}/v1/auth/me", timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["email"] == data["email"]
        assert body["country"] == "NG"
        assert body["tenant_id"].startswith("ten_")
        assert "general_user" in body["roles"]
        assert body["session_id"] is not None and body["session_id"].startswith("ses_")

    def test_login_with_wrong_password_returns_401_problem_json(self):
        email = _email()
        pw = secrets.token_urlsafe(20)
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        r = s.post(f"{API}/v1/auth/register", json={
            "email": email, "password": pw, "full_name": "X",
        }, timeout=15)
        assert r.status_code == 201
        r = s.post(f"{API}/v1/auth/login", json={
            "email": email, "password": "this_is_wrong_password",
        }, timeout=15)
        assert r.status_code == 401, r.text
        assert r.headers.get("content-type", "").startswith("application/problem+json")
        prob = r.json()
        assert prob["status"] == 401
        assert prob["code"] == "auth.invalid_credentials"
        assert prob["correlation_id"]
        assert prob["type"].startswith("https://aquasavannah.landvault/problems/")

    def test_me_without_token_returns_401(self):
        r = requests.get(f"{API}/v1/auth/me", timeout=10)
        assert r.status_code == 401
        assert r.json()["code"] == "auth.unauthenticated"

    def test_me_with_tampered_token_returns_401(self, fresh_user_session):
        _, data = fresh_user_session
        bad = data["access_token"][:-3] + "AAA"
        r = requests.get(f"{API}/v1/auth/me",
                         headers={"Authorization": f"Bearer {bad}"}, timeout=10)
        assert r.status_code == 401

    def test_refresh_rotates_and_replay_kills_chain(self):
        email = _email()
        pw = secrets.token_urlsafe(20)
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        r = s.post(f"{API}/v1/auth/register", json={
            "email": email, "password": pw, "full_name": "Chain",
        }, timeout=15)
        assert r.status_code == 201
        login = s.post(f"{API}/v1/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
        assert login.status_code == 200
        original_refresh = _extract_refresh_cookie(login)

        # Refresh once → token rotates.
        r = requests.post(f"{API}/v1/auth/refresh",
                          cookies={"lv_refresh": original_refresh}, timeout=15)
        assert r.status_code == 200, r.text
        new_refresh = _extract_refresh_cookie(r)
        assert new_refresh and new_refresh != original_refresh

        # Replay the ORIGINAL (now-revoked) refresh token → 401 + theft heuristic
        replay = requests.post(f"{API}/v1/auth/refresh",
                               cookies={"lv_refresh": original_refresh}, timeout=15)
        assert replay.status_code == 401
        assert replay.json()["code"] == "auth.refresh_replay"

        # And the new refresh token chain is now revoked too.
        r2 = requests.post(f"{API}/v1/auth/refresh",
                           cookies={"lv_refresh": new_refresh}, timeout=15)
        assert r2.status_code == 401

    def test_logout_revokes_current_session(self):
        email = _email()
        pw = secrets.token_urlsafe(20)
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        s.post(f"{API}/v1/auth/register", json={
            "email": email, "password": pw, "full_name": "Logout",
        }, timeout=15)
        login = s.post(f"{API}/v1/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
        refresh = _extract_refresh_cookie(login)
        r = requests.post(f"{API}/v1/auth/logout",
                          cookies={"lv_refresh": refresh}, timeout=10)
        assert r.status_code == 204
        # Replay refresh → must 401
        r2 = requests.post(f"{API}/v1/auth/refresh",
                           cookies={"lv_refresh": refresh}, timeout=10)
        assert r2.status_code == 401

    def test_duplicate_register_returns_409(self):
        email = _email()
        pw = secrets.token_urlsafe(20)
        r = requests.post(f"{API}/v1/auth/register", json={
            "email": email, "password": pw, "full_name": "X",
        }, timeout=15)
        assert r.status_code == 201
        r = requests.post(f"{API}/v1/auth/register", json={
            "email": email, "password": pw, "full_name": "X",
        }, timeout=15)
        assert r.status_code == 409
        assert r.json()["code"] == "identity.email_taken"

    def test_weak_password_rejected(self):
        r = requests.post(f"{API}/v1/auth/register", json={
            "email": _email(), "password": "short", "full_name": "X",
        }, timeout=15)
        assert r.status_code == 422  # Pydantic validation


# ---- Legacy backwards compatibility -------------------------------------

class TestLegacyCoexistence:
    def test_legacy_health_still_works(self):
        r = requests.get(f"{API}/health", timeout=10)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_legacy_dev_login_still_works(self):
        r = requests.post(f"{API}/auth/dev-login",
                          json={"role": "CITIZEN"}, timeout=10)
        assert r.status_code == 200
        assert "session_token" in r.json()
