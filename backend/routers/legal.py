"""Legal portal endpoints: search, parcel intel, due-diligence reports."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from core.audit import audit_log, enqueue_job
from core.config import REPORTS_DIR
from core.database import db
from core.helpers import isoformat, new_id, now_utc
from core.security import require_role
from services.trust import parcel_intelligence, redact_parcel

router = APIRouter(prefix="/legal")


@router.get("/dashboard")
async def dashboard(user: dict = Depends(require_role("LEGAL"))) -> dict:
    total_parcels = await db.parcels.count_documents({})
    verified = await db.parcels.count_documents({"status": "VERIFIED"})
    pending = await db.parcels.count_documents({"status": "PENDING"})
    disputed = await db.parcels.count_documents({"status": "DISPUTED"})
    open_disp = await db.dispute_records.count_documents({"status": "OPEN"})
    closed_disp = await db.dispute_records.count_documents({"status": "CLOSED"})
    active_certs = await db.certificates.count_documents({"status": "ACTIVE"})
    revoked_certs = await db.certificates.count_documents({"status": "REVOKED"})
    recent = [redact_parcel(p) async for p in db.parcels.find({}, {"_id": 0}).sort("updated_at", -1).limit(10)]
    my_reports = [r async for r in db.reports.find(
        {"requested_by": user["user_id"]}, {"_id": 0}).sort("requested_at", -1).limit(10)]
    await audit_log("DASHBOARD_ACCESSED", "legal_dashboard", "overview", user=user)
    return {
        "kpis": {
            "total_parcels": total_parcels, "verified": verified, "pending": pending,
            "disputed": disputed, "open_disputes": open_disp, "closed_disputes": closed_disp,
            "active_certificates": active_certs, "revoked_certificates": revoked_certs,
        },
        "recent": recent, "my_reports": my_reports,
    }


@router.get("/search")
async def search(
    q: Optional[str] = None,
    state: Optional[str] = None,
    lga: Optional[str] = None,
    ward: Optional[str] = None,
    community: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 50,
    skip: int = 0,
    user: dict = Depends(require_role("LEGAL")),
) -> dict:
    query: dict[str, Any] = {}
    if q:
        query["$or"] = [
            {"parcel_number": {"$regex": q, "$options": "i"}},
            {"community": {"$regex": q, "$options": "i"}},
        ]
    for field, val in (("state", state), ("lga", lga), ("ward", ward),
                       ("community", community), ("status", status_filter)):
        if val:
            query[field] = val
    limit = max(1, min(200, limit))
    cur = db.parcels.find(query, {"_id": 0}).sort("updated_at", -1).skip(max(0, skip)).limit(limit)
    items = [redact_parcel(p) async for p in cur]
    total = await db.parcels.count_documents(query)
    await audit_log("DASHBOARD_ACCESSED", "legal_search", q or "", user=user, metadata={"results": total})
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.get("/parcel/{parcel_id}")
async def parcel_detail(parcel_id: str, user: dict = Depends(require_role("LEGAL"))) -> dict:
    parcel = await db.parcels.find_one({"id": parcel_id}, {"_id": 0})
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")
    intel = await parcel_intelligence(parcel)
    await audit_log("CERTIFICATE_VIEWED", "parcel", parcel_id, user=user)
    return intel


@router.post("/report/{parcel_id}")
async def request_report(parcel_id: str, user: dict = Depends(require_role("LEGAL"))) -> dict:
    parcel = await db.parcels.find_one({"id": parcel_id}, {"_id": 0})
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")
    rid = new_id("rep")
    doc = {
        "id": rid, "type": "LEGAL_DUE_DILIGENCE", "parcel_id": parcel_id,
        "parcel_number": parcel["parcel_number"], "requested_by": user["user_id"],
        "requested_by_email": user["email"], "status": "PENDING", "result_url": None,
        "requested_at": isoformat(now_utc()), "completed_at": None,
        "tenant_id": user["tenant_id"],
    }
    await db.reports.insert_one(dict(doc))
    await enqueue_job("LEGAL_REPORT",
                      {"report_id": rid, "parcel_id": parcel_id, "user_id": user["user_id"]},
                      idempotency_key=f"legal-rep-{rid}")
    await audit_log("LEGAL_REPORT_GENERATED", "report", rid, user=user,
                    metadata={"parcel_id": parcel_id})
    return {"report": doc}


@router.get("/reports")
async def reports(user: dict = Depends(require_role("LEGAL"))) -> dict:
    items = [r async for r in db.reports.find(
        {"requested_by": user["user_id"], "type": "LEGAL_DUE_DILIGENCE"}, {"_id": 0}
    ).sort("requested_at", -1)]
    return {"items": items}


@router.get("/reports/{report_id}/download")
async def report_download(report_id: str, user: dict = Depends(require_role("LEGAL"))):
    r = await db.reports.find_one({"id": report_id, "requested_by": user["user_id"]}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    if r["status"] != "COMPLETED" or not r.get("filename"):
        raise HTTPException(status_code=409, detail="Report not ready")
    path = REPORTS_DIR / r["filename"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report file missing")
    await audit_log("CERTIFICATE_DOWNLOADED", "report", report_id, user=user)
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@router.get("/reports/{report_id}/download.csv")
async def report_download_csv(report_id: str, user: dict = Depends(require_role("LEGAL"))):
    r = await db.reports.find_one({"id": report_id, "requested_by": user["user_id"]}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    if r["status"] != "COMPLETED" or not r.get("csv_filename"):
        raise HTTPException(status_code=409, detail="CSV not ready")
    path = REPORTS_DIR / r["csv_filename"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="CSV file missing")
    await audit_log("CERTIFICATE_DOWNLOADED", "report_csv", report_id, user=user)
    return FileResponse(path, media_type="text/csv", filename=path.name)
