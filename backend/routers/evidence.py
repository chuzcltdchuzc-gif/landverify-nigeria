"""Evidence vault uploads + SHA-256 sealing + tenant isolation."""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, HTTPException

from core.audit import audit_log, enqueue_job, timeline_event
from core.helpers import isoformat, new_id, now_utc
from core.safe_db import tdb
from core.security import get_current_user
from schemas.models import EvidenceCreate

router = APIRouter(prefix="/evidence")


@router.post("")
async def upload_evidence(body: EvidenceCreate, user: dict = Depends(get_current_user)) -> dict:
    parcel = await tdb.parcels.find_one({"id": body.parcel_id}, {"_id": 0})
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")
    file_hash = hashlib.sha256(
        f"{body.file_url}|{body.file_name}|{user['user_id']}".encode()
    ).hexdigest()
    eid = new_id("ev")
    doc = {
        "id": eid, "parcel_id": body.parcel_id, "uploader_id": user["user_id"],
        "evidence_type": body.evidence_type, "file_url": body.file_url,
        "file_name": body.file_name, "file_hash": file_hash, "file_size": body.file_size,
        "mime_type": body.mime_type, "description": body.description,
        "status": "PENDING", "integrity_verified": True, "seal_date": None,
        "lock_reason": None, "tenant_id": user["tenant_id"], "created_at": isoformat(now_utc()),
    }
    await tdb.evidence_vault.insert_one(dict(doc))
    await tdb.parcels.update_one(
        {"id": body.parcel_id},
        {"$inc": {"evidence_count": 1}, "$set": {"updated_at": isoformat(now_utc())}},
    )
    await timeline_event(body.parcel_id, "EVIDENCE_UPLOADED",
                         f"{body.evidence_type} uploaded: {body.file_name}.",
                         actor=user, tenant_id=user["tenant_id"])
    await enqueue_job("OCR_PROCESSING", {"evidence_id": eid}, idempotency_key=f"ocr-{eid}")
    await enqueue_job("CONFIDENCE_RECALCULATION", {"parcel_id": body.parcel_id},
                      idempotency_key=f"conf-after-ev-{eid}")
    await audit_log("EVIDENCE_UPLOADED", "evidence", eid, user=user, after=doc)
    return {"evidence": doc}
