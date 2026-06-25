"""Institutional portal: portfolios, batch verification, risk engine, reports."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from core.audit import audit_log, enqueue_job
from core.config import REPORTS_DIR
from core.database import db
from core.helpers import isoformat, new_id, now_utc
from core.security import require_role
from schemas.models import PortfolioCreate
from services.trust import compute_risk

router = APIRouter(prefix="/institution")


@router.get("/dashboard")
async def dashboard(user: dict = Depends(require_role("INSTITUTIONAL"))) -> dict:
    portfolios = [p async for p in db.portfolios.find(
        {"owner_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).limit(20)]
    risk_counts = {"LOW_RISK": 0, "MEDIUM_RISK": 0, "HIGH_RISK": 0}
    parcel_ids: set[str] = set()
    for p in portfolios:
        for item in p.get("items", []):
            rl = item.get("risk_level")
            if rl in risk_counts:
                risk_counts[rl] += 1
            if item.get("parcel_id"):
                parcel_ids.add(item["parcel_id"])
    verified = await db.parcels.count_documents(
        {"id": {"$in": list(parcel_ids)}, "status": "VERIFIED"}) if parcel_ids else 0
    unverified = max(0, len(parcel_ids) - verified)
    open_disp = await db.dispute_records.count_documents(
        {"parcel_id": {"$in": list(parcel_ids)}, "status": "OPEN"}) if parcel_ids else 0
    expired_certs = await db.certificates.count_documents(
        {"parcel_id": {"$in": list(parcel_ids)}, "status": "REVOKED"}) if parcel_ids else 0
    my_reports = [r async for r in db.reports.find(
        {"requested_by": user["user_id"], "type": "INSTITUTION_REPORT"}, {"_id": 0}
    ).sort("requested_at", -1).limit(10)]
    await audit_log("DASHBOARD_ACCESSED", "institution_dashboard", "overview", user=user)
    return {
        "kpis": {
            "portfolios": len(portfolios), "tracked_parcels": len(parcel_ids),
            "verified_parcels": verified, "unverified_parcels": unverified,
            "open_disputes": open_disp, "expired_certificates": expired_certs,
        },
        "risk_breakdown": risk_counts,
        "portfolios": portfolios,
        "my_reports": my_reports,
    }


async def _build_portfolio(name: str, parcel_numbers: list[str], user: dict) -> dict:
    pid = new_id("pf")
    items: list[dict] = []
    risk_counts = {"LOW_RISK": 0, "MEDIUM_RISK": 0, "HIGH_RISK": 0}
    for pn in {p.strip().upper() for p in parcel_numbers if p and p.strip()}:
        parcel = await db.parcels.find_one({"parcel_number": pn}, {"_id": 0})
        if not parcel:
            items.append({"parcel_number": pn, "found": False, "risk_level": "HIGH_RISK",
                          "risk_score": 0, "status": None, "confidence_score": 0,
                          "factors": [{"k": "not_in_registry", "v": True, "delta": -50}]})
            risk_counts["HIGH_RISK"] += 1
            continue
        ev_items = [e async for e in db.evidence_vault.find({"parcel_id": parcel["id"]}, {"_id": 0})]
        ev_summary = {"total": len(ev_items),
                      "integrity_pass": sum(1 for e in ev_items if e.get("integrity_verified"))}
        atts = [a async for a in db.community_attestations.find({"parcel_id": parcel["id"]}, {"_id": 0})]
        att_summary = {"approved": sum(1 for a in atts if a["status"] == "APPROVED"),
                       "contested": sum(1 for a in atts if a["status"] == "CONTESTED")}
        disp = [d async for d in db.dispute_records.find({"parcel_id": parcel["id"]}, {"_id": 0})]
        certs = [c async for c in db.certificates.find({"parcel_id": parcel["id"]}, {"_id": 0})]
        risk = compute_risk(parcel, ev_summary, att_summary, disp, certs)
        risk_counts[risk["risk_level"]] += 1
        items.append({
            "parcel_id": parcel["id"], "parcel_number": parcel["parcel_number"], "found": True,
            "community": parcel.get("community"), "lga": parcel.get("lga"),
            "state": parcel.get("state"), "status": parcel["status"],
            "confidence_score": parcel.get("confidence_score", 0), **risk,
        })
    doc = {
        "id": pid, "name": name, "owner_id": user["user_id"], "items": items,
        "risk_counts": risk_counts, "total_parcels": len(items),
        "created_at": isoformat(now_utc()), "tenant_id": user["tenant_id"],
    }
    await db.portfolios.insert_one(dict(doc))
    return doc


@router.post("/portfolio")
async def create_portfolio(body: PortfolioCreate, user: dict = Depends(require_role("INSTITUTIONAL"))) -> dict:
    doc = await _build_portfolio(body.name, body.parcel_numbers, user)
    await audit_log("BULK_VERIFICATION_RUN", "portfolio", doc["id"], user=user,
                    metadata={"size": doc["total_parcels"]})
    return {"portfolio": doc}


@router.get("/portfolio/{portfolio_id}")
async def get_portfolio(portfolio_id: str, user: dict = Depends(require_role("INSTITUTIONAL"))) -> dict:
    doc = await db.portfolios.find_one({"id": portfolio_id, "owner_id": user["user_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return {"portfolio": doc}


@router.post("/portfolio/{portfolio_id}/recalculate")
async def recalculate(portfolio_id: str, user: dict = Depends(require_role("INSTITUTIONAL"))) -> dict:
    doc = await db.portfolios.find_one({"id": portfolio_id, "owner_id": user["user_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    parcel_numbers = [it["parcel_number"] for it in doc.get("items", [])]
    rebuilt = await _build_portfolio(doc["name"] + " (recalc)", parcel_numbers, user)
    await audit_log("BULK_VERIFICATION_RUN", "portfolio", rebuilt["id"], user=user,
                    metadata={"recalc_of": portfolio_id})
    return {"portfolio": rebuilt}


@router.post("/report/{portfolio_id}")
async def request_report(portfolio_id: str, user: dict = Depends(require_role("INSTITUTIONAL"))) -> dict:
    portfolio = await db.portfolios.find_one(
        {"id": portfolio_id, "owner_id": user["user_id"]}, {"_id": 0})
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    rid = new_id("rep")
    doc = {
        "id": rid, "type": "INSTITUTION_REPORT", "portfolio_id": portfolio_id,
        "requested_by": user["user_id"], "requested_by_email": user["email"],
        "status": "PENDING", "result_url": None,
        "requested_at": isoformat(now_utc()), "completed_at": None,
        "tenant_id": user["tenant_id"],
    }
    await db.reports.insert_one(dict(doc))
    await enqueue_job("INSTITUTION_REPORT",
                      {"report_id": rid, "portfolio_id": portfolio_id, "user_id": user["user_id"]},
                      idempotency_key=f"inst-rep-{rid}")
    await audit_log("INSTITUTION_REPORT_GENERATED", "report", rid, user=user,
                    metadata={"portfolio_id": portfolio_id})
    return {"report": doc}


@router.get("/reports")
async def reports_list(user: dict = Depends(require_role("INSTITUTIONAL"))) -> dict:
    items = [r async for r in db.reports.find(
        {"requested_by": user["user_id"], "type": "INSTITUTION_REPORT"}, {"_id": 0}
    ).sort("requested_at", -1)]
    return {"items": items}


@router.get("/reports/{report_id}/download")
async def report_download(report_id: str, user: dict = Depends(require_role("INSTITUTIONAL"))):
    r = await db.reports.find_one({"id": report_id, "requested_by": user["user_id"]}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    if r["status"] != "COMPLETED" or not r.get("result_url"):
        raise HTTPException(status_code=409, detail="Report not ready")
    path = REPORTS_DIR / Path(r["result_url"]).name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report file missing")
    await audit_log("CERTIFICATE_DOWNLOADED", "report", report_id, user=user)
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@router.get("/reports/{report_id}/download.csv")
async def report_download_csv(report_id: str, user: dict = Depends(require_role("INSTITUTIONAL"))):
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
