"""Surveyor field-ops endpoints: assignments, upload survey plan, revenue."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from core.audit import audit_log, enqueue_job, timeline_event
from core.database import db
from core.helpers import isoformat, new_id, now_utc
from core.security import require_role

router = APIRouter(prefix="/surveyor")


@router.get("/assignments")
async def surveyor_assignments(user: dict = Depends(require_role("SURVEYOR"))) -> dict:
    items = []
    async for p in db.parcels.find({"status": {"$in": ["PENDING", "UNVERIFIED"]}}, {"_id": 0}) \
            .sort("created_at", -1).limit(50):
        items.append(p)
    return {"items": items}


@router.post("/upload-plan")
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
        "id": sid, "parcel_id": parcel_id, "surveyor_id": user["user_id"], "assigned_by": None,
        "status": "COMPLETED", "survey_plan_url": plan_url,
        "gps_coordinates": parcel.get("coordinates"),
        "boundary_data": body.get("boundary_data"),
        "verification_date": isoformat(now_utc()), "report_url": None, "notes": notes,
        "tenant_id": parcel["tenant_id"], "created_at": isoformat(now_utc()),
    }
    await db.survey_assignments.insert_one(dict(doc))
    await timeline_event(parcel_id, "SURVEY_PLAN_UPLOADED",
                         f"Survey plan uploaded by {user['name']}.",
                         actor=user, tenant_id=parcel["tenant_id"])
    await db.parcels.update_one({"id": parcel_id},
                                {"$set": {"status": "PENDING", "updated_at": isoformat(now_utc())}})
    await enqueue_job("CONFIDENCE_RECALCULATION", {"parcel_id": parcel_id},
                      idempotency_key=f"conf-survey-{sid}")
    await audit_log("SURVEY_PLAN_UPLOADED", "survey_assignment", sid, user=user, after=doc)
    return {"survey": doc}


@router.get("/revenue")
async def surveyor_revenue(user: dict = Depends(require_role("SURVEYOR"))) -> dict:
    surveys = await db.survey_assignments.count_documents({"surveyor_id": user["user_id"]})
    return {
        "completed_surveys": surveys,
        "credits_earned": surveys * 15,
        "estimated_ngn": surveys * 15 * 50,
        "pending_invoices": 0,
    }
