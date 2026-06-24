"""MongoDB client + index management."""
from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient

from core.config import DB_NAME, MONGO_URL

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]


async def ensure_indexes() -> None:
    await db.users.create_index("user_id", unique=True)
    await db.users.create_index("email", unique=True)
    await db.user_sessions.create_index("session_token", unique=True)
    await db.user_sessions.create_index("expires_at")
    await db.parcels.create_index("parcel_number", unique=True)
    await db.parcels.create_index("tenant_id")
    await db.evidence_vault.create_index([("parcel_id", 1)])
    await db.community_attestations.create_index([("parcel_id", 1)])
    await db.credit_wallets.create_index("user_id", unique=True)
    await db.audit_logs.create_index("created_at")
    await db.job_queue.create_index("status")
    await db.job_queue.create_index("idempotency_key")
    await db.portfolios.create_index("owner_id")
    await db.reports.create_index("requested_by")
    await db.certificates.create_index("parcel_id")
    await db.dispute_records.create_index("parcel_id")
