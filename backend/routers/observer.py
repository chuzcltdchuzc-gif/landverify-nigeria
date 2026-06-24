"""Observer (read-only, anonymised) intelligence endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from core.audit import audit_log
from core.database import db
from core.security import require_role

router = APIRouter(prefix="/observer")


@router.get("/intelligence")
async def intelligence(user: dict = Depends(require_role("GOVERNMENT_OBSERVER"))) -> dict:
    kpis = {
        "total_parcels": await db.parcels.count_documents({}),
        "verified": await db.parcels.count_documents({"status": "VERIFIED"}),
        "pending": await db.parcels.count_documents({"status": "PENDING"}),
        "unverified": await db.parcels.count_documents({"status": "UNVERIFIED"}),
        "disputed": await db.parcels.count_documents({"status": "DISPUTED"}),
        "archived": await db.parcels.count_documents({"status": "FROZEN"}),
    }
    await audit_log("DASHBOARD_ACCESSED", "observer_intelligence", "overview", user=user)
    return {"kpis": kpis}


@router.get("/regional")
async def regional(user: dict = Depends(require_role("GOVERNMENT_OBSERVER"))) -> dict:
    agg: dict[str, dict[str, Any]] = {}
    async for p in db.parcels.find({}, {"_id": 0}):
        state = p.get("state") or "Unknown"
        lga = p.get("lga") or "Unknown"
        community = p.get("community") or "Unknown"
        st = agg.setdefault(state, {"state": state, "parcels": 0, "verified": 0,
                                    "evidence": 0, "attestations": 0, "lgas": {}})
        st["parcels"] += 1
        if p.get("status") == "VERIFIED":
            st["verified"] += 1
        st["evidence"] += p.get("evidence_count", 0)
        st["attestations"] += p.get("attestation_count", 0)
        lga_node = st["lgas"].setdefault(lga, {"lga": lga, "parcels": 0, "verified": 0,
                                               "communities": {}})
        lga_node["parcels"] += 1
        if p.get("status") == "VERIFIED":
            lga_node["verified"] += 1
        c_node = lga_node["communities"].setdefault(community,
                                                    {"community": community, "parcels": 0, "verified": 0})
        c_node["parcels"] += 1
        if p.get("status") == "VERIFIED":
            c_node["verified"] += 1
    out = []
    for st in agg.values():
        st_rate = (st["verified"] / st["parcels"] * 100) if st["parcels"] else 0
        lgas = []
        for lga_node in st["lgas"].values():
            lga_rate = (lga_node["verified"] / lga_node["parcels"] * 100) if lga_node["parcels"] else 0
            communities = list(lga_node["communities"].values())
            for c in communities:
                c["verification_rate"] = round((c["verified"] / c["parcels"] * 100) if c["parcels"] else 0, 1)
            lgas.append({**{k: v for k, v in lga_node.items() if k != "communities"},
                         "verification_rate": round(lga_rate, 1), "communities": communities})
        out.append({**{k: v for k, v in st.items() if k != "lgas"},
                    "verification_rate": round(st_rate, 1), "lgas": lgas})
    return {"by_state": out}


@router.get("/confidence-distribution")
async def confidence_distribution(user: dict = Depends(require_role("GOVERNMENT_OBSERVER"))) -> dict:
    buckets = {"90-100": 0, "80-89": 0, "70-79": 0, "below_70": 0}
    async for p in db.parcels.find({}, {"_id": 0, "confidence_score": 1}):
        s = p.get("confidence_score") or 0
        if s >= 90:
            buckets["90-100"] += 1
        elif s >= 80:
            buckets["80-89"] += 1
        elif s >= 70:
            buckets["70-79"] += 1
        else:
            buckets["below_70"] += 1
    return {"buckets": buckets}


@router.get("/evidence-analytics")
async def evidence_analytics(user: dict = Depends(require_role("GOVERNMENT_OBSERVER"))) -> dict:
    by_type: dict[str, int] = {}
    total = 0
    integrity_pass = 0
    approved = 0
    async for e in db.evidence_vault.find({}, {"_id": 0}):
        total += 1
        by_type[e.get("evidence_type", "OTHER")] = by_type.get(e.get("evidence_type", "OTHER"), 0) + 1
        if e.get("integrity_verified"):
            integrity_pass += 1
        if e.get("status") == "APPROVED":
            approved += 1
    return {
        "total_evidence": total, "by_type": by_type,
        "integrity_pass_rate": round(integrity_pass / total * 100, 1) if total else 0,
        "verification_success_rate": round(approved / total * 100, 1) if total else 0,
    }


@router.get("/timeline")
async def timeline(user: dict = Depends(require_role("GOVERNMENT_OBSERVER"))) -> dict:
    items = []
    async for t in db.evidence_timeline_events.find({}, {"_id": 0}).sort("created_at", -1).limit(50):
        items.append({"id": t["id"], "event_type": t["event_type"],
                      "description": t.get("description"),
                      "occurred_at": t.get("created_at")})
    return {"items": items}


@router.get("/dashboard")
async def dashboard(user: dict = Depends(require_role("GOVERNMENT_OBSERVER"))) -> dict:
    intel = await intelligence(user)
    conf = await confidence_distribution(user)
    ev = await evidence_analytics(user)
    reg = await regional(user)
    tl = await timeline(user)
    return {
        "intelligence": intel["kpis"],
        "confidence_distribution": conf["buckets"],
        "evidence_analytics": ev,
        "regional": reg["by_state"],
        "timeline": tl["items"],
    }
