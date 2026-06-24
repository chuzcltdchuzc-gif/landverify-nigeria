"""Community attestation submission + queue + personal history."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core.audit import audit_log, enqueue_job, timeline_event
from core.database import db
from core.helpers import isoformat, new_id, now_utc
from core.security import require_role
from schemas.models import AttestationCreate

router = APIRouter(prefix="/attestations")


@router.post("")
async def submit_attestation(body: AttestationCreate,
                             user: dict = Depends(require_role("COMMUNITY_VALIDATOR"))) -> dict:
    parcel = await db.parcels.find_one({"id": body.parcel_id}, {"_id": 0})
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")
    aid = new_id("att")
    doc = {
        "id": aid, "parcel_id": body.parcel_id, "attestor_id": user["user_id"],
        "attestor_name": user["name"], "role": body.role, "statement": body.statement,
        "relationship_to_land": body.relationship_to_land,
        "years_of_knowledge": body.years_of_knowledge, "signature_url": body.signature_url,
        "photo_url": body.photo_url, "supporting_docs": body.supporting_docs,
        "status": "PENDING", "tenant_id": parcel["tenant_id"],
        "created_at": isoformat(now_utc()),
    }
    await db.community_attestations.insert_one(dict(doc))
    await db.parcels.update_one(
        {"id": body.parcel_id},
        {"$inc": {"attestation_count": 1}, "$set": {"updated_at": isoformat(now_utc())}},
    )
    await timeline_event(body.parcel_id, "ATTESTATION_SUBMITTED",
                         f"Attestation by {user['name']} ({body.role}).",
                         actor=user, tenant_id=parcel["tenant_id"])
    await enqueue_job("CONFIDENCE_RECALCULATION", {"parcel_id": body.parcel_id},
                      idempotency_key=f"conf-att-{aid}")
    await audit_log("ATTESTATION_SUBMITTED", "attestation", aid, user=user, after=doc)
    return {"attestation": doc}


@router.get("/queue")
async def attestation_queue(user: dict = Depends(require_role("COMMUNITY_VALIDATOR"))) -> dict:
    items = []
    async for p in db.parcels.find({"status": {"$in": ["UNVERIFIED", "PENDING"]}}, {"_id": 0}) \
            .sort("created_at", -1).limit(50):
        items.append(p)
    return {"items": items}


@router.get("/mine")
async def my_attestations(user: dict = Depends(require_role("COMMUNITY_VALIDATOR"))) -> dict:
    items = [a async for a in db.community_attestations.find(
        {"attestor_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1)]
    return {"items": items}
