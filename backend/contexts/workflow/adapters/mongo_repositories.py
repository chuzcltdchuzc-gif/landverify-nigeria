"""Mongo adapter for the Workflow context (Phase 4 — Slice 4.0).

Persistence ONLY — these classes never raise domain events. Tenant +
country scoping is enforced inside ``_scope_filter()`` via the
ExecutionContext; client-supplied tenant_id / country_code values are
ignored as a defense-in-depth measure.
"""
from __future__ import annotations

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from contexts.workflow.domain.compensation import CompensationEntry
from contexts.workflow.domain.invariants import ConcurrencyConflict
from contexts.workflow.domain.task import Task
from contexts.workflow.domain.timer import Timer
from contexts.workflow.domain.workflow_instance import WorkflowInstance
from contexts.workflow.ports.repository import (
    InstanceSpec,
    TaskSpec,
    TimerSpec,
)
from kernel.errors.problem import conflict
from kernel.persistence.context import current_context

INSTANCES_COLLECTION = "workflow_instances"
TASKS_COLLECTION = "workflow_tasks"
TIMERS_COLLECTION = "workflow_timers"
COMPENSATION_COLLECTION = "workflow_compensation_log"
EVENT_LOG_COLLECTION = "workflow_event_log"


def _scope() -> dict:
    """Tenant + country filter derived from ExecutionContext."""
    ctx = current_context()
    flt: dict = {}
    if ctx.is_anonymous:
        return {"tenant_id": "__NO_TENANT_CONTEXT__"}
    if not ctx.has_role("super_admin"):
        if ctx.tenant_id:
            flt["tenant_id"] = ctx.tenant_id
        if ctx.country:
            flt["country_code"] = ctx.country
    return flt


# ---------------------------------------------------------------------------
# WorkflowInstanceRepository
# ---------------------------------------------------------------------------

class MongoWorkflowInstanceRepository:

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self.collection = db[INSTANCES_COLLECTION]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("instance_id", unique=True)
        await self.collection.create_index(
            [("definition_name", 1), ("business_state", 1)])
        await self.collection.create_index(
            [("country_code", 1), ("tenant_id", 1), ("lifecycle", 1)])
        await self.collection.create_index("correlation_id", sparse=True)

    async def save(self, instance: WorkflowInstance, session=None) -> None:
        doc = instance.to_state()
        # Optimistic concurrency: matching version must equal
        # `instance.version - 1` for updates; inserts use upsert when
        # no prior version exists.
        prior_version = max(instance.version - 1, 0)
        # Use upsert + version match for atomicity.
        flt = {"instance_id": instance.instance_id}
        # On creation prior_version may be 0; we require the doc be absent.
        existing = await self.collection.find_one(
            flt, {"version": 1}, session=session)
        if existing is None:
            await self.collection.insert_one(doc, session=session)
            return
        if existing.get("version", 0) != prior_version:
            raise conflict(
                f"concurrency conflict on workflow instance "
                f"(expected v{prior_version}, found v{existing.get('version', 0)})",
                code="workflow.instance.concurrency_conflict")
        result = await self.collection.replace_one(
            {"instance_id": instance.instance_id, "version": prior_version},
            doc, session=session)
        if result.matched_count == 0:
            raise conflict(
                "concurrency conflict on workflow instance (race)",
                code="workflow.instance.concurrency_conflict")

    async def get(self, instance_id: str) -> Optional[WorkflowInstance]:
        doc = await self.collection.find_one(
            {"instance_id": instance_id, **_scope()}, {"_id": 0})
        if not doc:
            return None
        return WorkflowInstance.from_state(doc)

    async def list(self, spec: InstanceSpec) -> list[WorkflowInstance]:
        flt = _scope()
        if spec.definition_name:
            flt["definition_name"] = spec.definition_name
        if spec.business_state:
            flt["business_state"] = spec.business_state
        if spec.lifecycle:
            flt["lifecycle"] = spec.lifecycle
        if spec.correlation_id:
            flt["correlation_id"] = spec.correlation_id
        cur = self.collection.find(flt, {"_id": 0}).sort(
            "created_at", -1).limit(spec.limit)
        return [WorkflowInstance.from_state(doc) async for doc in cur]


# ---------------------------------------------------------------------------
# TaskRepository
# ---------------------------------------------------------------------------

class MongoTaskRepository:

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self.collection = db[TASKS_COLLECTION]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("task_id", unique=True)
        await self.collection.create_index("instance_id")
        await self.collection.create_index(
            [("assigned_to_role", 1), ("state", 1)])
        await self.collection.create_index(
            [("country_code", 1), ("tenant_id", 1), ("state", 1)])
        await self.collection.create_index("due_at", sparse=True)

    async def save(self, task: Task, session=None) -> None:
        doc = task.to_state()
        prior_version = max(task.version - 1, 0)
        flt = {"task_id": task.task_id}
        existing = await self.collection.find_one(flt, {"version": 1},
                                                    session=session)
        if existing is None:
            await self.collection.insert_one(doc, session=session)
            return
        if existing.get("version", 0) != prior_version:
            raise conflict(
                f"concurrency conflict on workflow task "
                f"(expected v{prior_version}, found v{existing.get('version', 0)})",
                code="workflow.task.concurrency_conflict")
        await self.collection.replace_one(
            {"task_id": task.task_id, "version": prior_version},
            doc, session=session)

    async def get(self, task_id: str) -> Optional[Task]:
        doc = await self.collection.find_one(
            {"task_id": task_id, **_scope()}, {"_id": 0})
        return Task.from_state(doc) if doc else None

    async def list(self, spec: TaskSpec) -> list[Task]:
        flt = _scope()
        if spec.instance_id:
            flt["instance_id"] = spec.instance_id
        if spec.state:
            flt["state"] = spec.state
        if spec.assigned_to_role:
            flt["assigned_to_role"] = spec.assigned_to_role
        if spec.assigned_to_principal:
            flt["assigned_to_principal"] = spec.assigned_to_principal
        cur = self.collection.find(flt, {"_id": 0}).sort(
            "created_at", -1).limit(spec.limit)
        return [Task.from_state(doc) async for doc in cur]


# ---------------------------------------------------------------------------
# TimerRepository
# ---------------------------------------------------------------------------

class MongoTimerRepository:

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self.collection = db[TIMERS_COLLECTION]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("timer_id", unique=True)
        await self.collection.create_index([("fire_at", 1), ("state", 1)])
        await self.collection.create_index("instance_id")
        await self.collection.create_index(
            [("country_code", 1), ("tenant_id", 1), ("state", 1)])

    async def save(self, timer: Timer, session=None) -> None:
        doc = timer.to_state()
        prior_version = max(timer.version - 1, 0)
        flt = {"timer_id": timer.timer_id}
        existing = await self.collection.find_one(flt, {"version": 1},
                                                    session=session)
        if existing is None:
            await self.collection.insert_one(doc, session=session)
            return
        if existing.get("version", 0) != prior_version:
            raise conflict(
                f"concurrency conflict on workflow timer "
                f"(expected v{prior_version}, found v{existing.get('version', 0)})",
                code="workflow.timer.concurrency_conflict")
        await self.collection.replace_one(
            {"timer_id": timer.timer_id, "version": prior_version},
            doc, session=session)

    async def get(self, timer_id: str) -> Optional[Timer]:
        doc = await self.collection.find_one(
            {"timer_id": timer_id, **_scope()}, {"_id": 0})
        return Timer.from_state(doc) if doc else None

    async def list(self, spec: TimerSpec) -> list[Timer]:
        flt = _scope()
        if spec.instance_id:
            flt["instance_id"] = spec.instance_id
        if spec.state:
            flt["state"] = spec.state
        if spec.due_before:
            flt["fire_at"] = {"$lte": spec.due_before}
        cur = self.collection.find(flt, {"_id": 0}).sort(
            "fire_at", 1).limit(spec.limit)
        return [Timer.from_state(doc) async for doc in cur]


# ---------------------------------------------------------------------------
# CompensationRepository (append-only)
# ---------------------------------------------------------------------------

class MongoCompensationRepository:

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self.collection = db[COMPENSATION_COLLECTION]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("compensation_id", unique=True)
        await self.collection.create_index("instance_id")
        await self.collection.create_index([("instance_id", 1),
                                              ("recorded_at", 1)])

    async def append(self, entry: CompensationEntry, session=None) -> None:
        doc = entry.to_state()
        await self.collection.insert_one(doc, session=session)

    async def list_for_instance(self,
                                  instance_id: str) -> list[CompensationEntry]:
        cur = self.collection.find(
            {"instance_id": instance_id, **_scope()},
            {"_id": 0}).sort("recorded_at", 1)
        return [CompensationEntry(**{k: v for k, v in d.items()
                                       if k in CompensationEntry.__dataclass_fields__
                                       and not k.startswith("_")})
                async for d in cur]
