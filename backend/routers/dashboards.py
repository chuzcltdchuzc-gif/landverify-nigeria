"""Role-based dashboard aggregators: citizen, validator, surveyor."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from core.database import db
from core.security import get_current_user, require_role

router = APIRouter(prefix="/dashboard")


@router.get("/citizen")
async def dashboard_citizen(user: dict = Depends(get_current_user)) -> dict:
    parcels = [p async for p in db.parcels.find({"tenant_id": user["tenant_id"]}, {"_id": 0}).sort("created_at", -1)]
    evidence = await db.evidence_vault.find({"uploader_id": user["user_id"]}).to_list(None)
    parcel_ids = [p["id"] for p in parcels]
    attestations = await db.community_attestations.find({"parcel_id": {"$in": parcel_ids}}).to_list(None)
    wallet = await db.credit_wallets.find_one({"user_id": user["user_id"]}, {"_id": 0})
    timeline = [t async for t in db.evidence_timeline_events.find(
        {"parcel_id": {"$in": parcel_ids}}, {"_id": 0}).sort("created_at", -1).limit(20)]
    avg_trust = round(sum(p.get("confidence_score", 0) for p in parcels) / len(parcels)) if parcels else 0
    return {
        "kpis": {
            "my_parcels": len(parcels),
            "evidence_uploaded": len(evidence),
            "attestations_received": len(attestations),
            "trust_score": avg_trust,
        },
        "parcels": parcels,
        "wallet": wallet,
        "timeline": timeline,
    }


@router.get("/validator")
async def dashboard_validator(user: dict = Depends(require_role("COMMUNITY_VALIDATOR"))) -> dict:
    queue = [p async for p in db.parcels.find(
        {"status": {"$in": ["UNVERIFIED", "PENDING"]}}, {"_id": 0}).sort("created_at", -1).limit(50)]
    mine = [a async for a in db.community_attestations.find(
        {"attestor_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1)]
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


@router.get("/surveyor")
async def dashboard_surveyor(user: dict = Depends(require_role("SURVEYOR"))) -> dict:
    assignments = [p async for p in db.parcels.find(
        {"status": {"$in": ["UNVERIFIED", "PENDING"]}}, {"_id": 0}).sort("created_at", -1).limit(50)]
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
