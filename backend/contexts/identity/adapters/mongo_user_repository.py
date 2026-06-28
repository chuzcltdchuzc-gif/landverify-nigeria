"""MongoDB adapter for the User aggregate (Identity context).

Exposes the Repository Specification pattern (Section 2.4): the only place
that translates Specifications into Mongo filters.
"""
from __future__ import annotations

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from contexts.identity.domain.user import User
from kernel.errors.problem import conflict
from kernel.persistence.repository import GLOBAL, BaseRepository
from kernel.persistence.specification import Specification


class MongoUserRepository(BaseRepository):
    collection_name = "identity_users"
    scope = GLOBAL          # Identity owns its own scoping rules

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        super().__init__(db)

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("user_id", unique=True)
        await self.collection.create_index("email", unique=True)
        await self.collection.create_index([("country", 1), ("tenant_id", 1)])
        await self.collection.create_index("identities.subject")
        await self.collection.create_index("role")
        await self.collection.create_index("account_status")

    async def get(self, user_id: str, *, id_field: str = "user_id") -> Optional[User]:  # type: ignore[override]
        doc = await self.collection.find_one({"user_id": user_id}, {"_id": 0})
        return User.from_doc(doc) if doc else None

    async def get_by_email(self, email: str) -> Optional[User]:
        doc = await self.collection.find_one({"email": email.lower().strip()}, {"_id": 0})
        return User.from_doc(doc) if doc else None

    async def get_by_provider_subject(self, provider: str, subject: str) -> Optional[User]:
        doc = await self.collection.find_one(
            {"identities": {"$elemMatch": {"provider": provider, "subject": subject}}},
            {"_id": 0},
        )
        return User.from_doc(doc) if doc else None

    async def find(self, specification: Specification, *,             # type: ignore[override]
                   limit: int = 100, skip: int = 0,
                   sort: Optional[list[tuple]] = None) -> list[User]:
        flt = specification.to_mongo_filter() if specification else {}
        cur = self.collection.find(flt, {"_id": 0})
        if sort:
            cur = cur.sort(sort)
        cur = cur.skip(skip).limit(limit)
        return [User.from_doc(doc) async for doc in cur]

    async def count(self, specification: Optional[Specification] = None) -> int:  # type: ignore[override]
        flt = specification.to_mongo_filter() if specification else {}
        return await self.collection.count_documents(flt)

    async def add(self, user: User) -> User:  # type: ignore[override]
        try:
            await self.collection.insert_one(user.to_doc())
        except Exception as exc:  # noqa: BLE001
            if "duplicate key" in str(exc).lower():
                raise conflict("Email already registered", code="identity.email_taken") from exc
            raise
        return user

    async def update(self, user: User, expected_version: int) -> User:  # type: ignore[override]
        next_doc = user.to_doc()
        next_doc["version"] = expected_version + 1
        result = await self.collection.find_one_and_update(
            {"user_id": user.user_id, "version": expected_version},
            {"$set": next_doc},
            return_document=True,
            projection={"_id": 0},
        )
        if not result:
            raise conflict("User update lost a write race or user missing",
                           code="identity.update_conflict")
        return User.from_doc(result)
