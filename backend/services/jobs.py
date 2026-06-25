"""Background job processor + executor + seed routine.

`process_job_queue_internal` is invoked from the admin router and (in production)
should be scheduled every 5 minutes. `_execute_job` dispatches per job_type.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import timedelta

from core.audit import timeline_event
from core.database import db
from core.helpers import isoformat, new_id, now_utc
from services.trust import (
    parcel_intelligence,
    render_institution_report_csv,
    render_institution_report_pdf,
    render_legal_report_csv,
    render_legal_report_pdf,
    run_trust_validation_internal,
)

logger = logging.getLogger("landvault.jobs")


async def upsert_user(email: str, name: str, role: str) -> dict:
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    target_balance = 250 if role == "CITIZEN" else 1000
    if existing:
        # Top up demo wallets back to baseline on every startup so end-to-end
        # tests that drain the wallet don't break subsequent runs.
        wallet = await db.credit_wallets.find_one({"user_id": existing["user_id"]}, {"_id": 0})
        if wallet and wallet.get("balance", 0) < target_balance:
            await db.credit_wallets.update_one(
                {"user_id": existing["user_id"]},
                {"$set": {"balance": target_balance, "total_consumed": 0,
                          "total_purchased": target_balance}},
            )
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
    await db.credit_wallets.insert_one({
        "id": new_id("wallet"),
        "user_id": user_id,
        "balance": target_balance,
        "reserved_credits": 0,
        "total_purchased": target_balance,
        "total_consumed": 0,
        "status": "ACTIVE",
        "tenant_id": tenant_id,
        "created_at": isoformat(now_utc()),
    })
    doc.pop("_id", None)
    return doc


async def seed_demo_data() -> None:
    """Idempotent demo data seeding.

    Demo users are upserted on every startup (so newly-added roles like
    LEGAL/INSTITUTIONAL/OBSERVER are filled in for an existing installation).
    Heavy seed data (parcels, evidence, certificates, …) only runs once when
    the registry is empty.
    """
    logger.info("Ensuring demo users…")
    citizen = await upsert_user("citizen.demo@landvault.test", "Adaeze Okafor", "CITIZEN")
    validator = await upsert_user("validator.demo@landvault.test", "Chief Ibrahim Bello", "COMMUNITY_VALIDATOR")
    await upsert_user("surveyor.demo@landvault.test", "Engr. Yemi Adeniran", "SURVEYOR")
    await upsert_user("admin.demo@landvault.test", "Platform Admin", "ADMIN")
    await upsert_user("legal.demo@landvault.test", "Barr. Chinwe Eze", "LEGAL_USER")
    await upsert_user("institution.demo@landvault.test", "First Trust Bank Ltd.", "INSTITUTIONAL_USER")
    await upsert_user("observer.demo@landvault.test", "Lagos State Land Bureau", "OBSERVER")

    if await db.parcels.count_documents({}) > 0:
        return  # heavy seed already ran

    logger.info("Seeding demo parcels / evidence / attestations…")

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

    async for p in db.parcels.find({}, {"_id": 0}):
        if p.get("certificate_status") == "ISSUED":
            await db.certificates.insert_one({
                "id": new_id("cert"),
                "parcel_id": p["id"],
                "parcel_number": p["parcel_number"],
                "version": 1,
                "status": "ACTIVE",
                "generated_at": isoformat(now_utc() - timedelta(days=2)),
                "revoked_at": None,
                "signed_url": f"/api/legal/certificate/{p['id']}/v1/download",
                "issued_by": "Platform",
                "tenant_id": p["tenant_id"],
            })
        if p.get("status") == "DISPUTED":
            await db.dispute_records.insert_one({
                "id": new_id("disp"),
                "parcel_id": p["id"],
                "parcel_number": p["parcel_number"],
                "status": "OPEN",
                "reason": "Conflicting attestation from neighbouring family.",
                "opened_at": isoformat(now_utc() - timedelta(days=5)),
                "closed_at": None,
                "resolution_status": None,
                "tenant_id": p["tenant_id"],
            })

    await run_trust_validation_internal()
    logger.info("Demo data seeded.")


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
                score = 0
                score += min(30, ev_count * 10)
                score += min(30, att_count * 6)
                score += 20 if survey_count > 0 else 0
                score += 10
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
    if jt == "LEGAL_REPORT":
        rid = payload.get("report_id")
        pid = payload.get("parcel_id")
        if not (rid and pid):
            return {"skipped": True}
        report = await db.reports.find_one({"id": rid}, {"_id": 0})
        parcel = await db.parcels.find_one({"id": pid}, {"_id": 0})
        if not report or not parcel:
            return {"skipped": True}
        intel = await parcel_intelligence(parcel)
        filename = await render_legal_report_pdf(report, parcel, intel)
        csv_name = await render_legal_report_csv(report, parcel, intel)
        url = f"/api/legal/reports/{rid}/download"
        csv_url = f"/api/legal/reports/{rid}/download.csv"
        await db.reports.update_one(
            {"id": rid},
            {"$set": {"status": "COMPLETED", "result_url": url, "filename": filename,
                      "csv_url": csv_url, "csv_filename": csv_name,
                      "completed_at": isoformat(now_utc())}},
        )
        return {"report_id": rid, "filename": filename, "csv_filename": csv_name}
    if jt == "INSTITUTION_REPORT":
        rid = payload.get("report_id")
        pf_id = payload.get("portfolio_id")
        if not (rid and pf_id):
            return {"skipped": True}
        report = await db.reports.find_one({"id": rid}, {"_id": 0})
        portfolio = await db.portfolios.find_one({"id": pf_id}, {"_id": 0})
        if not report or not portfolio:
            return {"skipped": True}
        filename = await render_institution_report_pdf(report, portfolio)
        csv_name = await render_institution_report_csv(report, portfolio)
        url = f"/api/institution/reports/{rid}/download"
        csv_url = f"/api/institution/reports/{rid}/download.csv"
        await db.reports.update_one(
            {"id": rid},
            {"$set": {"status": "COMPLETED", "result_url": url, "filename": filename,
                      "csv_url": csv_url, "csv_filename": csv_name,
                      "completed_at": isoformat(now_utc())}},
        )
        return {"report_id": rid, "filename": filename, "csv_filename": csv_name}
    return {"mocked": True}


async def process_job_queue_internal() -> int:
    pending = [j async for j in db.job_queue.find({"status": "PENDING"}, {"_id": 0}).limit(10)]
    processed = 0
    for job in pending:
        await db.job_queue.update_one(
            {"id": job["id"]},
            {"$set": {"status": "PROCESSING", "started_at": isoformat(now_utc())},
             "$inc": {"attempts": 1}},
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
