"""Append-only audit log + timeline events + idempotent job queue inserts."""
from __future__ import annotations

import logging
from typing import Optional

from core.database import db
from core.helpers import isoformat, new_id, now_utc, serialize_doc

logger = logging.getLogger("landvault.audit")


async def audit_log(
    action: str,
    entity_type: str,
    entity_id: str,
    user: Optional[dict] = None,
    tenant_id: Optional[str] = None,
    before: Optional[dict] = None,
    after: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> None:
    entry = {
        "id": new_id("audit"),
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "user_id": user.get("user_id") if user else None,
        "user_email": user.get("email") if user else None,
        "tenant_id": tenant_id or (user.get("tenant_id") if user else None),
        "before_state": before,
        "after_state": after,
        "metadata": metadata,
        "created_at": isoformat(now_utc()),
    }
    try:
        await db.audit_logs.insert_one(entry)
    except Exception as exc:  # pragma: no cover — audit must never break a request
        logger.exception("audit_log insert failed: %s", exc)


async def timeline_event(
    parcel_id: str,
    event_type: str,
    description: str,
    actor: Optional[dict] = None,
    metadata: Optional[dict] = None,
    tenant_id: Optional[str] = None,
) -> None:
    await db.evidence_timeline_events.insert_one({
        "id": new_id("tl"),
        "parcel_id": parcel_id,
        "event_type": event_type,
        "description": description,
        "actor_id": actor.get("user_id") if actor else None,
        "actor_name": actor.get("name") if actor else "System",
        "metadata": metadata or {},
        "tenant_id": tenant_id or (actor.get("tenant_id") if actor else None),
        "created_at": isoformat(now_utc()),
    })


async def enqueue_job(job_type: str, payload: dict, idempotency_key: Optional[str] = None) -> dict:
    key = idempotency_key or new_id("job")
    existing = await db.job_queue.find_one({"idempotency_key": key, "status": {"$ne": "FAILED"}})
    if existing:
        return serialize_doc(existing)
    doc = {
        "id": new_id("job"),
        "job_type": job_type,
        "status": "PENDING",
        "payload": payload,
        "result": None,
        "attempts": 0,
        "max_attempts": 3,
        "error_message": None,
        "scheduled_at": isoformat(now_utc()),
        "started_at": None,
        "completed_at": None,
        "idempotency_key": key,
        "created_at": isoformat(now_utc()),
    }
    await db.job_queue.insert_one(doc)
    return serialize_doc(doc)
