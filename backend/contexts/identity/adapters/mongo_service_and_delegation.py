"""MongoDB adapter for ServiceAccount + DelegationGrant."""
from __future__ import annotations

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from contexts.identity.domain.delegation import DelegationGrant
from contexts.identity.domain.service_account import ServiceAccount
from kernel.persistence.repository import GLOBAL, BaseRepository


class MongoServiceAccountRepository(BaseRepository):
    collection_name = "identity_service_accounts"
    scope = GLOBAL

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("account_id", unique=True)
        await self.collection.create_index("secret_hash", unique=True)
        await self.collection.create_index([("tenant_id", 1), ("status", 1)])

    async def add(self, sa: ServiceAccount) -> ServiceAccount:
        await self.collection.insert_one(sa.to_doc())
        return sa

    async def get(self, account_id: str) -> Optional[ServiceAccount]:  # type: ignore[override]
        doc = await self.collection.find_one({"account_id": account_id}, {"_id": 0})
        return ServiceAccount.from_doc(doc) if doc else None

    async def get_by_secret_hash(self, secret_hash: str) -> Optional[ServiceAccount]:
        doc = await self.collection.find_one({"secret_hash": secret_hash}, {"_id": 0})
        return ServiceAccount.from_doc(doc) if doc else None

    async def list_for_tenant(self, tenant_id: Optional[str]) -> list[ServiceAccount]:
        cur = self.collection.find({"tenant_id": tenant_id}, {"_id": 0})
        return [ServiceAccount.from_doc(d) async for d in cur]

    async def update(self, sa: ServiceAccount, expected_version: int) -> ServiceAccount:  # type: ignore[override]
        next_doc = sa.to_doc()
        next_doc["version"] = expected_version + 1
        result = await self.collection.find_one_and_update(
            {"account_id": sa.account_id, "version": expected_version},
            {"$set": next_doc}, return_document=True, projection={"_id": 0},
        )
        return ServiceAccount.from_doc(result) if result else sa


class MongoDelegationRepository(BaseRepository):
    collection_name = "identity_delegations"
    scope = GLOBAL

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("grant_id", unique=True)
        await self.collection.create_index([("delegate_id", 1), ("status", 1)])
        await self.collection.create_index([("delegator_id", 1), ("status", 1)])
        await self.collection.create_index("valid_until")

    async def add(self, grant: DelegationGrant) -> DelegationGrant:
        await self.collection.insert_one(grant.to_doc())
        return grant

    async def get(self, grant_id: str) -> Optional[DelegationGrant]:  # type: ignore[override]
        doc = await self.collection.find_one({"grant_id": grant_id}, {"_id": 0})
        return DelegationGrant.from_doc(doc) if doc else None

    async def list_active_for_delegate(self, delegate_id: str) -> list[DelegationGrant]:
        cur = self.collection.find(
            {"delegate_id": delegate_id, "status": "ACTIVE"}, {"_id": 0},
        )
        return [DelegationGrant.from_doc(d) async for d in cur]

    async def list_issued_by(self, delegator_id: str) -> list[DelegationGrant]:
        cur = self.collection.find({"delegator_id": delegator_id}, {"_id": 0})
        return [DelegationGrant.from_doc(d) async for d in cur]

    async def update(self, grant: DelegationGrant, expected_version: int) -> DelegationGrant:  # type: ignore[override]
        next_doc = grant.to_doc()
        next_doc["version"] = expected_version + 1
        result = await self.collection.find_one_and_update(
            {"grant_id": grant.grant_id, "version": expected_version},
            {"$set": next_doc}, return_document=True, projection={"_id": 0},
        )
        return DelegationGrant.from_doc(result) if result else grant
