"""Admin command centre: overview, users/parcels/evidence/jobs/audit views, trust + readiness."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core.audit import audit_log, timeline_event
from core.database import db
from core.helpers import isoformat, new_id, now_utc
from core.security import require_role
from services.jobs import process_job_queue_internal
from services.trust import run_trust_validation_internal

router = APIRouter(prefix="/admin")


@router.get("/overview")
async def overview(user: dict = Depends(require_role("ADMIN"))) -> dict:
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
            "total_users": total_users, "total_parcels": total_parcels,
            "verified_parcels": verified, "total_evidence": evidence,
            "total_attestations": attestations, "open_incidents": incidents_open,
        },
        "jobs": {"pending": jobs_pending, "processing": jobs_processing,
                 "completed": jobs_completed, "failed": jobs_failed},
        "layers": layers,
    }


@router.get("/users")
async def users(user: dict = Depends(require_role("ADMIN"))) -> dict:
    items = [u async for u in db.users.find({}, {"_id": 0}).sort("created_at", -1).limit(200)]
    return {"items": items}


@router.get("/parcels")
async def parcels(user: dict = Depends(require_role("ADMIN"))) -> dict:
    items = [p async for p in db.parcels.find({}, {"_id": 0}).sort("created_at", -1).limit(200)]
    return {"items": items}


@router.get("/evidence")
async def evidence(user: dict = Depends(require_role("ADMIN"))) -> dict:
    items = [e async for e in db.evidence_vault.find({}, {"_id": 0}).sort("created_at", -1).limit(200)]
    return {"items": items}


@router.post("/evidence/{evidence_id}/approve")
async def approve_evidence(evidence_id: str, user: dict = Depends(require_role("ADMIN"))) -> dict:
    ev = await db.evidence_vault.find_one({"id": evidence_id}, {"_id": 0})
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence not found")
    await db.evidence_vault.update_one(
        {"id": evidence_id},
        {"$set": {"status": "APPROVED", "seal_date": isoformat(now_utc())}},
    )
    await timeline_event(ev["parcel_id"], "EVIDENCE_APPROVED",
                         f"Evidence {ev['file_name']} approved.",
                         actor=user, tenant_id=ev.get("tenant_id"))
    await audit_log("EVIDENCE_APPROVED", "evidence", evidence_id, user=user, before=ev)
    return {"ok": True}


@router.get("/jobs")
async def jobs(user: dict = Depends(require_role("ADMIN"))) -> dict:
    items = [j async for j in db.job_queue.find({}, {"_id": 0}).sort("created_at", -1).limit(200)]
    return {"items": items}


@router.post("/jobs/process")
async def jobs_process(user: dict = Depends(require_role("ADMIN"))) -> dict:
    processed = await process_job_queue_internal()
    return {"processed": processed}


@router.get("/audit-logs")
async def audit_logs(user: dict = Depends(require_role("ADMIN"))) -> dict:
    items = [a async for a in db.audit_logs.find({}, {"_id": 0}).sort("created_at", -1).limit(200)]
    return {"items": items}


@router.get("/security")
async def security(user: dict = Depends(require_role("ADMIN"))) -> dict:
    incidents = [s async for s in db.security_incidents.find({}, {"_id": 0}).sort("detected_at", -1).limit(100)]
    return {"incidents": incidents}


@router.post("/security/scan")
async def security_scan(user: dict = Depends(require_role("ADMIN"))) -> dict:
    issues = []
    stuck_jobs = await db.job_queue.count_documents({"status": "PROCESSING"})
    if stuck_jobs > 5:
        issues.append({"type": "STUCK_JOBS", "severity": "MEDIUM",
                       "description": f"{stuck_jobs} jobs stuck in PROCESSING."})
    incident_doc = None
    if issues:
        incident_doc = {
            "id": new_id("inc"), "incident_type": "SECURITY_SCAN", "severity": "MEDIUM",
            "description": f"Scan found {len(issues)} issues.", "status": "OPEN",
            "detected_at": isoformat(now_utc()), "resolved_at": None,
            "resolution_notes": None, "issues": issues, "tenant_id": None,
        }
        await db.security_incidents.insert_one(dict(incident_doc))
    await audit_log("SECURITY_SCAN_RUN", "security", "scan", user=user, metadata={"issues": len(issues)})
    return {"issues": issues, "incident": incident_doc}


@router.post("/trust/run")
async def trust_run(user: dict = Depends(require_role("ADMIN"))) -> dict:
    doc = await run_trust_validation_internal()
    await audit_log("TRUST_VALIDATION_RUN", "trust", doc["id"], user=user)
    return {"run": doc}


@router.get("/trust/latest")
async def trust_latest(user: dict = Depends(require_role("ADMIN"))) -> dict:
    doc = await db.trust_validation_runs.find_one({}, {"_id": 0}, sort=[("run_at", -1)])
    if not doc:
        doc = await run_trust_validation_internal()
    return {"run": doc}


@router.get("/readiness")
async def readiness(user: dict = Depends(require_role("ADMIN"))) -> dict:
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
        "overall_score": overall, "readiness_level": level, "sub_scores": sub,
        "blocking_gaps": blocking, "non_blocking_gaps": non_blocking,
        "assessed_at": isoformat(now_utc()),
    }
