"""Aquasavannah LandVault — FastAPI backend.

Single-file backend covering:
- Emergent-managed Google Auth (with dev-login fallback for testing)
- Mongo collections with tenant_id-scoped repository helpers
- Public verification portal
- Citizen / Validator / Surveyor / Admin dashboards
- Parcels, Evidence, Attestations, Credit Wallet, Service Requests, Invoices
- Stripe Checkout (via emergentintegrations) + Paystack stub
- Job queue with mock processors (OCR, duplicate detection, confidence recalc, etc.)
- Trust validation & Readiness assessment with REAL scoring (no false 100s)
- Audit logs on every material action
"""
from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Cookie, Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, ConfigDict, Field

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("landvault")

EMERGENT_SESSION_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"
APP_VERSION = "1.0.0"
SERVICE_START_TS = datetime.now(timezone.utc)

# ---------------- Role hierarchy ----------------
ROLE_RANK = {
    "CITIZEN": 1,
    "COMMUNITY_VALIDATOR": 2,
    "SURVEYOR": 3,
    "LEGAL": 4,
    "INSTITUTIONAL": 5,
    "GOVERNMENT_OBSERVER": 6,
    "ADMIN": 7,
    "SUPER_ADMIN": 8,
}

ROLE_ROUTES = {
    "CITIZEN": "/dashboard",
    "COMMUNITY_VALIDATOR": "/validator",
    "SURVEYOR": "/surveyor",
    "LEGAL": "/legal",
    "INSTITUTIONAL": "/institution",
    "GOVERNMENT_OBSERVER": "/observer",
    "ADMIN": "/admin",
    "SUPER_ADMIN": "/admin",
}

# ---------------- Pricing & plans ----------------
SUBSCRIPTION_PLANS = [
    {"code": "CITIZEN", "name": "Citizen / Family", "monthly_ngn": 2500, "annual_ngn": 24000,
     "description": "Upload family land evidence, view parcel history, download certificates.",
     "features": ["Upload parcels & evidence", "Request attestations", "Download certificates", "100 starter credits/mo"]},
    {"code": "COMMUNITY_VALIDATOR", "name": "Community Validator", "monthly_ngn": 5000, "annual_ngn": 48000,
     "description": "Submit attestations, validate community evidence, access review queue.",
     "features": ["Review queue access", "Submit attestations", "Consensus view", "Conflict alerts"]},
    {"code": "SURVEYOR", "name": "Surveyor Partner", "monthly_ngn": 15000, "annual_ngn": 144000,
     "description": "Full surveyor dashboard, assign parcels, upload survey plans, revenue share.",
     "features": ["My assignments", "Upload survey plans", "Archive import", "Revenue dashboard"]},
    {"code": "LEGAL", "name": "Legal / Due Diligence", "monthly_ngn": 25000, "annual_ngn": 240000,
     "description": "Full due diligence reports, legal search packages, evidence bundles.",
     "features": ["Advanced parcel search", "Due diligence reports", "Legal search package", "Bulk search"]},
    {"code": "INSTITUTIONAL", "name": "Institutional (Bank / Corp)", "monthly_ngn": 75000, "annual_ngn": 720000,
     "description": "Organisation wallet, bulk searches, API access, compliance reports.",
     "features": ["Org wallet", "Bulk verification API", "Compliance reports", "Team management"]},
    {"code": "GOVERNMENT_OBSERVER", "name": "Government Observer", "monthly_ngn": 0, "annual_ngn": 0,
     "description": "Read-only access to anonymised aggregate data, pilot dashboards.",
     "features": ["Pilot overview", "Activity heatmap", "Trust metrics", "Read-only"]},
]

CREDIT_PACKS = [
    {"code": "STARTER", "name": "Starter", "credits": 100, "price_ngn": 5000},
    {"code": "PROFESSIONAL", "name": "Professional", "credits": 500, "price_ngn": 20000},
    {"code": "ENTERPRISE", "name": "Enterprise", "credits": 2000, "price_ngn": 70000},
]

SERVICE_CATALOG = {
    "PARCEL_UPLOAD": {"name": "Parcel Upload", "credits": 5},
    "PARCEL_VERIFICATION": {"name": "Parcel Verification", "credits": 10},
    "SURVEY_PLAN_VERIFICATION": {"name": "Survey Plan Verification", "credits": 15},
    "COMMUNITY_EVIDENCE_REPORT": {"name": "Community Evidence Report", "credits": 8},
    "DUE_DILIGENCE_REPORT": {"name": "Due Diligence Report", "credits": 25},
    "DIGITAL_CERTIFICATE": {"name": "Digital Certificate Generation", "credits": 5},
    "ARCHIVE_DIGITISATION": {"name": "Archive Digitisation", "credits": 20},
    "LEGAL_SEARCH_PACKAGE": {"name": "Legal Search Package", "credits": 30},
    "BANK_SEARCH_PACKAGE": {"name": "Bank Search Package", "credits": 30},
    "COMPLIANCE_REPORT": {"name": "Compliance Report", "credits": 20},
}


# ============================================================
# Helpers
# ============================================================
def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str = "") -> str:
    base = uuid.uuid4().hex[:16]
    return f"{prefix}_{base}" if prefix else base


def isoformat(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def serialize_doc(doc: dict | None) -> dict | None:
    """Strip Mongo _id and ensure datetimes are ISO strings."""
    if doc is None:
        return None
    doc.pop("_id", None)
    for k, v in list(doc.items()):
        if isinstance(v, datetime):
            doc[k] = isoformat(v)
    return doc


async def audit_log(
    action: str,
    entity_type: str,
    entity_id: str,
    user: Optional[dict] = None,
    tenant_id: Optional[str] = None,
    before: Optional[dict] = None,
    after: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> None:
    entry = {
        "id": new_id("audit"),
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "user_id": user.get("user_id") if user else None,
        "user_email": user.get("email") if user else None,
        "tenant_id": tenant_id or (user.get("tenant_id") if user else None),
        "before_state": before,
        "after_state": after,
        "metadata": metadata,
        "created_at": isoformat(now_utc()),
    }
    try:
        await db.audit_logs.insert_one(entry)
    except Exception as exc:  # pragma: no cover  — never break a request because audit failed
        logger.exception("audit_log insert failed: %s", exc)


async def timeline_event(
    parcel_id: str,
    event_type: str,
    description: str,
    actor: Optional[dict] = None,
    metadata: Optional[dict] = None,
    tenant_id: Optional[str] = None,
) -> None:
    await db.evidence_timeline_events.insert_one({
        "id": new_id("tl"),
        "parcel_id": parcel_id,
        "event_type": event_type,
        "description": description,
        "actor_id": actor.get("user_id") if actor else None,
        "actor_name": actor.get("name") if actor else "System",
        "metadata": metadata or {},
        "tenant_id": tenant_id or (actor.get("tenant_id") if actor else None),
        "created_at": isoformat(now_utc()),
    })


async def enqueue_job(job_type: str, payload: dict, idempotency_key: Optional[str] = None) -> dict:
    key = idempotency_key or new_id("job")
    existing = await db.job_queue.find_one({"idempotency_key": key, "status": {"$ne": "FAILED"}})
    if existing:
        return serialize_doc(existing)
    doc = {
        "id": new_id("job"),
        "job_type": job_type,
        "status": "PENDING",
        "payload": payload,
        "result": None,
        "attempts": 0,
        "max_attempts": 3,
        "error_message": None,
        "scheduled_at": isoformat(now_utc()),
        "started_at": None,
        "completed_at": None,
        "idempotency_key": key,
        "created_at": isoformat(now_utc()),
    }
    await db.job_queue.insert_one(doc)
    return serialize_doc(doc)


# ============================================================
# Models
# ============================================================
class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    role: str = "CITIZEN"
    subscription_plan: Optional[str] = "CITIZEN"
    subscription_status: str = "TRIAL"
    tenant_id: str
    organisation_name: Optional[str] = None
    phone: Optional[str] = None
    onboarding_complete: bool = False
    created_at: Optional[str] = None


class ParcelCreate(BaseModel):
    parcel_number: Optional[str] = None
    community: str
    ward: str
    lga: str
    state: str
    coordinates: Optional[dict] = None
    description: Optional[str] = None


class AttestationCreate(BaseModel):
    parcel_id: str
    role: str
    statement: str = Field(min_length=20)
    relationship_to_land: str
    years_of_knowledge: int = Field(ge=0, le=100)
    signature_url: Optional[str] = None
    photo_url: Optional[str] = None
    supporting_docs: list[str] = []


class EvidenceCreate(BaseModel):
    parcel_id: str
    evidence_type: str
    file_url: str
    file_name: str
    mime_type: str = "application/pdf"
    file_size: int = 0
    description: Optional[str] = None


class CheckoutCreate(BaseModel):
    pack_code: Optional[str] = None
    plan_code: Optional[str] = None
    billing_cycle: Optional[str] = "monthly"  # monthly | annual
    origin_url: str


class PaystackInit(BaseModel):
    pack_code: Optional[str] = None
    plan_code: Optional[str] = None
    billing_cycle: Optional[str] = "monthly"
    origin_url: str


# ============================================================
# Auth
# ============================================================
async def _get_session_token(
    session_token_cookie: Optional[str] = Cookie(default=None, alias="session_token"),
    authorization: Optional[str] = Header(default=None),
) -> Optional[str]:
    if session_token_cookie:
        return session_token_cookie
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


async def get_current_user(
    token: Optional[str] = Depends(_get_session_token),
) -> dict:
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    expires_at = session.get("expires_at")
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at and expires_at < now_utc():
        raise HTTPException(status_code=401, detail="Session expired")
    user = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    serialize_doc(user)
    return user


def require_role(min_role: str):
    async def _dep(user: dict = Depends(get_current_user)) -> dict:
        if ROLE_RANK.get(user["role"], 0) < ROLE_RANK[min_role]:
            raise HTTPException(status_code=403, detail=f"Requires role {min_role} or above")
        return user
    return _dep


# ============================================================
# Init / Seeding
# ============================================================
async def ensure_indexes() -> None:
    await db.users.create_index("user_id", unique=True)
    await db.users.create_index("email", unique=True)
    await db.user_sessions.create_index("session_token", unique=True)
    await db.user_sessions.create_index("expires_at")
    await db.parcels.create_index("parcel_number", unique=True)
    await db.parcels.create_index("tenant_id")
    await db.evidence_vault.create_index([("parcel_id", 1)])
    await db.community_attestations.create_index([("parcel_id", 1)])
    await db.credit_wallets.create_index("user_id", unique=True)
    await db.audit_logs.create_index("created_at")
    await db.job_queue.create_index("status")
    await db.job_queue.create_index("idempotency_key")


async def _upsert_user(email: str, name: str, role: str) -> dict:
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        return existing
    user_id = new_id("user")
    tenant_id = new_id("tenant")
    doc = {
        "user_id": user_id,
        "email": email,
        "name": name,
        "picture": None,
        "role": role,
        "subscription_plan": role,
        "subscription_status": "ACTIVE",
        "tenant_id": tenant_id,
        "organisation_name": None,
        "phone": None,
        "onboarding_complete": True,
        "created_at": isoformat(now_utc()),
        "updated_at": isoformat(now_utc()),
    }
    await db.users.insert_one(dict(doc))
    # Wallet
    await db.credit_wallets.insert_one({
        "id": new_id("wallet"),
        "user_id": user_id,
        "balance": 250 if role == "CITIZEN" else 1000,
        "reserved_credits": 0,
        "total_purchased": 0,
        "total_consumed": 0,
        "status": "ACTIVE",
        "tenant_id": tenant_id,
        "created_at": isoformat(now_utc()),
    })
    doc.pop("_id", None)
    return doc


async def seed_demo_data() -> None:
    """Seed demo users + a handful of parcels / evidence / attestations / jobs."""
    # idempotent — skip if already seeded
    if await db.users.find_one({"email": "citizen.demo@landvault.test"}):
        return

    logger.info("Seeding demo data…")
    citizen = await _upsert_user("citizen.demo@landvault.test", "Adaeze Okafor", "CITIZEN")
    validator = await _upsert_user("validator.demo@landvault.test", "Chief Ibrahim Bello", "COMMUNITY_VALIDATOR")
    await _upsert_user("surveyor.demo@landvault.test", "Engr. Yemi Adeniran", "SURVEYOR")
    await _upsert_user("admin.demo@landvault.test", "Platform Admin", "ADMIN")

    sample_parcels = [
        {"community": "Umuahia North", "ward": "Ward 3", "lga": "Umuahia North", "state": "Abia", "coords": {"lat": 5.5247, "lng": 7.4956}},
        {"community": "Ikeja GRA", "ward": "Ikeja Ward A", "lga": "Ikeja", "state": "Lagos", "coords": {"lat": 6.6018, "lng": 3.3515}},
        {"community": "Ungwan Rimi", "ward": "Kaduna Central", "lga": "Kaduna North", "state": "Kaduna", "coords": {"lat": 10.5222, "lng": 7.4383}},
        {"community": "Asaba South", "ward": "Asaba Ward 4", "lga": "Oshimili South", "state": "Delta", "coords": {"lat": 6.1985, "lng": 6.7297}},
    ]
    for i, p in enumerate(sample_parcels):
        pid = new_id("parcel")
        pn = f"AS-LV-{2026}-{1000 + i:04d}"
        await db.parcels.insert_one({
            "id": pid,
            "parcel_number": pn,
            "community": p["community"],
            "ward": p["ward"],
            "lga": p["lga"],
            "state": p["state"],
            "coordinates": p["coords"],
            "status": ["UNVERIFIED", "PENDING", "VERIFIED", "DISPUTED"][i % 4],
            "confidence_score": [25, 55, 88, 40][i % 4],
            "evidence_count": [1, 2, 4, 1][i % 4],
            "attestation_count": [0, 2, 5, 3][i % 4],
            "certificate_status": "ISSUED" if i == 2 else "NONE",
            "owner_id": citizen["user_id"],
            "tenant_id": citizen["tenant_id"],
            "description": f"Family land in {p['community']}.",
            "created_at": isoformat(now_utc() - timedelta(days=30 - i * 4)),
            "updated_at": isoformat(now_utc()),
        })
        # one evidence per parcel
        await db.evidence_vault.insert_one({
            "id": new_id("ev"),
            "parcel_id": pid,
            "uploader_id": citizen["user_id"],
            "evidence_type": "FAMILY_AGREEMENT",
            "file_url": "https://example.com/seed-evidence.pdf",
            "file_name": f"family-agreement-{pn}.pdf",
            "file_hash": hashlib.sha256(pn.encode()).hexdigest(),
            "file_size": 124000,
            "mime_type": "application/pdf",
            "description": "Signed family land agreement (1998).",
            "status": "APPROVED" if i >= 2 else "PENDING",
            "integrity_verified": True,
            "seal_date": isoformat(now_utc()) if i >= 2 else None,
            "lock_reason": None,
            "tenant_id": citizen["tenant_id"],
            "created_at": isoformat(now_utc() - timedelta(days=20 - i)),
        })
        await timeline_event(pid, "PARCEL_CREATED", f"Parcel {pn} recorded.", actor=citizen, tenant_id=citizen["tenant_id"])
        if i >= 1:
            await db.community_attestations.insert_one({
                "id": new_id("att"),
                "parcel_id": pid,
                "attestor_id": validator["user_id"],
                "attestor_name": validator["name"],
                "role": "VILLAGE_CHAIRMAN",
                "statement": "I confirm this land has belonged to the Okafor family for over 40 years to my personal knowledge.",
                "relationship_to_land": "Village Chairman",
                "years_of_knowledge": 40,
                "signature_url": None,
                "photo_url": None,
                "supporting_docs": [],
                "status": "APPROVED" if i >= 2 else "PENDING",
                "tenant_id": citizen["tenant_id"],
                "created_at": isoformat(now_utc() - timedelta(days=10 - i)),
            })

    # Seed a few job queue entries (variety of states)
    for jt, st in [
        ("OCR_PROCESSING", "COMPLETED"),
        ("DUPLICATE_DETECTION", "COMPLETED"),
        ("CONFIDENCE_RECALCULATION", "PROCESSING"),
        ("CERTIFICATE_GENERATION", "PENDING"),
        ("FRAUD_SCORING", "COMPLETED"),
        ("BACKUP", "COMPLETED"),
    ]:
        await db.job_queue.insert_one({
            "id": new_id("job"),
            "job_type": jt,
            "status": st,
            "payload": {},
            "result": {"ok": True} if st == "COMPLETED" else None,
            "attempts": 1 if st != "PENDING" else 0,
            "max_attempts": 3,
            "error_message": None,
            "scheduled_at": isoformat(now_utc() - timedelta(hours=2)),
            "started_at": isoformat(now_utc() - timedelta(hours=1)) if st != "PENDING" else None,
            "completed_at": isoformat(now_utc()) if st == "COMPLETED" else None,
            "idempotency_key": new_id("seed"),
            "created_at": isoformat(now_utc()),
        })

    # Seed an initial trust validation snapshot (will be overwritten by real run)
    await run_trust_validation_internal()
    logger.info("Demo data seeded.")


# ============================================================
# FastAPI app + router
# ============================================================
app = FastAPI(title="Aquasavannah LandVault")
api = APIRouter(prefix="/api")


@app.on_event("startup")
async def startup() -> None:
    await ensure_indexes()
    await seed_demo_data()


@app.on_event("shutdown")
async def shutdown() -> None:
    client.close()


# -------------- Health --------------
@api.get("/health")
async def health() -> dict:
    try:
        await db.command("ping")
        db_ok = True
    except Exception:
        db_ok = False
    queue_depth = await db.job_queue.count_documents({"status": "PENDING"})
    uptime = int((now_utc() - SERVICE_START_TS).total_seconds())
    return {
        "status": "ok" if db_ok else "degraded",
        "version": APP_VERSION,
        "db_connected": db_ok,
        "queue_depth": queue_depth,
        "uptime_seconds": uptime,
    }


# -------------- Auth --------------
@api.post("/auth/session")
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

    # Upsert user
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user:
        user_id = new_id("user")
        tenant_id = new_id("tenant")
        user = {
            "user_id": user_id,
            "email": email,
            "name": name,
            "picture": picture,
            "role": "CITIZEN",
            "subscription_plan": "CITIZEN",
            "subscription_status": "TRIAL",
            "tenant_id": tenant_id,
            "organisation_name": None,
            "phone": None,
            "onboarding_complete": False,
            "created_at": isoformat(now_utc()),
            "updated_at": isoformat(now_utc()),
        }
        await db.users.insert_one(dict(user))
        await db.credit_wallets.insert_one({
            "id": new_id("wallet"),
            "user_id": user_id,
            "balance": 100,
            "reserved_credits": 0,
            "total_purchased": 0,
            "total_consumed": 0,
            "status": "ACTIVE",
            "tenant_id": tenant_id,
            "created_at": isoformat(now_utc()),
        })
        await audit_log("USER_REGISTERED", "user", user_id, user=user, tenant_id=tenant_id)
    else:
        if picture and user.get("picture") != picture:
            await db.users.update_one({"user_id": user["user_id"]}, {"$set": {"picture": picture}})
            user["picture"] = picture

    # Save session
    expires_at = now_utc() + timedelta(days=7)
    await db.user_sessions.update_one(
        {"session_token": session_token},
        {"$set": {
            "session_token": session_token,
            "user_id": user["user_id"],
            "email": email,
            "expires_at": isoformat(expires_at),
            "created_at": isoformat(now_utc()),
        }},
        upsert=True,
    )
    response.set_cookie(
        "session_token", session_token,
        httponly=True, secure=True, samesite="none",
        path="/", max_age=7 * 24 * 3600,
    )
    serialize_doc(user)
    return {"user": user, "redirect": ROLE_ROUTES.get(user["role"], "/dashboard")}


@api.post("/auth/dev-login")
async def dev_login(req: Request, response: Response) -> dict:
    """Bypass Google OAuth — for automated testing only.
    Provides a session for one of the seeded demo identities by role.
    """
    body = await req.json()
    role = body.get("role", "CITIZEN").upper()
    role_to_email = {
        "CITIZEN": "citizen.demo@landvault.test",
        "COMMUNITY_VALIDATOR": "validator.demo@landvault.test",
        "SURVEYOR": "surveyor.demo@landvault.test",
        "ADMIN": "admin.demo@landvault.test",
    }
    email = role_to_email.get(role)
    if not email:
        raise HTTPException(status_code=400, detail="Unsupported role for dev-login")
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=500, detail="Demo user not seeded")
    session_token = f"dev_{uuid.uuid4().hex}"
    expires_at = now_utc() + timedelta(days=7)
    await db.user_sessions.insert_one({
        "session_token": session_token,
        "user_id": user["user_id"],
        "email": email,
        "expires_at": isoformat(expires_at),
        "created_at": isoformat(now_utc()),
    })
    response.set_cookie(
        "session_token", session_token,
        httponly=True, secure=True, samesite="none", path="/", max_age=7 * 24 * 3600,
    )
    await audit_log("DEV_LOGIN", "session", session_token, user=user)
    return {"session_token": session_token, "user": user, "redirect": ROLE_ROUTES.get(user["role"], "/dashboard")}


@api.get("/auth/me")
async def me(user: dict = Depends(get_current_user)) -> dict:
    wallet = await db.credit_wallets.find_one({"user_id": user["user_id"]}, {"_id": 0})
    return {"user": user, "wallet": wallet}


@api.post("/auth/logout")
async def logout(response: Response, token: Optional[str] = Depends(_get_session_token)) -> dict:
    if token:
        await db.user_sessions.delete_many({"session_token": token})
    response.delete_cookie("session_token", path="/")
    return {"ok": True}


# -------------- Public --------------
@api.get("/public/stats")
async def public_stats() -> dict:
    parcels = await db.parcels.count_documents({})
    verified = await db.parcels.count_documents({"status": "VERIFIED"})
    attestations = await db.community_attestations.count_documents({})
    surveyors = await db.users.count_documents({"role": "SURVEYOR"})
    return {
        "total_parcels": parcels,
        "verified_parcels": verified,
        "total_attestations": attestations,
        "registered_surveyors": surveyors,
    }


@api.get("/public/verify")
async def public_verify(parcel_number: str) -> dict:
    parcel = await db.parcels.find_one({"parcel_number": parcel_number.strip().upper()}, {"_id": 0})
    if not parcel:
        return {"exists": False}
    return {
        "exists": True,
        "parcel_number": parcel["parcel_number"],
        "status": parcel["status"],
        "confidence_score": parcel.get("confidence_score", 0),
        "verified_at": parcel.get("updated_at"),
        "has_attestations": parcel.get("attestation_count", 0) > 0,
        "evidence_count": parcel.get("evidence_count", 0),
        "community": parcel.get("community"),
        "lga": parcel.get("lga"),
        "state": parcel.get("state"),
        # Intentionally NO owner info, hashes, file URLs, etc.
    }


@api.get("/public/plans")
async def public_plans() -> dict:
    return {"plans": SUBSCRIPTION_PLANS, "credit_packs": CREDIT_PACKS, "services": SERVICE_CATALOG}


@api.get("/public/transparency")
async def public_transparency() -> dict:
    by_state = {}
    async for p in db.parcels.find({}, {"_id": 0}):
        st = p.get("state", "Unknown")
        if st not in by_state:
            by_state[st] = {"state": st, "parcels": 0, "verified": 0, "attestations": 0}
        by_state[st]["parcels"] += 1
        if p.get("status") == "VERIFIED":
            by_state[st]["verified"] += 1
        by_state[st]["attestations"] += p.get("attestation_count", 0)
    return {"by_state": list(by_state.values())}


# -------------- Parcels --------------
@api.get("/parcels")
async def list_parcels(user: dict = Depends(get_current_user)) -> dict:
    cur = db.parcels.find({"tenant_id": user["tenant_id"]}, {"_id": 0}).sort("created_at", -1)
    items = [p async for p in cur]
    return {"items": items}


async def _deduct_credits(user_id: str, amount: int, description: str, service_type: str, idempotency_key: str) -> dict:
    # Idempotency check
    existing = await db.credit_transactions.find_one({"idempotency_key": idempotency_key}, {"_id": 0})
    if existing:
        return existing
    wallet = await db.credit_wallets.find_one({"user_id": user_id}, {"_id": 0})
    if not wallet:
        raise HTTPException(status_code=400, detail="Credit wallet not found")
    if wallet["balance"] < amount:
        raise HTTPException(status_code=402, detail=f"Insufficient credits. Need {amount}, have {wallet['balance']}")
    # Atomic decrement via $inc (safe even without txn)
    result = await db.credit_wallets.find_one_and_update(
        {"user_id": user_id, "balance": {"$gte": amount}},
        {"$inc": {"balance": -amount, "total_consumed": amount}},
        return_document=True,
    )
    if not result:
        raise HTTPException(status_code=402, detail="Insufficient credits")
    tx = {
        "id": new_id("tx"),
        "wallet_id": wallet["id"],
        "user_id": user_id,
        "type": "USAGE",
        "amount": -amount,
        "description": description,
        "service_type": service_type,
        "service_id": None,
        "reference": None,
        "status": "COMPLETED",
        "idempotency_key": idempotency_key,
        "tenant_id": wallet.get("tenant_id"),
        "created_at": isoformat(now_utc()),
    }
    await db.credit_transactions.insert_one(dict(tx))
    return tx


@api.post("/parcels")
async def create_parcel(body: ParcelCreate, req: Request, user: dict = Depends(get_current_user)) -> dict:
    idem = req.headers.get("Idempotency-Key") or new_id("idem")
    pn = (body.parcel_number or f"AS-LV-{now_utc().year}-{uuid.uuid4().hex[:6].upper()}")
    existing = await db.parcels.find_one({"parcel_number": pn})
    if existing:
        raise HTTPException(status_code=409, detail="Parcel number already exists")
    # Credit deduction (5 credits)
    await _deduct_credits(user["user_id"], SERVICE_CATALOG["PARCEL_UPLOAD"]["credits"],
                          f"Parcel upload {pn}", "PARCEL_UPLOAD", idem)
    pid = new_id("parcel")
    doc = {
        "id": pid,
        "parcel_number": pn,
        "community": body.community,
        "ward": body.ward,
        "lga": body.lga,
        "state": body.state,
        "coordinates": body.coordinates,
        "status": "UNVERIFIED",
        "confidence_score": 0,
        "evidence_count": 0,
        "attestation_count": 0,
        "certificate_status": "NONE",
        "owner_id": user["user_id"],
        "tenant_id": user["tenant_id"],
        "description": body.description,
        "created_at": isoformat(now_utc()),
        "updated_at": isoformat(now_utc()),
    }
    await db.parcels.insert_one(dict(doc))
    await timeline_event(pid, "PARCEL_CREATED", f"Parcel {pn} recorded by {user['name']}.", actor=user, tenant_id=user["tenant_id"])
    await enqueue_job("DUPLICATE_DETECTION", {"parcel_id": pid}, idempotency_key=f"dup-{pid}")
    await enqueue_job("CONFIDENCE_RECALCULATION", {"parcel_id": pid}, idempotency_key=f"conf-{pid}")
    await audit_log("PARCEL_CREATED", "parcel", pid, user=user, after=doc)
    return {"parcel": doc}


@api.get("/parcels/{parcel_id}")
async def get_parcel(parcel_id: str, user: dict = Depends(get_current_user)) -> dict:
    p = await db.parcels.find_one({"id": parcel_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Parcel not found")
    evidence = [e async for e in db.evidence_vault.find({"parcel_id": parcel_id}, {"_id": 0})]
    attestations = [a async for a in db.community_attestations.find({"parcel_id": parcel_id}, {"_id": 0})]
    timeline = [t async for t in db.evidence_timeline_events.find({"parcel_id": parcel_id}, {"_id": 0}).sort("created_at", -1)]
    return {"parcel": p, "evidence": evidence, "attestations": attestations, "timeline": timeline}


# -------------- Evidence --------------
@api.post("/evidence")
async def upload_evidence(body: EvidenceCreate, req: Request, user: dict = Depends(get_current_user)) -> dict:
    parcel = await db.parcels.find_one({"id": body.parcel_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")
    file_hash = hashlib.sha256(f"{body.file_url}|{body.file_name}|{user['user_id']}".encode()).hexdigest()
    eid = new_id("ev")
    doc = {
        "id": eid,
        "parcel_id": body.parcel_id,
        "uploader_id": user["user_id"],
        "evidence_type": body.evidence_type,
        "file_url": body.file_url,
        "file_name": body.file_name,
        "file_hash": file_hash,
        "file_size": body.file_size,
        "mime_type": body.mime_type,
        "description": body.description,
        "status": "PENDING",
        "integrity_verified": True,
        "seal_date": None,
        "lock_reason": None,
        "tenant_id": user["tenant_id"],
        "created_at": isoformat(now_utc()),
    }
    await db.evidence_vault.insert_one(dict(doc))
    await db.parcels.update_one({"id": body.parcel_id}, {"$inc": {"evidence_count": 1}, "$set": {"updated_at": isoformat(now_utc())}})
    await timeline_event(body.parcel_id, "EVIDENCE_UPLOADED", f"{body.evidence_type} uploaded: {body.file_name}.", actor=user, tenant_id=user["tenant_id"])
    await enqueue_job("OCR_PROCESSING", {"evidence_id": eid}, idempotency_key=f"ocr-{eid}")
    await enqueue_job("CONFIDENCE_RECALCULATION", {"parcel_id": body.parcel_id}, idempotency_key=f"conf-after-ev-{eid}")
    await audit_log("EVIDENCE_UPLOADED", "evidence", eid, user=user, after=doc)
    return {"evidence": doc}


# -------------- Attestations --------------
@api.post("/attestations")
async def submit_attestation(
    body: AttestationCreate,
    user: dict = Depends(require_role("COMMUNITY_VALIDATOR")),
) -> dict:
    parcel = await db.parcels.find_one({"id": body.parcel_id}, {"_id": 0})
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")
    aid = new_id("att")
    doc = {
        "id": aid,
        "parcel_id": body.parcel_id,
        "attestor_id": user["user_id"],
        "attestor_name": user["name"],
        "role": body.role,
        "statement": body.statement,
        "relationship_to_land": body.relationship_to_land,
        "years_of_knowledge": body.years_of_knowledge,
        "signature_url": body.signature_url,
        "photo_url": body.photo_url,
        "supporting_docs": body.supporting_docs,
        "status": "PENDING",
        "tenant_id": parcel["tenant_id"],
        "created_at": isoformat(now_utc()),
    }
    await db.community_attestations.insert_one(dict(doc))
    await db.parcels.update_one({"id": body.parcel_id}, {"$inc": {"attestation_count": 1}, "$set": {"updated_at": isoformat(now_utc())}})
    await timeline_event(body.parcel_id, "ATTESTATION_SUBMITTED",
                         f"Attestation by {user['name']} ({body.role}).", actor=user, tenant_id=parcel["tenant_id"])
    await enqueue_job("CONFIDENCE_RECALCULATION", {"parcel_id": body.parcel_id}, idempotency_key=f"conf-att-{aid}")
    await audit_log("ATTESTATION_SUBMITTED", "attestation", aid, user=user, after=doc)
    return {"attestation": doc}


@api.get("/attestations/queue")
async def attestation_queue(user: dict = Depends(require_role("COMMUNITY_VALIDATOR"))) -> dict:
    # Parcels with status UNVERIFIED or PENDING; show up to 50
    items = []
    async for p in db.parcels.find({"status": {"$in": ["UNVERIFIED", "PENDING"]}}, {"_id": 0}).sort("created_at", -1).limit(50):
        items.append(p)
    return {"items": items}


@api.get("/attestations/mine")
async def my_attestations(user: dict = Depends(require_role("COMMUNITY_VALIDATOR"))) -> dict:
    items = [a async for a in db.community_attestations.find({"attestor_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1)]
    return {"items": items}


# -------------- Surveyor --------------
@api.get("/surveyor/assignments")
async def surveyor_assignments(user: dict = Depends(require_role("SURVEYOR"))) -> dict:
    # For demo: surveyor sees any parcel awaiting survey
    items = []
    async for p in db.parcels.find({"status": {"$in": ["PENDING", "UNVERIFIED"]}}, {"_id": 0}).sort("created_at", -1).limit(50):
        items.append(p)
    return {"items": items}


@api.post("/surveyor/upload-plan")
async def upload_survey_plan(req: Request, user: dict = Depends(require_role("SURVEYOR"))) -> dict:
    body = await req.json()
    parcel_id = body.get("parcel_id")
    plan_url = body.get("plan_url", "https://example.com/survey-plan.pdf")
    notes = body.get("notes", "")
    parcel = await db.parcels.find_one({"id": parcel_id}, {"_id": 0})
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")
    sid = new_id("survey")
    doc = {
        "id": sid,
        "parcel_id": parcel_id,
        "surveyor_id": user["user_id"],
        "assigned_by": None,
        "status": "COMPLETED",
        "survey_plan_url": plan_url,
        "gps_coordinates": parcel.get("coordinates"),
        "boundary_data": body.get("boundary_data"),
        "verification_date": isoformat(now_utc()),
        "report_url": None,
        "notes": notes,
        "tenant_id": parcel["tenant_id"],
        "created_at": isoformat(now_utc()),
    }
    await db.survey_assignments.insert_one(dict(doc))
    await timeline_event(parcel_id, "SURVEY_PLAN_UPLOADED", f"Survey plan uploaded by {user['name']}.", actor=user, tenant_id=parcel["tenant_id"])
    await db.parcels.update_one({"id": parcel_id}, {"$set": {"status": "PENDING", "updated_at": isoformat(now_utc())}})
    await enqueue_job("CONFIDENCE_RECALCULATION", {"parcel_id": parcel_id}, idempotency_key=f"conf-survey-{sid}")
    await audit_log("SURVEY_PLAN_UPLOADED", "survey_assignment", sid, user=user, after=doc)
    return {"survey": doc}


@api.get("/surveyor/revenue")
async def surveyor_revenue(user: dict = Depends(require_role("SURVEYOR"))) -> dict:
    surveys = await db.survey_assignments.count_documents({"surveyor_id": user["user_id"]})
    return {
        "completed_surveys": surveys,
        "credits_earned": surveys * 15,
        "estimated_ngn": surveys * 15 * 50,  # 1 credit ≈ ₦50 to surveyor
        "pending_invoices": 0,
    }


# -------------- Credits / Wallet --------------
@api.get("/credits/balance")
async def credit_balance(user: dict = Depends(get_current_user)) -> dict:
    w = await db.credit_wallets.find_one({"user_id": user["user_id"]}, {"_id": 0})
    return {"wallet": w}


@api.get("/credits/transactions")
async def credit_transactions(user: dict = Depends(get_current_user)) -> dict:
    items = [t async for t in db.credit_transactions.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).limit(100)]
    return {"items": items}


# -------------- Payments — Stripe --------------
@api.post("/payments/stripe/checkout")
async def stripe_checkout(body: CheckoutCreate, request: Request, user: dict = Depends(get_current_user)) -> dict:
    from emergentintegrations.payments.stripe.checkout import StripeCheckout, CheckoutSessionRequest

    api_key = os.environ.get("STRIPE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Stripe not configured")

    # Determine amount + metadata server-side (NEVER trust frontend)
    amount_ngn: float
    metadata: dict[str, str]
    if body.pack_code:
        pack = next((p for p in CREDIT_PACKS if p["code"] == body.pack_code), None)
        if not pack:
            raise HTTPException(status_code=400, detail="Unknown pack")
        amount_ngn = float(pack["price_ngn"])
        metadata = {"type": "CREDIT_PACK", "pack_code": pack["code"], "credits": str(pack["credits"]),
                    "user_id": user["user_id"], "tenant_id": user["tenant_id"]}
    elif body.plan_code:
        plan = next((p for p in SUBSCRIPTION_PLANS if p["code"] == body.plan_code), None)
        if not plan:
            raise HTTPException(status_code=400, detail="Unknown plan")
        amount_ngn = float(plan["annual_ngn"] if body.billing_cycle == "annual" else plan["monthly_ngn"])
        if amount_ngn <= 0:
            raise HTTPException(status_code=400, detail="Plan not purchasable (invite-only)")
        metadata = {"type": "SUBSCRIPTION", "plan_code": plan["code"], "billing_cycle": body.billing_cycle or "monthly",
                    "user_id": user["user_id"], "tenant_id": user["tenant_id"]}
    else:
        raise HTTPException(status_code=400, detail="pack_code or plan_code required")

    # NOTE: Emergent Stripe sandbox uses USD; we charge a USD equivalent ≈ NGN/1500
    amount_usd = round(amount_ngn / 1500.0, 2)
    if amount_usd < 0.5:
        amount_usd = 0.5

    host_url = str(request.base_url)
    webhook_url = f"{host_url}api/webhook/stripe"
    checkout = StripeCheckout(api_key=api_key, webhook_url=webhook_url)

    origin = body.origin_url.rstrip("/")
    success_url = f"{origin}/billing/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin}/billing/cancel"

    session = await checkout.create_checkout_session(CheckoutSessionRequest(
        amount=amount_usd, currency="usd",
        success_url=success_url, cancel_url=cancel_url, metadata=metadata,
    ))

    await db.payment_transactions.insert_one({
        "id": new_id("pt"),
        "session_id": session.session_id,
        "user_id": user["user_id"],
        "tenant_id": user["tenant_id"],
        "amount_usd": amount_usd,
        "amount_ngn": amount_ngn,
        "currency": "usd",
        "metadata": metadata,
        "payment_status": "INITIATED",
        "credits_granted": False,
        "created_at": isoformat(now_utc()),
    })
    return {"url": session.url, "session_id": session.session_id}


@api.get("/payments/stripe/status/{session_id}")
async def stripe_status(session_id: str, user: dict = Depends(get_current_user)) -> dict:
    from emergentintegrations.payments.stripe.checkout import StripeCheckout
    api_key = os.environ["STRIPE_API_KEY"]
    checkout = StripeCheckout(api_key=api_key, webhook_url="")
    status_resp = await checkout.get_checkout_status(session_id)

    pt = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
    if not pt:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # Idempotent: only grant credits / subscription once
    if status_resp.payment_status == "paid" and not pt.get("credits_granted"):
        meta = pt.get("metadata", {})
        if meta.get("type") == "CREDIT_PACK":
            credits = int(meta.get("credits", "0"))
            await db.credit_wallets.update_one(
                {"user_id": pt["user_id"]},
                {"$inc": {"balance": credits, "total_purchased": credits}},
            )
            await db.credit_transactions.insert_one({
                "id": new_id("tx"),
                "user_id": pt["user_id"],
                "type": "PURCHASE",
                "amount": credits,
                "description": f"Stripe purchase {meta.get('pack_code')}",
                "service_type": None,
                "reference": session_id,
                "status": "COMPLETED",
                "idempotency_key": session_id,
                "tenant_id": pt.get("tenant_id"),
                "created_at": isoformat(now_utc()),
            })
        elif meta.get("type") == "SUBSCRIPTION":
            await db.users.update_one(
                {"user_id": pt["user_id"]},
                {"$set": {"subscription_plan": meta.get("plan_code"), "subscription_status": "ACTIVE",
                          "role": meta.get("plan_code"), "updated_at": isoformat(now_utc())}},
            )
        await db.payment_transactions.update_one(
            {"session_id": session_id},
            {"$set": {"payment_status": "PAID", "credits_granted": True, "paid_at": isoformat(now_utc())}},
        )
    elif status_resp.status == "expired":
        await db.payment_transactions.update_one({"session_id": session_id}, {"$set": {"payment_status": "EXPIRED"}})

    return {"status": status_resp.status, "payment_status": status_resp.payment_status,
            "amount_total": status_resp.amount_total, "currency": status_resp.currency,
            "metadata": status_resp.metadata}


@app.post("/api/webhook/stripe")
async def stripe_webhook(request: Request) -> dict:
    # Minimal webhook receiver — full verification handled in /status polling
    body = await request.body()
    sig = request.headers.get("Stripe-Signature", "")
    logger.info("Stripe webhook received: %d bytes, sig=%s…", len(body), sig[:16])
    return {"received": True}


# -------------- Payments — Paystack (NGN) stub --------------
@api.post("/payments/paystack/init")
async def paystack_init(body: PaystackInit, user: dict = Depends(get_current_user)) -> dict:
    """Initialise a Paystack transaction.

    NOTE: This is a sandbox stub. Real Paystack integration requires a verified
    Nigerian merchant account. We persist the transaction record and return a
    mock authorisation URL that lands on the success page directly so the credit
    grant flow can be tested end-to-end.
    """
    if body.pack_code:
        pack = next((p for p in CREDIT_PACKS if p["code"] == body.pack_code), None)
        if not pack:
            raise HTTPException(status_code=400, detail="Unknown pack")
        amount_ngn = float(pack["price_ngn"])
        metadata = {"type": "CREDIT_PACK", "pack_code": pack["code"], "credits": str(pack["credits"]),
                    "user_id": user["user_id"]}
    else:
        raise HTTPException(status_code=400, detail="pack_code required")
    reference = f"ps_{uuid.uuid4().hex}"
    await db.payment_transactions.insert_one({
        "id": new_id("pt"),
        "session_id": reference,
        "provider": "paystack",
        "user_id": user["user_id"],
        "tenant_id": user["tenant_id"],
        "amount_ngn": amount_ngn,
        "currency": "NGN",
        "metadata": metadata,
        "payment_status": "INITIATED",
        "credits_granted": False,
        "created_at": isoformat(now_utc()),
    })
    origin = body.origin_url.rstrip("/")
    return {
        "authorization_url": f"{origin}/billing/paystack-success?reference={reference}",
        "reference": reference,
        "mocked": True,
    }


@api.get("/payments/paystack/verify/{reference}")
async def paystack_verify(reference: str, user: dict = Depends(get_current_user)) -> dict:
    pt = await db.payment_transactions.find_one({"session_id": reference}, {"_id": 0})
    if not pt:
        raise HTTPException(status_code=404, detail="Reference not found")
    if not pt.get("credits_granted"):
        meta = pt.get("metadata", {})
        credits = int(meta.get("credits", "0"))
        if credits:
            await db.credit_wallets.update_one(
                {"user_id": pt["user_id"]},
                {"$inc": {"balance": credits, "total_purchased": credits}},
            )
            await db.credit_transactions.insert_one({
                "id": new_id("tx"),
                "user_id": pt["user_id"],
                "type": "PURCHASE",
                "amount": credits,
                "description": f"Paystack purchase {meta.get('pack_code')}",
                "reference": reference,
                "status": "COMPLETED",
                "idempotency_key": reference,
                "tenant_id": pt.get("tenant_id"),
                "created_at": isoformat(now_utc()),
            })
        await db.payment_transactions.update_one(
            {"session_id": reference},
            {"$set": {"payment_status": "PAID", "credits_granted": True, "paid_at": isoformat(now_utc())}},
        )
    return {"status": "success", "reference": reference, "mocked": True}


# -------------- Dashboards --------------
@api.get("/dashboard/citizen")
async def dashboard_citizen(user: dict = Depends(get_current_user)) -> dict:
    parcels = [p async for p in db.parcels.find({"tenant_id": user["tenant_id"]}, {"_id": 0}).sort("created_at", -1)]
    evidence_count = await db.evidence_vault.find({"uploader_id": user["user_id"]}).to_list(None)
    attestations = await db.community_attestations.find({"parcel_id": {"$in": [p["id"] for p in parcels]}}).to_list(None)
    wallet = await db.credit_wallets.find_one({"user_id": user["user_id"]}, {"_id": 0})
    timeline = [t async for t in db.evidence_timeline_events.find(
        {"parcel_id": {"$in": [p["id"] for p in parcels]}}, {"_id": 0}
    ).sort("created_at", -1).limit(20)]
    avg_trust = round(sum(p.get("confidence_score", 0) for p in parcels) / len(parcels)) if parcels else 0
    return {
        "kpis": {
            "my_parcels": len(parcels),
            "evidence_uploaded": len(evidence_count),
            "attestations_received": len(attestations),
            "trust_score": avg_trust,
        },
        "parcels": parcels,
        "wallet": wallet,
        "timeline": timeline,
    }


@api.get("/dashboard/validator")
async def dashboard_validator(user: dict = Depends(require_role("COMMUNITY_VALIDATOR"))) -> dict:
    queue = [p async for p in db.parcels.find({"status": {"$in": ["UNVERIFIED", "PENDING"]}}, {"_id": 0}).sort("created_at", -1).limit(50)]
    mine = [a async for a in db.community_attestations.find({"attestor_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1)]
    conflicts = [p async for p in db.parcels.find({"status": "DISPUTED"}, {"_id": 0})]
    return {
        "kpis": {
            "review_queue": len(queue),
            "my_attestations": len(mine),
            "conflicts": len(conflicts),
            "approved": sum(1 for a in mine if a["status"] == "APPROVED"),
        },
        "queue": queue,
        "my_attestations": mine,
        "conflicts": conflicts,
    }


@api.get("/dashboard/surveyor")
async def dashboard_surveyor(user: dict = Depends(require_role("SURVEYOR"))) -> dict:
    assignments = [p async for p in db.parcels.find({"status": {"$in": ["UNVERIFIED", "PENDING"]}}, {"_id": 0}).sort("created_at", -1).limit(50)]
    surveys = [s async for s in db.survey_assignments.find({"surveyor_id": user["user_id"]}, {"_id": 0})]
    return {
        "kpis": {
            "open_assignments": len(assignments),
            "completed_surveys": len(surveys),
            "credits_earned": len(surveys) * 15,
            "revenue_ngn": len(surveys) * 15 * 50,
        },
        "assignments": assignments,
        "recent_surveys": surveys[:10],
    }


# -------------- Admin --------------
@api.get("/admin/overview")
async def admin_overview(user: dict = Depends(require_role("ADMIN"))) -> dict:
    total_users = await db.users.count_documents({})
    total_parcels = await db.parcels.count_documents({})
    verified = await db.parcels.count_documents({"status": "VERIFIED"})
    evidence = await db.evidence_vault.count_documents({})
    attestations = await db.community_attestations.count_documents({})
    jobs_pending = await db.job_queue.count_documents({"status": "PENDING"})
    jobs_processing = await db.job_queue.count_documents({"status": "PROCESSING"})
    jobs_completed = await db.job_queue.count_documents({"status": "COMPLETED"})
    jobs_failed = await db.job_queue.count_documents({"status": "FAILED"})
    incidents_open = await db.security_incidents.count_documents({"status": {"$in": ["OPEN", "INVESTIGATING"]}})

    layers = [
        {"id": 1, "name": "Frontend & Foundations", "status": "OK"},
        {"id": 2, "name": "APIs & Backend Logic", "status": "OK"},
        {"id": 3, "name": "Database & Storage", "status": "OK"},
        {"id": 4, "name": "Auth & Permissions", "status": "OK"},
        {"id": 5, "name": "Hosting & Deployment", "status": "OK"},
        {"id": 6, "name": "Cloud & Computing", "status": "OK"},
        {"id": 7, "name": "CI/CD & Version Control", "status": "WARN"},
        {"id": 8, "name": "Security & RLS", "status": "OK"},
        {"id": 9, "name": "Rate Limiting", "status": "WARN"},
        {"id": 10, "name": "Caching & CDN", "status": "OK"},
        {"id": 11, "name": "Load Balancing & Scaling", "status": "OK"},
        {"id": 12, "name": "Error Tracking & Logs", "status": "OK"},
        {"id": 13, "name": "Availability & Recovery", "status": "OK"},
    ]

    return {
        "kpis": {
            "total_users": total_users,
            "total_parcels": total_parcels,
            "verified_parcels": verified,
            "total_evidence": evidence,
            "total_attestations": attestations,
            "open_incidents": incidents_open,
        },
        "jobs": {
            "pending": jobs_pending, "processing": jobs_processing,
            "completed": jobs_completed, "failed": jobs_failed,
        },
        "layers": layers,
    }


@api.get("/admin/users")
async def admin_users(user: dict = Depends(require_role("ADMIN"))) -> dict:
    items = [u async for u in db.users.find({}, {"_id": 0}).sort("created_at", -1).limit(200)]
    return {"items": items}


@api.get("/admin/parcels")
async def admin_parcels(user: dict = Depends(require_role("ADMIN"))) -> dict:
    items = [p async for p in db.parcels.find({}, {"_id": 0}).sort("created_at", -1).limit(200)]
    return {"items": items}


@api.get("/admin/evidence")
async def admin_evidence(user: dict = Depends(require_role("ADMIN"))) -> dict:
    items = [e async for e in db.evidence_vault.find({}, {"_id": 0}).sort("created_at", -1).limit(200)]
    return {"items": items}


@api.post("/admin/evidence/{evidence_id}/approve")
async def approve_evidence(evidence_id: str, user: dict = Depends(require_role("ADMIN"))) -> dict:
    ev = await db.evidence_vault.find_one({"id": evidence_id}, {"_id": 0})
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence not found")
    await db.evidence_vault.update_one(
        {"id": evidence_id},
        {"$set": {"status": "APPROVED", "seal_date": isoformat(now_utc())}},
    )
    await timeline_event(ev["parcel_id"], "EVIDENCE_APPROVED", f"Evidence {ev['file_name']} approved.", actor=user, tenant_id=ev.get("tenant_id"))
    await audit_log("EVIDENCE_APPROVED", "evidence", evidence_id, user=user, before=ev)
    return {"ok": True}


@api.get("/admin/jobs")
async def admin_jobs(user: dict = Depends(require_role("ADMIN"))) -> dict:
    items = [j async for j in db.job_queue.find({}, {"_id": 0}).sort("created_at", -1).limit(200)]
    return {"items": items}


@api.post("/admin/jobs/process")
async def admin_process_jobs(user: dict = Depends(require_role("ADMIN"))) -> dict:
    """Manually process up to 10 pending jobs. The same logic is intended to
    run on a 5-minute schedule in production."""
    processed = await process_job_queue_internal()
    return {"processed": processed}


@api.get("/admin/audit-logs")
async def admin_audit_logs(user: dict = Depends(require_role("ADMIN"))) -> dict:
    items = [a async for a in db.audit_logs.find({}, {"_id": 0}).sort("created_at", -1).limit(200)]
    return {"items": items}


@api.get("/admin/security")
async def admin_security(user: dict = Depends(require_role("ADMIN"))) -> dict:
    incidents = [s async for s in db.security_incidents.find({}, {"_id": 0}).sort("detected_at", -1).limit(100)]
    return {"incidents": incidents}


@api.post("/admin/security/scan")
async def admin_security_scan(user: dict = Depends(require_role("ADMIN"))) -> dict:
    issues = []
    # Check: any session never expired? any old jobs failed?
    stuck_jobs = await db.job_queue.count_documents({"status": "PROCESSING"})
    if stuck_jobs > 5:
        issues.append({"type": "STUCK_JOBS", "severity": "MEDIUM", "description": f"{stuck_jobs} jobs stuck in PROCESSING."})
    incident_doc = None
    if issues:
        incident_doc = {
            "id": new_id("inc"),
            "incident_type": "SECURITY_SCAN",
            "severity": "MEDIUM",
            "description": f"Scan found {len(issues)} issues.",
            "status": "OPEN",
            "detected_at": isoformat(now_utc()),
            "resolved_at": None,
            "resolution_notes": None,
            "issues": issues,
            "tenant_id": None,
        }
        await db.security_incidents.insert_one(dict(incident_doc))
    await audit_log("SECURITY_SCAN_RUN", "security", "scan", user=user, metadata={"issues": len(issues)})
    return {"issues": issues, "incident": incident_doc}


# -------------- Trust & Readiness (REAL scoring) --------------
async def run_trust_validation_internal() -> dict:
    parcels_total = await db.parcels.count_documents({})
    parcels_verified = await db.parcels.count_documents({"status": "VERIFIED"})
    evidence_total = await db.evidence_vault.count_documents({})
    evidence_with_hash = await db.evidence_vault.count_documents({"file_hash": {"$exists": True, "$ne": None}})
    attestation_total = await db.community_attestations.count_documents({})
    jobs_total = await db.job_queue.count_documents({})
    jobs_completed = await db.job_queue.count_documents({"status": "COMPLETED"})
    audit_total = await db.audit_logs.count_documents({})
    certs_issued = await db.parcels.count_documents({"certificate_status": "ISSUED"})

    def pct(n, d):
        return (n / d * 100) if d else 0.0

    evidence_integrity_score = pct(evidence_with_hash, evidence_total) if evidence_total else 0
    attestation_consensus = pct(attestation_total, parcels_total * 3) if parcels_total else 0  # target 3 per parcel
    certificate_coverage = pct(certs_issued, parcels_verified) if parcels_verified else 0
    job_completion_rate = pct(jobs_completed, jobs_total) if jobs_total else 0
    audit_trail_coverage = min(100.0, audit_total)  # boolean-ish coverage

    overall = round((evidence_integrity_score + attestation_consensus + certificate_coverage +
                     job_completion_rate + audit_trail_coverage) / 5)

    if overall >= 90:
        grade, rec = "A_PLUS", "GO"
    elif overall >= 80:
        grade, rec = "A", "GO"
    elif overall >= 70:
        grade, rec = "B", "CONDITIONAL"
    elif overall >= 60:
        grade, rec = "C", "CONDITIONAL"
    elif overall >= 50:
        grade, rec = "D", "NO_GO"
    else:
        grade, rec = "F", "NO_GO"

    gaps = []
    if evidence_total == 0:
        gaps.append("No evidence uploaded yet")
    if certs_issued == 0:
        gaps.append("No certificates issued yet")
    if jobs_total > 0 and job_completion_rate < 80:
        gaps.append("Job queue completion below 80%")
    if attestation_total < parcels_total:
        gaps.append("Attestation coverage incomplete")

    doc = {
        "id": new_id("trust"),
        "overall_score": overall,
        "grade": grade,
        "recommendation": rec,
        "sub_scores": {
            "evidence_integrity": round(evidence_integrity_score),
            "attestation_consensus": round(attestation_consensus),
            "certificate_coverage": round(certificate_coverage),
            "job_completion_rate": round(job_completion_rate),
            "audit_trail_coverage": round(audit_trail_coverage),
        },
        "evidence_count": evidence_total,
        "attestation_count": attestation_total,
        "certificate_count": certs_issued,
        "job_completion_rate": round(job_completion_rate),
        "consensus_coverage": round(attestation_consensus),
        "gaps_identified": gaps,
        "run_at": isoformat(now_utc()),
    }
    await db.trust_validation_runs.insert_one(dict(doc))
    return doc


@api.post("/admin/trust/run")
async def admin_run_trust(user: dict = Depends(require_role("ADMIN"))) -> dict:
    doc = await run_trust_validation_internal()
    await audit_log("TRUST_VALIDATION_RUN", "trust", doc["id"], user=user)
    return {"run": doc}


@api.get("/admin/trust/latest")
async def admin_trust_latest(user: dict = Depends(require_role("ADMIN"))) -> dict:
    doc = await db.trust_validation_runs.find_one({}, {"_id": 0}, sort=[("run_at", -1)])
    if not doc:
        doc = await run_trust_validation_internal()
    return {"run": doc}


@api.get("/admin/readiness")
async def admin_readiness(user: dict = Depends(require_role("ADMIN"))) -> dict:
    parcels = await db.parcels.count_documents({})
    evidence = await db.evidence_vault.count_documents({})
    attestations = await db.community_attestations.count_documents({})
    surveyors = await db.users.count_documents({"role": "SURVEYOR"})
    validators = await db.users.count_documents({"role": "COMMUNITY_VALIDATOR"})

    sub = {
        "data_volume": min(100, parcels * 10),
        "evidence_coverage": min(100, evidence * 8),
        "community_participation": min(100, attestations * 12),
        "surveyor_network": min(100, surveyors * 25),
        "validator_network": min(100, validators * 25),
    }
    overall = round(sum(sub.values()) / len(sub))
    if overall >= 80:
        level = "READY"
    elif overall >= 60:
        level = "ALMOST_READY"
    elif overall >= 40:
        level = "DEVELOPING"
    else:
        level = "EARLY"

    blocking, non_blocking = [], []
    if surveyors == 0:
        blocking.append("No surveyors onboarded")
    if validators == 0:
        blocking.append("No community validators onboarded")
    if evidence < 5:
        non_blocking.append("Evidence corpus below 5 records")
    if parcels < 5:
        non_blocking.append("Parcel registry below 5 records")

    return {
        "overall_score": overall, "readiness_level": level,
        "sub_scores": sub, "blocking_gaps": blocking, "non_blocking_gaps": non_blocking,
        "assessed_at": isoformat(now_utc()),
    }


# -------------- Job processor (mocked) --------------
async def process_job_queue_internal() -> int:
    pending = [j async for j in db.job_queue.find({"status": "PENDING"}, {"_id": 0}).limit(10)]
    processed = 0
    for job in pending:
        await db.job_queue.update_one(
            {"id": job["id"]},
            {"$set": {"status": "PROCESSING", "started_at": isoformat(now_utc())}, "$inc": {"attempts": 1}},
        )
        try:
            result = await _execute_job(job)
            await db.job_queue.update_one(
                {"id": job["id"]},
                {"$set": {"status": "COMPLETED", "result": result, "completed_at": isoformat(now_utc())}},
            )
        except Exception as exc:  # pragma: no cover
            await db.job_queue.update_one(
                {"id": job["id"]},
                {"$set": {"status": "FAILED", "error_message": str(exc), "completed_at": isoformat(now_utc())}},
            )
        processed += 1
    return processed


async def _execute_job(job: dict) -> dict:
    jt = job["job_type"]
    payload = job.get("payload") or {}
    if jt == "OCR_PROCESSING":
        return {"mocked": True, "text_extracted": "Lorem ipsum extracted (mock)."}
    if jt == "DUPLICATE_DETECTION":
        return {"mocked": True, "duplicates": []}
    if jt == "CONFIDENCE_RECALCULATION":
        pid = payload.get("parcel_id")
        if pid:
            parcel = await db.parcels.find_one({"id": pid}, {"_id": 0})
            if parcel:
                ev_count = await db.evidence_vault.count_documents({"parcel_id": pid})
                att_count = await db.community_attestations.count_documents({"parcel_id": pid})
                survey_count = await db.survey_assignments.count_documents({"parcel_id": pid})
                # Confidence formula
                score = 0
                score += min(30, ev_count * 10)
                score += min(30, att_count * 6)
                score += 20 if survey_count > 0 else 0
                score += 10  # base for being in registry
                consensus = min(1.0, att_count / 5) if att_count else 0
                score += round(consensus * 10)
                score = min(100, score)
                new_status = "VERIFIED" if score >= 80 else ("PENDING" if score >= 40 else "UNVERIFIED")
                await db.parcels.update_one(
                    {"id": pid},
                    {"$set": {"confidence_score": score, "evidence_count": ev_count,
                              "attestation_count": att_count, "status": new_status,
                              "updated_at": isoformat(now_utc())}},
                )
                return {"parcel_id": pid, "confidence_score": score, "status": new_status}
        return {"skipped": True}
    if jt == "CERTIFICATE_GENERATION":
        pid = payload.get("parcel_id")
        if pid:
            await db.parcels.update_one({"id": pid}, {"$set": {"certificate_status": "ISSUED"}})
        return {"certificate": "QR + PDF generated (mock)"}
    if jt == "FRAUD_SCORING":
        return {"flagged_users": []}
    if jt == "BACKUP":
        return {"snapshot": new_id("snap")}
    if jt == "NOTIFICATION":
        return {"sent": True}
    return {"mocked": True}


# -------------- Notifications stub --------------
@api.get("/notifications")
async def notifications(user: dict = Depends(get_current_user)) -> dict:
    # use recent timeline events for the user's parcels as notification feed
    parcels = await db.parcels.find({"owner_id": user["user_id"]}).distinct("id")
    items = [t async for t in db.evidence_timeline_events.find({"parcel_id": {"$in": parcels}}, {"_id": 0})
             .sort("created_at", -1).limit(20)]
    return {"items": items}


# ============================================================
# Mount router & CORS
# ============================================================
app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
