"""Repository Protocols for the Workflow context (Phase 4 — Slice 4.0).

Adapters live in ``contexts.workflow.adapters.*``. The domain depends
only on these Protocols, not on Mongo.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from contexts.workflow.domain.compensation import CompensationEntry
from contexts.workflow.domain.task import Task
from contexts.workflow.domain.timer import Timer
from contexts.workflow.domain.workflow_definition import WorkflowDefinition
from contexts.workflow.domain.workflow_instance import WorkflowInstance


@dataclass(frozen=True)
class InstanceSpec:
    """Filter spec for instance queries. Honored alongside the
    ExecutionContext tenant/country scoping in adapters."""
    definition_name: Optional[str] = None
    business_state: Optional[str] = None
    lifecycle: Optional[str] = None
    correlation_id: Optional[str] = None
    limit: int = 50


@dataclass(frozen=True)
class TaskSpec:
    instance_id: Optional[str] = None
    assigned_to_role: Optional[str] = None
    assigned_to_principal: Optional[str] = None
    state: Optional[str] = None
    limit: int = 50


@dataclass(frozen=True)
class TimerSpec:
    instance_id: Optional[str] = None
    state: Optional[str] = None
    due_before: Optional[str] = None
    limit: int = 50


class WorkflowInstanceRepository(Protocol):
    async def ensure_indexes(self) -> None: ...

    async def save(self, instance: WorkflowInstance, session=None) -> None: ...

    async def get(self, instance_id: str) -> Optional[WorkflowInstance]: ...

    async def list(self, spec: InstanceSpec) -> list[WorkflowInstance]: ...


class TaskRepository(Protocol):
    async def ensure_indexes(self) -> None: ...

    async def save(self, task: Task, session=None) -> None: ...

    async def get(self, task_id: str) -> Optional[Task]: ...

    async def list(self, spec: TaskSpec) -> list[Task]: ...


class TimerRepository(Protocol):
    async def ensure_indexes(self) -> None: ...

    async def save(self, timer: Timer, session=None) -> None: ...

    async def get(self, timer_id: str) -> Optional[Timer]: ...

    async def list(self, spec: TimerSpec) -> list[Timer]: ...


class CompensationRepository(Protocol):
    async def ensure_indexes(self) -> None: ...

    async def append(self, entry: CompensationEntry, session=None) -> None: ...

    async def list_for_instance(self, instance_id: str) -> list[CompensationEntry]: ...


class DefinitionLoader(Protocol):
    """Loads frozen JSON workflow definitions at boot. Production
    adapter reads ``contracts/v1/workflow_definitions/*.v1.json``; tests
    can inject an in-memory loader."""

    def list_definitions(self) -> list[WorkflowDefinition]: ...

    def get(self, name: str,
            version: Optional[int] = None) -> Optional[WorkflowDefinition]: ...
