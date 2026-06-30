"""Task aggregate (Phase 4 — Slice 4.0).

A Task is a unit of human work surfaced by the workflow engine. The
engine creates a Task when a definition's ``on_enter`` declares a
``create_task`` action; the application services let assignees claim
and complete it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from contexts.workflow.domain.events import DomainEvent
from contexts.workflow.domain.invariants import (
    TaskStateError,
    TerminalInstanceError,
)
from contexts.workflow.domain.value_objects import (
    TERMINAL_TASK_STATES,
    TaskState,
    new_task_id,
    now_iso,
)

SCHEMA_VERSION_CURRENT = 1


def _task_event(event_type: str, task_id: str, version: int,
                payload: dict) -> DomainEvent:
    return DomainEvent(event_type=event_type, aggregate_id=task_id,
                       aggregate_version=version, payload=payload,
                       aggregate_type="WorkflowTask")


@dataclass
class Task:
    """A unit of human work that the engine surfaces for an actor or role."""

    task_id: str
    instance_id: str
    definition_name: str
    tenant_id: str
    country_code: str
    title: str
    assigned_to_role: Optional[str]
    assigned_to_principal: Optional[str]
    created_at: str
    state: str = TaskState.OPEN.value
    claimed_by: Optional[str] = None
    claimed_at: Optional[str] = None
    completed_by: Optional[str] = None
    completed_at: Optional[str] = None
    completion_payload: dict = field(default_factory=dict)
    due_at: Optional[str] = None
    cancelled_reason: Optional[str] = None
    version: int = 1
    schema_version: int = SCHEMA_VERSION_CURRENT

    _events: list[DomainEvent] = field(default_factory=list,
                                        repr=False, compare=False)

    @classmethod
    def create(cls, *, instance_id: str, definition_name: str,
               tenant_id: str, country_code: str, title: str,
               assigned_to_role: Optional[str] = None,
               assigned_to_principal: Optional[str] = None,
               due_at: Optional[str] = None,
               task_id: Optional[str] = None) -> "Task":
        tid = task_id or new_task_id()
        created_at = now_iso()
        agg = cls(task_id=tid, instance_id=instance_id,
                   definition_name=definition_name,
                   tenant_id=tenant_id, country_code=country_code,
                   title=title,
                   assigned_to_role=assigned_to_role,
                   assigned_to_principal=assigned_to_principal,
                   created_at=created_at, due_at=due_at)
        agg._raise(_task_event("workflow.task.created", tid, 1, {
            "task_id": tid, "instance_id": instance_id,
            "definition_name": definition_name,
            "title": title,
            "assigned_to_role": assigned_to_role,
            "assigned_to_principal": assigned_to_principal,
            "due_at": due_at,
        }))
        return agg

    @classmethod
    def from_state(cls, state: dict) -> "Task":
        clean = {k: v for k, v in state.items()
                 if k in cls.__dataclass_fields__ and not k.startswith("_")}
        agg = cls(**clean)
        agg._events.clear()
        return agg

    def _raise(self, ev: DomainEvent) -> None:
        self._events.append(ev)

    def pull_events(self) -> list[DomainEvent]:
        out = list(self._events)
        self._events.clear()
        return out

    def claim(self, *, principal_id: str) -> None:
        if self.state != TaskState.OPEN.value:
            raise TaskStateError(
                f"task {self.task_id} not OPEN (state={self.state}); cannot claim")
        self.state = TaskState.CLAIMED.value
        self.claimed_by = principal_id
        self.claimed_at = now_iso()
        self.version += 1
        self._raise(_task_event("workflow.task.claimed", self.task_id,
                                  self.version, {
            "task_id": self.task_id, "instance_id": self.instance_id,
            "claimed_by": principal_id,
        }))

    def complete(self, *, principal_id: str,
                  payload: Optional[dict] = None) -> None:
        if self.state not in {TaskState.OPEN.value, TaskState.CLAIMED.value}:
            raise TaskStateError(
                f"task {self.task_id} not completable (state={self.state})")
        if self.state == TaskState.CLAIMED.value \
                and self.claimed_by and self.claimed_by != principal_id:
            raise TaskStateError(
                f"task {self.task_id} claimed by {self.claimed_by}; "
                f"cannot be completed by {principal_id}")
        self.state = TaskState.COMPLETED.value
        self.completed_by = principal_id
        self.completed_at = now_iso()
        self.completion_payload = dict(payload or {})
        self.version += 1
        self._raise(_task_event("workflow.task.completed", self.task_id,
                                  self.version, {
            "task_id": self.task_id, "instance_id": self.instance_id,
            "completed_by": principal_id,
            "payload": dict(payload or {}),
        }))

    def cancel(self, *, actor: str, reason: str) -> None:
        if self.state in TERMINAL_TASK_STATES:
            raise TerminalInstanceError(
                f"task {self.task_id} already terminal (state={self.state})")
        self.state = TaskState.CANCELLED.value
        self.cancelled_reason = reason
        self.version += 1
        self._raise(_task_event("workflow.task.cancelled", self.task_id,
                                  self.version, {
            "task_id": self.task_id, "instance_id": self.instance_id,
            "actor": actor, "reason": reason,
        }))

    def mark_expired(self) -> None:
        if self.state in TERMINAL_TASK_STATES:
            raise TerminalInstanceError(
                f"task {self.task_id} already terminal (state={self.state})")
        self.state = TaskState.EXPIRED.value
        self.version += 1
        self._raise(_task_event("workflow.task.expired", self.task_id,
                                  self.version, {
            "task_id": self.task_id, "instance_id": self.instance_id,
        }))

    def to_state(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__
                if not k.startswith("_")}
