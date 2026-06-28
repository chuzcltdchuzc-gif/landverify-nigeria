"""MongoDB adapter for the Session aggregate (Identity context)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from contexts.identity.domain.session import STATUS_ACTIVE, STATUS_REVOKED, Session
from kernel.persistence.repository import GLOBAL, BaseRepository


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MongoSessionRepository(BaseRepository):
    collection_name = "identity_sessions"
    scope = GLOBAL

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        super().__init__(db)

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("session_id", unique=True)
        await self.collection.create_index("refresh_token_hash", unique=True)
        await self.collection.create_index([("user_id", 1), ("status", 1)])

    async def add(self, session: Session) -> Session:
        await self.collection.insert_one(session.to_doc())
        return session

    async def get(self, session_id: str) -> Optional[Session]:
        doc = await self.collection.find_one({"session_id": session_id}, {"_id": 0})
        return Session.from_doc(doc) if doc else None

    async def get_by_refresh_hash(self, refresh_hash: str) -> Optional[Session]:
        doc = await self.collection.find_one({"refresh_token_hash": refresh_hash}, {"_id": 0})
        return Session.from_doc(doc) if doc else None

    async def revoke(self, session_id: str, reason: str) -> None:
        await self.collection.update_one(
            {"session_id": session_id},
            {"$set": {"status": STATUS_REVOKED, "revoked_at": _now_iso(),
                      "revoked_reason": reason}},
        )

    async def revoke_user_sessions(self, user_id: str, reason: str) -> int:
        result = await self.collection.update_many(
            {"user_id": user_id, "status": STATUS_ACTIVE},
            {"$set": {"status": STATUS_REVOKED, "revoked_at": _now_iso(),
                      "revoked_reason": reason}},
        )
        return result.modified_count or 0
