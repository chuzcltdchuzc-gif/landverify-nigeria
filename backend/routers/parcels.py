"""Parcel CRUD + tenant-scoped queries.

WRITES are delegated to the canonical Registry bounded context
(`contexts/registry/`) per Phase 2A directive §2. The legacy `parcels`
collection is now a read-only mirror that's kept in sync after every
successful Registry write. The Registry is the authoritative writer;
this router exists as a transitional compatibility layer until the
legacy frontend is migrated to `/api/v1/registry/*`.

Reads continue to use `tdb` which structurally enforces tenant isolation.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from contexts.registry.legacy_adapter import legacy_create_parcel_via_registry
from core.audit import audit_log, enqueue_job, timeline_event
from core.helpers import isoformat, now_utc
from core.safe_db import tdb
from core.security import get_current_user
from schemas.models import ParcelCreate

router = APIRouter(prefix="/parcels")


@router.get("")
async def list_parcels(user: dict = Depends(get_current_user)) -> dict:
    # tdb auto-injects tenant_id — leaks across tenants are structurally impossible.
    cur = tdb.parcels.find({}, {"_id": 0}).sort("created_at", -1)
    items = [p async for p in cur]
    return {"items": items}


@router.post("", deprecated=True)
async def create_parcel(body: ParcelCreate, req: Request,
                        user: dict = Depends(get_current_user)) -> dict:
    """Deprecated — delegates to /api/v1/registry/landvaults.

    The legacy `parcels` collection is mirrored from the canonical
    Registry record so existing readers (legacy admin views, evidence
    routes, etc.) keep working during the migration window.
    """
    # 1) Authoritative write through the Registry (raises domain events
    #    via the transactional outbox, allocates canonical parcel_number).
    landvault = await legacy_create_parcel_via_registry(user=user, body=body)

    # 2) Legacy mirror — denormalized, NOT authoritative. Keyed by
    #    `registry_id` so a future cleanup can drop these rows safely.
    pid = landvault["registry_id"]
    mirror = {
        "id": pid,
        "registry_id": pid,
        "parcel_number": landvault["parcel_number"],
        "community": getattr(body, "community", None),
        "ward": getattr(body, "ward", None),
        "lga": getattr(body, "lga", None),
        "state": getattr(body, "state", None),
        "coordinates": getattr(body, "coordinates", None),
        "status": "UNVERIFIED",
        "confidence_score": 0,
        "evidence_count": 0,
        "attestation_count": 0,
        "certificate_status": "NONE",
        "owner_id": user["user_id"],
        "tenant_id": user["tenant_id"],
        "description": getattr(body, "description", None),
        "created_at": isoformat(now_utc()),
        "updated_at": isoformat(now_utc()),
        "x_legacy_mirror_of_registry_id": pid,
    }
    await tdb.parcels.insert_one(dict(mirror))
    await timeline_event(pid, "PARCEL_CREATED",
                         f"Parcel {mirror['parcel_number']} recorded "
                         f"by {user['name']} (via Registry).",
                         actor=user, tenant_id=user["tenant_id"])
    await enqueue_job("DUPLICATE_DETECTION", {"parcel_id": pid},
                      idempotency_key=f"dup-{pid}")
    await enqueue_job("CONFIDENCE_RECALCULATION", {"parcel_id": pid},
                      idempotency_key=f"conf-{pid}")
    await audit_log("PARCEL_CREATED", "parcel", pid, user=user, after=mirror)
    return {"parcel": mirror, "registry_id": pid}


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
