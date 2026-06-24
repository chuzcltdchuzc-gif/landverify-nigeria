"""Public, unauthenticated endpoints: health, stats, parcel verify, plans."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from core.config import (APP_VERSION, CREDIT_PACKS, SERVICE_CATALOG,
                         SERVICE_START_TS, SUBSCRIPTION_PLANS)
from core.database import db

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    try:
        await db.command("ping")
        db_ok = True
    except Exception:
        db_ok = False
    queue_depth = await db.job_queue.count_documents({"status": "PENDING"})
    uptime = int((datetime.now(timezone.utc) - SERVICE_START_TS).total_seconds())
    return {
        "status": "ok" if db_ok else "degraded",
        "version": APP_VERSION,
        "db_connected": db_ok,
        "queue_depth": queue_depth,
        "uptime_seconds": uptime,
    }


@router.get("/public/stats")
async def public_stats() -> dict:
    return {
        "total_parcels": await db.parcels.count_documents({}),
        "verified_parcels": await db.parcels.count_documents({"status": "VERIFIED"}),
        "total_attestations": await db.community_attestations.count_documents({}),
        "registered_surveyors": await db.users.count_documents({"role": "SURVEYOR"}),
    }


@router.get("/public/verify")
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
    }


@router.get("/public/plans")
async def public_plans() -> dict:
    return {"plans": SUBSCRIPTION_PLANS, "credit_packs": CREDIT_PACKS, "services": SERVICE_CATALOG}


@router.get("/public/transparency")
async def public_transparency() -> dict:
    by_state: dict = {}
    async for p in db.parcels.find({}, {"_id": 0}):
        st = p.get("state", "Unknown")
        if st not in by_state:
            by_state[st] = {"state": st, "parcels": 0, "verified": 0, "attestations": 0}
        by_state[st]["parcels"] += 1
        if p.get("status") == "VERIFIED":
            by_state[st]["verified"] += 1
        by_state[st]["attestations"] += p.get("attestation_count", 0)
    return {"by_state": list(by_state.values())}
