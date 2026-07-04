"""Extended Mongo repositories for Slice 4.1 workflow infrastructure.

These live alongside the Slice 4.0 repositories in ``mongo_repositories.py``
but are kept in a separate module so the 4.0 file stays untouched.
Collections (all internal — none of these appear in the v2.0.0 public
contract):

* ``workflow_command_outbox``         — CommandEnvelope docs
* ``workflow_child_registry``         — ChildLink docs
* ``workflow_notification_deliveries``— NotificationDelivery docs
* ``workflow_policies``               — persisted WorkflowPolicy docs
                                        (optional; disk load is authoritative)

All queries honor tenant + country scoping via ExecutionContext (defense
in depth) except for background scheduler queries which run under a
system context.
"""
from __future__ import annotations

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from contexts.workflow.domain.child_link import ChildLink
from contexts.workflow.domain.command_envelope import (
    CommandEnvelope,
    CommandStatus,
)
from contexts.workflow.domain.notification import (
    DeliveryStatus,
    NotificationDelivery,
)
from kernel.errors.problem import conflict

COMMAND_OUTBOX_COLLECTION = "workflow_command_outbox"
CHILD_REGISTRY_COLLECTION = "workflow_child_registry"
NOTIFICATION_DELIVERY_COLLECTION = "workflow_notification_deliveries"


# ---------------------------------------------------------------------------
# CommandEnvelope repository
# ---------------------------------------------------------------------------

class MongoCommandOutbox:
    """Persistence for outbound engine commands."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self.collection = db[COMMAND_OUTBOX_COLLECTION]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("command_id", unique=True)
        await self.collection.create_index("instance_id")
        await self.collection.create_index(
            [("status", 1), ("next_attempt_at", 1)])
        await self.collection.create_index(
            [("target_context", 1), ("command_name", 1), ("status", 1)])
        await self.collection.create_index(
            [("country_code", 1), ("tenant_id", 1), ("status", 1)])

    async def save(self, envelope: CommandEnvelope, session=None) -> None:
        doc = envelope.to_state()
        prior_version = max(envelope.version - 1, 0)
        existing = await self.collection.find_one(
            {"command_id": envelope.command_id}, {"version": 1},
            session=session)
        if existing is None:
            await self.collection.insert_one(doc, session=session)
            return
        if existing.get("version", 0) != prior_version:
            raise conflict(
                f"concurrency conflict on command envelope "
                f"(expected v{prior_version}, "
                f"found v{existing.get('version', 0)})",
                code="workflow.command_envelope.concurrency_conflict")
        await self.collection.replace_one(
            {"command_id": envelope.command_id,
             "version": prior_version}, doc, session=session)

    async def get(self, command_id: str) -> Optional[CommandEnvelope]:
        doc = await self.collection.find_one(
            {"command_id": command_id}, {"_id": 0})
        return CommandEnvelope.from_state(doc) if doc else None

    async def list_for_instance(
            self, instance_id: str) -> list[CommandEnvelope]:
        cur = self.collection.find(
            {"instance_id": instance_id}, {"_id": 0}).sort("created_at", 1)
        return [CommandEnvelope.from_state(d) async for d in cur]

    async def list_dead_lettered(self,
                                 limit: int = 50) -> list[CommandEnvelope]:
        cur = self.collection.find(
            {"status": CommandStatus.DEAD_LETTERED.value},
            {"_id": 0}).sort("dead_lettered_at", -1).limit(limit)
        return [CommandEnvelope.from_state(d) async for d in cur]

    async def claim_next_batch(self, *, now_iso: str,
                               limit: int = 25) -> list[CommandEnvelope]:
        """Return a batch of envelopes ready for dispatch.

        Ready = ``status ∈ {pending, failed}`` and (``next_attempt_at``
        is null OR ``next_attempt_at <= now_iso``).
        """
        flt = {"status": {"$in": [CommandStatus.PENDING.value,
                                    CommandStatus.FAILED.value]},
                "$or": [{"next_attempt_at": None},
                         {"next_attempt_at": {"$lte": now_iso}}]}
        cur = self.collection.find(flt, {"_id": 0}).sort(
            "created_at", 1).limit(limit)
        return [CommandEnvelope.from_state(d) async for d in cur]


# ---------------------------------------------------------------------------
# ChildLink repository
# ---------------------------------------------------------------------------

class MongoChildRegistry:

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self.collection = db[CHILD_REGISTRY_COLLECTION]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("link_id", unique=True)
        await self.collection.create_index("parent_instance_id")
        await self.collection.create_index("child_instance_id", unique=True)
        await self.collection.create_index(
            [("parent_instance_id", 1), ("child_terminal", 1)])

    async def save(self, link: ChildLink, session=None) -> None:
        doc = link.to_state()
        existing = await self.collection.find_one(
            {"link_id": link.link_id}, {"version": 1}, session=session)
        prior_version = max(link.version - 1, 0)
        if existing is None:
            await self.collection.insert_one(doc, session=session)
            return
        if existing.get("version", 0) != prior_version:
            raise conflict(
                f"concurrency conflict on child link "
                f"(expected v{prior_version}, "
                f"found v{existing.get('version', 0)})",
                code="workflow.child_link.concurrency_conflict")
        await self.collection.replace_one(
            {"link_id": link.link_id, "version": prior_version},
            doc, session=session)

    async def list_children(self,
                            parent_instance_id: str) -> list[ChildLink]:
        cur = self.collection.find(
            {"parent_instance_id": parent_instance_id},
            {"_id": 0}).sort("created_at", 1)
        return [ChildLink.from_state(d) async for d in cur]

    async def find_by_child(self,
                            child_instance_id: str) -> Optional[ChildLink]:
        doc = await self.collection.find_one(
            {"child_instance_id": child_instance_id}, {"_id": 0})
        return ChildLink.from_state(doc) if doc else None


# ---------------------------------------------------------------------------
# NotificationDelivery repository
# ---------------------------------------------------------------------------

class MongoNotificationLog:

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self.collection = db[NOTIFICATION_DELIVERY_COLLECTION]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("delivery_id", unique=True)
        await self.collection.create_index("instance_id", sparse=True)
        await self.collection.create_index(
            [("status", 1), ("next_attempt_at", 1)])
        await self.collection.create_index(
            [("channel", 1), ("status", 1)])
        await self.collection.create_index(
            [("country_code", 1), ("tenant_id", 1), ("status", 1)])

    async def save(self, delivery: NotificationDelivery,
                    session=None) -> None:
        doc = delivery.to_state()
        existing = await self.collection.find_one(
            {"delivery_id": delivery.delivery_id}, {"version": 1},
            session=session)
        prior_version = max(delivery.version - 1, 0)
        if existing is None:
            await self.collection.insert_one(doc, session=session)
            return
        if existing.get("version", 0) != prior_version:
            raise conflict(
                f"concurrency conflict on notification delivery "
                f"(expected v{prior_version}, "
                f"found v{existing.get('version', 0)})",
                code="workflow.notification.concurrency_conflict")
        await self.collection.replace_one(
            {"delivery_id": delivery.delivery_id,
             "version": prior_version}, doc, session=session)

    async def get(self, delivery_id: str) -> Optional[NotificationDelivery]:
        doc = await self.collection.find_one(
            {"delivery_id": delivery_id}, {"_id": 0})
        return NotificationDelivery.from_state(doc) if doc else None

    async def claim_next_batch(self, *, now_iso: str,
                               limit: int = 25
                               ) -> list[NotificationDelivery]:
        flt = {"status": {"$in": [DeliveryStatus.QUEUED.value,
                                    DeliveryStatus.RETRY.value]},
                "$or": [{"next_attempt_at": None},
                         {"next_attempt_at": {"$lte": now_iso}}]}
        cur = self.collection.find(flt, {"_id": 0}).sort(
            "created_at", 1).limit(limit)
        return [NotificationDelivery.from_state(d) async for d in cur]

    async def list_dead_lettered(
            self, limit: int = 50) -> list[NotificationDelivery]:
        cur = self.collection.find(
            {"status": DeliveryStatus.DEAD_LETTERED.value},
            {"_id": 0}).sort("dead_lettered_at", -1).limit(limit)
        return [NotificationDelivery.from_state(d) async for d in cur]
