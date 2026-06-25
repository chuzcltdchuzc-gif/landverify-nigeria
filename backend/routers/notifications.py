"""Notification feed — recent timeline events + reports (tenant-scoped)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from core.safe_db import tdb
from core.security import get_current_user

router = APIRouter()


@router.get("/notifications")
async def notifications(user: dict = Depends(get_current_user)) -> dict:
    items: list[dict] = []
    parcels = await tdb.parcels.find({"owner_id": user["user_id"]}).distinct("id")
    if parcels:
        async for t in tdb.evidence_timeline_events.find(
                {"parcel_id": {"$in": parcels}}, {"_id": 0}).sort("created_at", -1).limit(15):
            items.append({
                "type": "TIMELINE", "id": t["id"], "title": t.get("event_type"),
                "description": t.get("description"), "occurred_at": t.get("created_at"),
            })
    async for r in tdb.reports.find({"requested_by": user["user_id"]}, {"_id": 0}) \
            .sort("requested_at", -1).limit(15):
        title = "REPORT_READY" if r["status"] == "COMPLETED" else f"REPORT_{r['status']}"
        items.append({
            "type": "REPORT", "id": r["id"], "title": title,
            "description": f"{r['type']} · {r.get('parcel_number') or r.get('portfolio_id') or ''}".strip(" ·"),
            "occurred_at": r.get("completed_at") or r.get("requested_at"),
            "download_url": r.get("result_url"),
        })
    items.sort(key=lambda x: x.get("occurred_at") or "", reverse=True)
    return {"items": items[:30]}
