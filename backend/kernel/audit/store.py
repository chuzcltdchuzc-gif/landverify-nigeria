"""Append-only audit store with hash-chain integrity (ADR-005).

Public API exposes only `record()` — there is intentionally no update or
delete method. Each entry carries:
    * principal (or "anonymous")
    * action (e.g. "auth.login.success")
    * resource (type + id)
    * tenant / country / organization scope
    * decision (permit/deny when produced by the PDP)
    * correlation_id
    * occurred_at (server UTC)
    * payload (small, redacted)
    * prev_hash + entry_hash for chain integrity

Hash chain: sha256(prev_hash || canonical_json(entry_without_hash)).
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from kernel.persistence.context import current_context

logger = logging.getLogger("kernel.audit")

COLLECTION = "kernel_audit_log"
GENESIS_HASH = "0" * 64


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


@dataclass
class AuditEntry:
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    decision: Optional[str] = None        # PERMIT | DENY | None (informational)
    payload: dict = field(default_factory=dict)
    occurred_at: str = field(default_factory=_now_iso)


class AuditStore:
    """Append-only audit store. Wrap a motor database; never bypass `record()`."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self.collection = db[COLLECTION]

    async def _previous_hash(self) -> str:
        latest = await self.collection.find_one(
            {}, {"entry_hash": 1, "_id": 0}, sort=[("seq", -1)],
        )
        return latest["entry_hash"] if latest and latest.get("entry_hash") else GENESIS_HASH

    async def _next_seq(self) -> int:
        # Atomic monotonic counter via update_one upsert.
        result = await self._db["kernel_audit_counters"].find_one_and_update(
            {"_id": "audit_seq"},
            {"$inc": {"value": 1}},
            upsert=True, return_document=True,
        )
        return int(result["value"])

    async def record(self, entry: AuditEntry) -> dict:
        """Append a new audit entry and return the stored document.

        Read-of-tip + insert run inside a transaction so concurrent writers
        cannot produce two entries with the same `prev_hash` (which would
        break the chain). On replica-set deployments the TX auto-retries on
        WriteConflict via `core.tx.run_in_transaction`.
        """
        from core.tx import run_in_transaction
        ctx = current_context()

        async def _do(session) -> dict:
            latest = await self.collection.find_one(
                {}, {"entry_hash": 1, "_id": 0}, sort=[("seq", -1)], session=session,
            )
            prev_hash = latest["entry_hash"] if latest and latest.get("entry_hash") else GENESIS_HASH
            seq_doc = await self._db["kernel_audit_counters"].find_one_and_update(
                {"_id": "audit_seq"},
                {"$inc": {"value": 1}},
                upsert=True, return_document=True, session=session,
            )
            seq = int(seq_doc["value"])
            doc = {
                "id": uuid.uuid4().hex,
                "seq": seq,
                "occurred_at": entry.occurred_at,
                "principal_id": ctx.principal_id,
                "email": ctx.email,
                "tenant_id": ctx.tenant_id,
                "country": ctx.country,
                "organization_id": ctx.organization_id,
                "correlation_id": ctx.correlation_id,
                "request_ip": ctx.request_ip,
                "user_agent": ctx.user_agent,
                "action": entry.action,
                "resource_type": entry.resource_type,
                "resource_id": entry.resource_id,
                "decision": entry.decision,
                "payload": entry.payload,
                "prev_hash": prev_hash,
            }
            doc["entry_hash"] = hashlib.sha256(
                (prev_hash + _canonical_json({k: v for k, v in doc.items()
                                              if k != "entry_hash"})).encode()
            ).hexdigest()
            await self.collection.insert_one(dict(doc), session=session)
            return doc

        return await run_in_transaction(_do)

    # NOTE: intentionally no update / delete / replace methods.


# Convenience helper -------------------------------------------------------
_store: AuditStore | None = None


def configure_audit_store(db: AsyncIOMotorDatabase) -> AuditStore:
    global _store
    _store = AuditStore(db)
    return _store


async def audit(action: str, *, resource_type: str = "platform",
                resource_id: Optional[str] = None, decision: Optional[str] = None,
                payload: Optional[dict[str, Any]] = None) -> None:
    if _store is None:
        logger.warning("audit store not configured; dropping action=%s", action)
        return
    await _store.record(AuditEntry(
        action=action, resource_type=resource_type, resource_id=resource_id,
        decision=decision, payload=payload or {},
    ))
