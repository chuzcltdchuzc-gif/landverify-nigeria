"""Authentication: session exchange (Emergent OAuth), dev-login bypass, me, logout."""
from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from core.audit import audit_log
from core.config import EMERGENT_SESSION_URL, ROLE_ROUTES
from core.database import db
from core.helpers import isoformat, new_id, now_utc, serialize_doc
from core.security import _get_session_token, get_current_user

logger = logging.getLogger("landvault.auth")
router = APIRouter(prefix="/auth")

ROLE_TO_DEMO_EMAIL = {
    "CITIZEN": "citizen.demo@landvault.test",
    "COMMUNITY_VALIDATOR": "validator.demo@landvault.test",
    "SURVEYOR": "surveyor.demo@landvault.test",
    "LEGAL": "legal.demo@landvault.test",
    "LEGAL_USER": "legal.demo@landvault.test",
    "INSTITUTIONAL": "institution.demo@landvault.test",
    "INSTITUTIONAL_USER": "institution.demo@landvault.test",
    "OBSERVER": "observer.demo@landvault.test",
    "GOVERNMENT_OBSERVER": "observer.demo@landvault.test",
    "ADMIN": "admin.demo@landvault.test",
}


@router.post("/session")
async def exchange_session(req: Request, response: Response) -> dict:
    body = await req.json()
    session_id = body.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")

    async with httpx.AsyncClient(timeout=15) as http:
        r = await http.get(EMERGENT_SESSION_URL, headers={"X-Session-ID": session_id})
    if r.status_code != 200:
        logger.warning("Emergent session exchange failed %s %s", r.status_code, r.text)
        raise HTTPException(status_code=401, detail="Session exchange failed")
    data = r.json()
    email = data["email"]
    name = data.get("name") or email.split("@")[0]
    picture = data.get("picture")
    session_token = data["session_token"]

    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user:
        user_id = new_id("user")
        tenant_id = new_id("tenant")
        user = {
            "user_id": user_id, "email": email, "name": name, "picture": picture,
            "role": "CITIZEN", "subscription_plan": "CITIZEN", "subscription_status": "TRIAL",
            "tenant_id": tenant_id, "organisation_name": None, "phone": None,
            "onboarding_complete": False,
            "created_at": isoformat(now_utc()), "updated_at": isoformat(now_utc()),
        }
        await db.users.insert_one(dict(user))
        await db.credit_wallets.insert_one({
            "id": new_id("wallet"), "user_id": user_id, "balance": 100,
            "reserved_credits": 0, "total_purchased": 0, "total_consumed": 0,
            "status": "ACTIVE", "tenant_id": tenant_id, "created_at": isoformat(now_utc()),
        })
        await audit_log("USER_REGISTERED", "user", user_id, user=user, tenant_id=tenant_id)
    else:
        if picture and user.get("picture") != picture:
            await db.users.update_one({"user_id": user["user_id"]}, {"$set": {"picture": picture}})
            user["picture"] = picture

    expires_at = now_utc() + timedelta(days=7)
    await db.user_sessions.update_one(
        {"session_token": session_token},
        {"$set": {
            "session_token": session_token, "user_id": user["user_id"], "email": email,
            "expires_at": isoformat(expires_at), "created_at": isoformat(now_utc()),
        }},
        upsert=True,
    )
    response.set_cookie("session_token", session_token, httponly=True, secure=True,
                        samesite="none", path="/", max_age=7 * 24 * 3600)
    serialize_doc(user)
    return {"user": user, "redirect": ROLE_ROUTES.get(user["role"], "/dashboard")}


@router.post("/test-set-balance")
async def test_set_balance(req: Request, user: dict = Depends(get_current_user)) -> dict:
    """Test-only: cap the caller's wallet balance to a specific value."""
    body = await req.json()
    balance = int(body.get("balance", 0))
    await db.credit_wallets.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"balance": balance, "total_consumed": 0, "total_purchased": balance}},
    )
    wallet = await db.credit_wallets.find_one({"user_id": user["user_id"]}, {"_id": 0})
    return {"wallet": wallet}


@router.post("/test-bootstrap-citizen")
async def test_bootstrap_citizen(req: Request, response: Response) -> dict:
    """Test-only endpoint: create a brand-new isolated citizen (unique tenant_id)
    and return a valid session token. Used by the tenant-isolation test suite.

    The endpoint is unauthenticated by design but only creates `CITIZEN` users
    with a synthetic email — it cannot escalate privileges or impersonate
    existing accounts.
    """
    body = await req.json()
    email = (body.get("email") or f"bootstrap_{uuid.uuid4().hex[:8]}@landvault.test").strip().lower()
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user = existing
    else:
        user_id = new_id("user")
        tenant_id = new_id("tenant")
        user = {
            "user_id": user_id, "email": email, "name": f"Test {user_id[-6:]}",
            "picture": None, "role": "CITIZEN", "subscription_plan": "CITIZEN",
            "subscription_status": "TRIAL", "tenant_id": tenant_id,
            "organisation_name": None, "phone": None, "onboarding_complete": True,
            "created_at": isoformat(now_utc()), "updated_at": isoformat(now_utc()),
        }
        await db.users.insert_one(dict(user))
        await db.credit_wallets.insert_one({
            "id": new_id("wallet"), "user_id": user_id, "balance": 500,
            "reserved_credits": 0, "total_purchased": 0, "total_consumed": 0,
            "status": "ACTIVE", "tenant_id": tenant_id, "created_at": isoformat(now_utc()),
        })
        serialize_doc(user)
    session_token = f"test_{uuid.uuid4().hex}"
    expires_at = now_utc() + timedelta(days=1)
    await db.user_sessions.insert_one({
        "session_token": session_token, "user_id": user["user_id"], "email": user["email"],
        "expires_at": isoformat(expires_at), "created_at": isoformat(now_utc()),
    })
    response.set_cookie("session_token", session_token, httponly=True, secure=True,
                        samesite="none", path="/", max_age=24 * 3600)
    return {"session_token": session_token, "user": user}


@router.post("/dev-login")
async def dev_login(req: Request, response: Response) -> dict:
    body = await req.json()
    role = body.get("role", "CITIZEN").upper()
    email = ROLE_TO_DEMO_EMAIL.get(role)
    if not email:
        raise HTTPException(status_code=400, detail="Unsupported role for dev-login")
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=500, detail="Demo user not seeded")
    session_token = f"dev_{uuid.uuid4().hex}"
    expires_at = now_utc() + timedelta(days=7)
    await db.user_sessions.insert_one({
        "session_token": session_token, "user_id": user["user_id"], "email": email,
        "expires_at": isoformat(expires_at), "created_at": isoformat(now_utc()),
    })
    response.set_cookie("session_token", session_token, httponly=True, secure=True,
                        samesite="none", path="/", max_age=7 * 24 * 3600)
    await audit_log("DEV_LOGIN", "session", session_token, user=user)
    return {"session_token": session_token, "user": user,
            "redirect": ROLE_ROUTES.get(user["role"], "/dashboard")}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)) -> dict:
    wallet = await db.credit_wallets.find_one({"user_id": user["user_id"]}, {"_id": 0})
    return {"user": user, "wallet": wallet}


@router.post("/logout")
async def logout(response: Response, token: Optional[str] = Depends(_get_session_token)) -> dict:
    if token:
        await db.user_sessions.delete_many({"session_token": token})
    response.delete_cookie("session_token", path="/")
    return {"ok": True}
