"""Trust validation, parcel intelligence, risk engine, PDF report rendering."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.config import REPORTS_DIR
from core.database import db
from core.helpers import isoformat, new_id, now_utc


def redact_parcel(parcel: dict, *, redact_owner: bool = True) -> dict:
    p = dict(parcel)
    if redact_owner:
        p.pop("owner_id", None)
        p.pop("tenant_id", None)
        p.pop("description", None)
    return p


async def parcel_intelligence(parcel: dict) -> dict:
    pid = parcel["id"]
    evidence_items = [e async for e in db.evidence_vault.find({"parcel_id": pid}, {"_id": 0})]
    ev_summary = {
        "total": len(evidence_items),
        "approved": sum(1 for e in evidence_items if e["status"] == "APPROVED"),
        "rejected": sum(1 for e in evidence_items if e["status"] == "REJECTED"),
        "pending": sum(1 for e in evidence_items if e["status"] == "PENDING"),
        "sealed": sum(1 for e in evidence_items if e["status"] in ("APPROVED", "SEALED", "LOCKED")),
        "integrity_pass": sum(1 for e in evidence_items if e.get("integrity_verified")),
        "by_type": {},
    }
    for e in evidence_items:
        t = e.get("evidence_type", "OTHER")
        ev_summary["by_type"][t] = ev_summary["by_type"].get(t, 0) + 1

    evidence_safe = [{
        "id": e["id"],
        "evidence_type": e.get("evidence_type"),
        "status": e.get("status"),
        "integrity_verified": bool(e.get("integrity_verified")),
        "file_hash": (e.get("file_hash") or "")[:16] + "…" if e.get("file_hash") else None,
        "uploaded_at": e.get("created_at"),
    } for e in evidence_items]

    attestations = [a async for a in db.community_attestations.find({"parcel_id": pid}, {"_id": 0})]
    att_summary = {
        "total": len(attestations),
        "approved": sum(1 for a in attestations if a["status"] == "APPROVED"),
        "pending": sum(1 for a in attestations if a["status"] == "PENDING"),
        "contested": sum(1 for a in attestations if a["status"] == "CONTESTED"),
        "rejected": sum(1 for a in attestations if a["status"] == "REJECTED"),
    }
    attestations_safe = [{
        "id": a["id"],
        "role": a.get("role"),
        "statement": a.get("statement"),
        "relationship_to_land": a.get("relationship_to_land"),
        "years_of_knowledge": a.get("years_of_knowledge"),
        "status": a.get("status"),
        "submitted_at": a.get("created_at"),
    } for a in attestations]

    timeline = [t async for t in db.evidence_timeline_events.find({"parcel_id": pid}, {"_id": 0}).sort("created_at", -1)]
    certs = [c async for c in db.certificates.find({"parcel_id": pid}, {"_id": 0}).sort("version", -1)]
    disputes = [d async for d in db.dispute_records.find({"parcel_id": pid}, {"_id": 0}).sort("opened_at", -1)]

    return {
        "parcel": redact_parcel(parcel),
        "evidence_summary": ev_summary,
        "evidence": evidence_safe,
        "attestation_summary": att_summary,
        "attestations": attestations_safe,
        "timeline": timeline,
        "certificates": certs,
        "disputes": disputes,
    }


def compute_risk(parcel: dict, evidence_summary: dict, att_summary: dict,
                 disputes: list, certificates: list) -> dict:
    score = 0
    factors: list[dict[str, Any]] = []
    status_v = parcel.get("status")
    if status_v == "VERIFIED":
        score += 35
        factors.append({"k": "status", "v": status_v, "delta": 35})
    elif status_v == "PENDING":
        score += 18
        factors.append({"k": "status", "v": status_v, "delta": 18})
    elif status_v == "UNVERIFIED":
        factors.append({"k": "status", "v": status_v, "delta": 0})
    elif status_v == "DISPUTED":
        score -= 20
        factors.append({"k": "status", "v": status_v, "delta": -20})
    elif status_v == "FROZEN":
        score -= 40
        factors.append({"k": "status", "v": status_v, "delta": -40})

    conf = parcel.get("confidence_score") or 0
    bonus = min(25, conf // 4)
    score += bonus
    factors.append({"k": "confidence", "v": conf, "delta": bonus})

    integ_ratio = (evidence_summary["integrity_pass"] / evidence_summary["total"]) if evidence_summary["total"] else 0
    integ_bonus = int(round(integ_ratio * 15))
    score += integ_bonus
    factors.append({"k": "integrity", "v": f"{integ_ratio*100:.0f}%", "delta": integ_bonus})

    if att_summary["approved"] >= 3:
        score += 15
        factors.append({"k": "attestations", "v": att_summary["approved"], "delta": 15})
    elif att_summary["approved"] >= 1:
        score += 8
        factors.append({"k": "attestations", "v": att_summary["approved"], "delta": 8})
    if att_summary["contested"] > 0:
        score -= 10
        factors.append({"k": "contested_attestations", "v": att_summary["contested"], "delta": -10})

    open_disputes = sum(1 for d in disputes if d.get("status") == "OPEN")
    if open_disputes > 0:
        score -= 25
        factors.append({"k": "open_disputes", "v": open_disputes, "delta": -25})

    active_cert = next((c for c in certificates if c.get("status") == "ACTIVE"), None)
    if active_cert:
        score += 10
        factors.append({"k": "active_certificate", "v": "yes", "delta": 10})

    score = max(0, min(100, score))
    if score >= 75:
        level = "LOW_RISK"
    elif score >= 50:
        level = "MEDIUM_RISK"
    else:
        level = "HIGH_RISK"
    return {"risk_level": level, "risk_score": score, "factors": factors}


async def run_trust_validation_internal() -> dict:
    parcels_total = await db.parcels.count_documents({})
    parcels_verified = await db.parcels.count_documents({"status": "VERIFIED"})
    evidence_total = await db.evidence_vault.count_documents({})
    evidence_with_hash = await db.evidence_vault.count_documents({"file_hash": {"$exists": True, "$ne": None}})
    attestation_total = await db.community_attestations.count_documents({})
    jobs_total = await db.job_queue.count_documents({})
    jobs_completed = await db.job_queue.count_documents({"status": "COMPLETED"})
    audit_total = await db.audit_logs.count_documents({})
    certs_issued = await db.parcels.count_documents({"certificate_status": "ISSUED"})

    def pct(n, d):
        return (n / d * 100) if d else 0.0

    evidence_integrity_score = pct(evidence_with_hash, evidence_total) if evidence_total else 0
    attestation_consensus = pct(attestation_total, parcels_total * 3) if parcels_total else 0
    certificate_coverage = pct(certs_issued, parcels_verified) if parcels_verified else 0
    job_completion_rate = pct(jobs_completed, jobs_total) if jobs_total else 0
    audit_trail_coverage = min(100.0, audit_total)

    overall = round((evidence_integrity_score + attestation_consensus + certificate_coverage +
                     job_completion_rate + audit_trail_coverage) / 5)

    if overall >= 90:
        grade, rec = "A_PLUS", "GO"
    elif overall >= 80:
        grade, rec = "A", "GO"
    elif overall >= 70:
        grade, rec = "B", "CONDITIONAL"
    elif overall >= 60:
        grade, rec = "C", "CONDITIONAL"
    elif overall >= 50:
        grade, rec = "D", "NO_GO"
    else:
        grade, rec = "F", "NO_GO"

    gaps: list[str] = []
    if evidence_total == 0:
        gaps.append("No evidence uploaded yet")
    if certs_issued == 0:
        gaps.append("No certificates issued yet")
    if jobs_total > 0 and job_completion_rate < 80:
        gaps.append("Job queue completion below 80%")
    if attestation_total < parcels_total:
        gaps.append("Attestation coverage incomplete")

    doc = {
        "id": new_id("trust"),
        "overall_score": overall,
        "grade": grade,
        "recommendation": rec,
        "sub_scores": {
            "evidence_integrity": round(evidence_integrity_score),
            "attestation_consensus": round(attestation_consensus),
            "certificate_coverage": round(certificate_coverage),
            "job_completion_rate": round(job_completion_rate),
            "audit_trail_coverage": round(audit_trail_coverage),
        },
        "evidence_count": evidence_total,
        "attestation_count": attestation_total,
        "certificate_count": certs_issued,
        "job_completion_rate": round(job_completion_rate),
        "consensus_coverage": round(attestation_consensus),
        "gaps_identified": gaps,
        "run_at": isoformat(now_utc()),
    }
    await db.trust_validation_runs.insert_one(dict(doc))
    return doc


async def render_legal_report_pdf(report: dict, parcel: dict, intel: dict) -> str:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    out = REPORTS_DIR / f"{report['id']}.pdf"
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], textColor=colors.HexColor("#2e7d52"), fontSize=20, spaceAfter=12)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=colors.HexColor("#1a2e1a"), fontSize=13)
    body = styles["BodyText"]
    small = ParagraphStyle("small", parent=body, fontSize=9, textColor=colors.HexColor("#546e7a"))
    story = [
        Paragraph("Aquasavannah LandVault — Legal Due Diligence", h1),
        Paragraph(f"Report ID: {report['id']}", small),
        Paragraph(f"Generated for: {report.get('requested_by_email')}", small),
        Spacer(1, 8),
        Paragraph("1. Parcel Overview", h2),
    ]
    rows = [
        ["Parcel Number", parcel["parcel_number"]],
        ["Status", parcel.get("status", "—")],
        ["Confidence", f"{parcel.get('confidence_score', 0)}/100"],
        ["Community", parcel.get("community", "—")],
        ["LGA / Ward", f"{parcel.get('lga', '—')} / {parcel.get('ward', '—')}"],
        ["State", parcel.get("state", "—")],
        ["Last update", parcel.get("updated_at") or "—"],
    ]
    t = Table(rows, colWidths=[40 * mm, 110 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e8f5e9")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#1a2e1a")),
        ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 8))

    es = intel["evidence_summary"]
    story.append(Paragraph("2. Evidence Summary", h2))
    story.append(Paragraph(
        f"Total: <b>{es['total']}</b> · Approved: {es['approved']} · "
        f"Pending: {es['pending']} · Rejected: {es['rejected']} · "
        f"SHA-256 integrity pass: {es['integrity_pass']}/{es['total']}", body))
    story.append(Spacer(1, 6))

    a = intel["attestation_summary"]
    story.append(Paragraph("3. Attestation Summary", h2))
    story.append(Paragraph(
        f"Total: <b>{a['total']}</b> · Approved: {a['approved']} · Pending: {a['pending']} · "
        f"Contested: {a['contested']} · Rejected: {a['rejected']}", body))
    story.append(Spacer(1, 6))

    story.append(Paragraph("4. Dispute History", h2))
    if intel["disputes"]:
        d_rows = [["Opened", "Status", "Reason"]] + [
            [(d.get("opened_at") or "—")[:10], d.get("status", "—"), (d.get("reason") or "—")[:80]]
            for d in intel["disputes"]
        ]
        story.append(Table(d_rows, colWidths=[35 * mm, 25 * mm, 90 * mm], style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1565c0")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
        ])))
    else:
        story.append(Paragraph("No disputes on record.", body))
    story.append(Spacer(1, 6))

    story.append(Paragraph("5. Certificate History", h2))
    if intel["certificates"]:
        c_rows = [["Version", "Status", "Generated", "Revoked"]] + [
            [str(c.get("version", "—")), c.get("status", "—"),
             (c.get("generated_at") or "—")[:10], (c.get("revoked_at") or "—")[:10]]
            for c in intel["certificates"]
        ]
        story.append(Table(c_rows, colWidths=[20 * mm, 25 * mm, 35 * mm, 35 * mm], style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2e7d52")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
        ])))
    else:
        story.append(Paragraph("No certificates issued.", body))
    story.append(Spacer(1, 10))

    story.append(Paragraph("6. Legal Disclaimer", h2))
    story.append(Paragraph(
        "Aquasavannah LandVault records submitted evidence and verification events. "
        "It does not determine legal ownership, adjudicate disputes, or replace government "
        "title systems. All records are evidence submissions only. Verification of evidence "
        "does not constitute proof of ownership.",
        small,
    ))

    SimpleDocTemplate(str(out), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                      topMargin=18 * mm, bottomMargin=18 * mm).build(story)
    return out.name


async def render_institution_report_pdf(report: dict, portfolio: dict) -> str:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    out = REPORTS_DIR / f"{report['id']}.pdf"
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], textColor=colors.HexColor("#1565c0"), fontSize=20, spaceAfter=12)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=colors.HexColor("#1a2e1a"), fontSize=13)
    body = styles["BodyText"]
    small = ParagraphStyle("small", parent=body, fontSize=9, textColor=colors.HexColor("#546e7a"))
    rc = portfolio.get("risk_counts", {})
    story = [
        Paragraph("Aquasavannah LandVault — Institutional Due Diligence", h1),
        Paragraph(f"Portfolio: {portfolio['name']}", small),
        Paragraph(f"Report ID: {report['id']}", small),
        Spacer(1, 8),
        Paragraph("1. Portfolio Summary", h2),
        Table([
            ["Total parcels", str(portfolio.get("total_parcels", 0))],
            ["LOW RISK", str(rc.get("LOW_RISK", 0))],
            ["MEDIUM RISK", str(rc.get("MEDIUM_RISK", 0))],
            ["HIGH RISK", str(rc.get("HIGH_RISK", 0))],
        ], colWidths=[60 * mm, 90 * mm], style=TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e3f2fd")),
            ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ])),
        Spacer(1, 8),
        Paragraph("2. Parcel Risk Breakdown", h2),
    ]
    rows = [["#", "Parcel", "Status", "Conf.", "Risk", "Score"]]
    for i, it in enumerate(portfolio.get("items", []), 1):
        rows.append([
            str(i), it.get("parcel_number", "—"),
            it.get("status") or "NOT FOUND",
            str(it.get("confidence_score", 0)),
            it.get("risk_level", "—"),
            str(it.get("risk_score", 0)),
        ])
    story.append(Table(rows, colWidths=[10 * mm, 40 * mm, 30 * mm, 18 * mm, 30 * mm, 20 * mm], style=TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1565c0")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
    ])))
    story.append(Spacer(1, 8))
    story.append(Paragraph("3. Recommendations", h2))
    if rc.get("HIGH_RISK", 0):
        story.append(Paragraph(
            f"<b>{rc['HIGH_RISK']} parcel(s) flagged HIGH RISK.</b> Recommend independent "
            "field verification before any transaction.", body))
    if rc.get("MEDIUM_RISK", 0):
        story.append(Paragraph(
            f"{rc['MEDIUM_RISK']} parcel(s) flagged MEDIUM RISK. Recommend additional "
            "attestations or fresh survey plan before relying on these records.", body))
    if rc.get("LOW_RISK", 0):
        story.append(Paragraph(
            f"{rc['LOW_RISK']} parcel(s) flagged LOW RISK. Standard transactional diligence applies.",
            body))
    story.append(Spacer(1, 10))
    story.append(Paragraph("4. Legal Disclaimer", h2))
    story.append(Paragraph(
        "Aquasavannah LandVault records submitted evidence and verification events. "
        "It does not determine legal ownership, adjudicate disputes, or replace government "
        "title systems. All records are evidence submissions only.",
        small,
    ))
    SimpleDocTemplate(str(out), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                      topMargin=18 * mm, bottomMargin=18 * mm).build(story)
    return out.name
