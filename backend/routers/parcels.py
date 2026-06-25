"""Parcel CRUD + tenant-scoped queries.

All reads/writes go through `tdb` (TenantDB) which structurally enforces
`tenant_id` isolation. Public verify lives in routers/public.py.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from core.audit import audit_log, enqueue_job, timeline_event
from core.config import SERVICE_CATALOG
from core.database import db
from core.helpers import isoformat, new_id, now_utc
from core.safe_db import tdb
from core.security import get_current_user
from schemas.models import ParcelCreate
from services.payments import deduct_credits

router = APIRouter(prefix="/parcels")


@router.get("")
async def list_parcels(user: dict = Depends(get_current_user)) -> dict:
    # tdb auto-injects tenant_id — leaks across tenants are structurally impossible.
    cur = tdb.parcels.find({}, {"_id": 0}).sort("created_at", -1)
    items = [p async for p in cur]
    return {"items": items}


@router.post("")
async def create_parcel(body: ParcelCreate, req: Request, user: dict = Depends(get_current_user)) -> dict:
    idem = req.headers.get("Idempotency-Key") or new_id("idem")
    pn = (body.parcel_number or f"AS-LV-{now_utc().year}-{uuid.uuid4().hex[:6].upper()}")
    # parcel_number must be globally unique — query the raw collection.
    existing = await db.parcels.find_one({"parcel_number": pn})
    if existing:
        raise HTTPException(status_code=409, detail="Parcel number already exists")
    await deduct_credits(user["user_id"], SERVICE_CATALOG["PARCEL_UPLOAD"]["credits"],
                         f"Parcel upload {pn}", "PARCEL_UPLOAD", idem)
    pid = new_id("parcel")
    doc = {
        "id": pid, "parcel_number": pn, "community": body.community, "ward": body.ward,
        "lga": body.lga, "state": body.state, "coordinates": body.coordinates,
        "status": "UNVERIFIED", "confidence_score": 0, "evidence_count": 0,
        "attestation_count": 0, "certificate_status": "NONE",
        "owner_id": user["user_id"], "tenant_id": user["tenant_id"],
        "description": body.description,
        "created_at": isoformat(now_utc()), "updated_at": isoformat(now_utc()),
    }
    await tdb.parcels.insert_one(dict(doc))
    await timeline_event(pid, "PARCEL_CREATED", f"Parcel {pn} recorded by {user['name']}.",
                         actor=user, tenant_id=user["tenant_id"])
    await enqueue_job("DUPLICATE_DETECTION", {"parcel_id": pid}, idempotency_key=f"dup-{pid}")
    await enqueue_job("CONFIDENCE_RECALCULATION", {"parcel_id": pid}, idempotency_key=f"conf-{pid}")
    await audit_log("PARCEL_CREATED", "parcel", pid, user=user, after=doc)
    return {"parcel": doc}


@router.get("/{parcel_id}")
async def get_parcel(parcel_id: str, user: dict = Depends(get_current_user)) -> dict:
    p = await tdb.parcels.find_one({"id": parcel_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Parcel not found")
    evidence = [e async for e in tdb.evidence_vault.find({"parcel_id": parcel_id}, {"_id": 0})]
    attestations = [a async for a in tdb.community_attestations.find({"parcel_id": parcel_id}, {"_id": 0})]
    timeline = [t async for t in tdb.evidence_timeline_events.find(
        {"parcel_id": parcel_id}, {"_id": 0}).sort("created_at", -1)]
    return {"parcel": p, "evidence": evidence, "attestations": attestations, "timeline": timeline}
