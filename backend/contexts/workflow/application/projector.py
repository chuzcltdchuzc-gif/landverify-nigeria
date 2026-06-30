"""Workflow instance projector (Phase 4 — Slice 4.0).

A minimal read-model projection that turns ``workflow.instance.*``
events into a denormalised view of every instance, suitable for
admin queues, dashboards, and replay verification.

Constitutional rules (ADR-0010):
* Pure event-to-row mapping. NO business logic.
* NEVER mutates aggregates. NEVER publishes commands.
* Idempotent: deleting the projection rows and replaying from event 0
  MUST produce byte-identical state.
"""
from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

from kernel.events.envelope import Envelope

PROJECTION_NAME = "workflow.instance"
PROJECTION_VERSION = 1
EVENT_GLOB = "workflow.instance.*"
COLLECTION = "workflow_instance_read_model"


class WorkflowInstanceProjector:
    """Maintains the ``workflow_instance_read_model`` collection.

    One document per ``instance_id`` containing the latest snapshot of
    business state, lifecycle, and last-transition metadata. The row's
    ``version`` tracks the highest envelope ``aggregate_version`` seen.
    """

    name = PROJECTION_NAME
    version = PROJECTION_VERSION
    event_glob = EVENT_GLOB

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self.collection = db[COLLECTION]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("instance_id", unique=True)
        await self.collection.create_index(
            [("definition_name", 1), ("business_state", 1)])
        await self.collection.create_index(
            [("country_code", 1), ("tenant_id", 1), ("lifecycle", 1)])

    async def on_event(self, env: Envelope) -> None:
        p = env.payload or {}
        instance_id = p.get("instance_id")
        if not instance_id:
            return
        # Adapter-level dedup: only advance the row when the incoming
        # envelope is at or above the row's current version. This makes
        # replay byte-identical because every replayed event re-applies
        # to the same row deterministically (idempotent).
        existing = await self.collection.find_one(
            {"instance_id": instance_id}, {"version": 1})
        cur_v = (existing or {}).get("version", 0)
        if env.aggregate_version < cur_v:
            return
        update: dict = {"$set": {
            "instance_id": instance_id,
            "version": env.aggregate_version,
            "last_event_type": env.event_type,
            "last_event_at": env.occurred_at,
            "tenant_id": env.tenant_id,
            "country_code": env.country,
        }}
        if env.event_type == "workflow.instance.started":
            update["$set"].update({
                "definition_name": p.get("definition_name"),
                "definition_version": p.get("definition_version"),
                "initial_state": p.get("initial_state"),
                "business_state": p.get("initial_state"),
                "lifecycle": "running",
                "initiator_id": p.get("initiator_id"),
                "created_at": env.occurred_at,
            })
        elif env.event_type == "workflow.instance.transitioned":
            update["$set"].update({
                "business_state": p.get("to_state"),
                "last_command": p.get("command"),
                "last_actor": p.get("actor"),
            })
        elif env.event_type == "workflow.instance.completed":
            update["$set"].update({
                "lifecycle": "completed",
                "business_state": p.get("final_state") or
                                  (existing or {}).get("business_state"),
                "terminated_at": env.occurred_at,
            })
        elif env.event_type == "workflow.instance.cancelled":
            update["$set"].update({
                "lifecycle": "cancelled",
                "terminated_at": env.occurred_at,
            })
        elif env.event_type == "workflow.instance.suspended":
            update["$set"].update({"lifecycle": "suspended"})
        elif env.event_type == "workflow.instance.reactivated":
            update["$set"].update({"lifecycle": "running"})
        await self.collection.update_one(
            {"instance_id": instance_id}, update, upsert=True)

    async def reset(self) -> None:
        await self.collection.delete_many({})
