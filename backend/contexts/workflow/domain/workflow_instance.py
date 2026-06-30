"""WorkflowInstance aggregate (Phase 4 — Slice 4.0).

Event-sourced aggregate root. The pure ``apply(state, event)`` function
makes replay byte-identical regardless of when it runs.

Constitutional rules (ADR-0019):
* The instance NEVER directly writes to other bounded contexts. When
  the definition says ``emit_command``, the engine records that
  intent as an outbox envelope; downstream contexts consume it.
* All identity, scope, and lifecycle fields are immutable post-create.
* ``version`` is monotonic; optimistic concurrency uses it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from contexts.workflow.domain.events import DomainEvent
from contexts.workflow.domain.invariants import (
    IllegalTransitionError,
    ImmutableFieldError,
    SuspendedInstanceError,
    TerminalInstanceError,
    UnknownCommandError,
)
from contexts.workflow.domain.value_objects import (
    InstanceState,
    TERMINAL_INSTANCE_STATES,
    new_instance_id,
    now_iso,
)
from contexts.workflow.domain.workflow_definition import WorkflowDefinition

SCHEMA_VERSION_CURRENT = 1


def _instance_event(event_type: str, instance_id: str, version: int,
                    payload: dict) -> DomainEvent:
    return DomainEvent(event_type=event_type, aggregate_id=instance_id,
                       aggregate_version=version, payload=payload,
                       aggregate_type="WorkflowInstance")


@dataclass
class WorkflowInstance:
    """A single live (or terminal) execution of a WorkflowDefinition."""

    # ---- Identity (immutable) -----------------------------------------
    instance_id: str
    definition_name: str
    definition_version: int
    tenant_id: str
    country_code: str
    initiator_id: str
    created_at: str

    # ---- Lifecycle ----------------------------------------------------
    business_state: str                       # state from the definition
    lifecycle: str = InstanceState.RUNNING.value
    correlation_id: Optional[str] = None
    payload: dict = field(default_factory=dict)
    version: int = 1
    schema_version: int = SCHEMA_VERSION_CURRENT
    pending_actions: list[dict] = field(default_factory=list)
    last_command: Optional[str] = None
    last_actor: Optional[str] = None
    last_transitioned_at: Optional[str] = None
    terminated_at: Optional[str] = None
    suspended_reason: Optional[str] = None

    _events: list[DomainEvent] = field(default_factory=list,
                                        repr=False, compare=False)

    # ---- Factory ------------------------------------------------------

    @classmethod
    def start(cls, *, definition: WorkflowDefinition,
              tenant_id: str, country_code: str,
              initiator_id: str, payload: Optional[dict] = None,
              correlation_id: Optional[str] = None,
              instance_id: Optional[str] = None) -> "WorkflowInstance":
        iid = instance_id or new_instance_id()
        created_at = now_iso()
        agg = cls(instance_id=iid,
                   definition_name=definition.name,
                   definition_version=definition.version,
                   tenant_id=tenant_id,
                   country_code=country_code,
                   initiator_id=initiator_id,
                   created_at=created_at,
                   business_state=definition.initial_state,
                   correlation_id=correlation_id,
                   payload=dict(payload or {}),
                   last_transitioned_at=created_at)
        agg.pending_actions = [_action_to_dict(a)
                                for a in definition.on_enter(definition.initial_state)]
        agg._raise(_instance_event(
            "workflow.instance.started", iid, 1, {
                "instance_id": iid,
                "definition_name": definition.name,
                "definition_version": definition.version,
                "initial_state": definition.initial_state,
                "initiator_id": initiator_id,
                "payload": dict(payload or {}),
            }))
        if definition.is_terminal(definition.initial_state):
            agg._complete_terminal(definition)
        return agg

    @classmethod
    def from_state(cls, state: dict) -> "WorkflowInstance":
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

    def pull_pending_actions(self) -> list[dict]:
        out = list(self.pending_actions)
        self.pending_actions = []
        return out

    # ---- Commands -----------------------------------------------------

    def apply_command(self, *, definition: WorkflowDefinition,
                      command: str, actor: str,
                      payload: Optional[dict] = None) -> None:
        if definition.name != self.definition_name or \
           definition.version != self.definition_version:
            raise ImmutableFieldError(
                f"definition mismatch: instance bound to "
                f"{self.definition_name}@v{self.definition_version}, "
                f"got {definition.qualified_name()}")
        if self.lifecycle == InstanceState.SUSPENDED.value:
            raise SuspendedInstanceError(
                f"instance {self.instance_id} is suspended; cannot apply "
                f"command {command!r}")
        if self.lifecycle in TERMINAL_INSTANCE_STATES:
            raise TerminalInstanceError(
                f"instance {self.instance_id} is terminal ({self.lifecycle}); "
                f"cannot apply command {command!r}")
        target = definition.legal_target(self.business_state, command)
        if target is None:
            # Distinguish "no such command anywhere" from "wrong state".
            any_target = any(t.command == command for t in definition.transitions)
            if not any_target:
                raise UnknownCommandError(
                    f"command {command!r} is not declared in definition "
                    f"{definition.qualified_name()}")
            raise IllegalTransitionError(
                f"command {command!r} is not legal in state "
                f"{self.business_state!r}; legal: "
                f"{definition.known_commands(self.business_state)}")

        previous = self.business_state
        self.business_state = target
        self.version += 1
        self.last_command = command
        self.last_actor = actor
        self.last_transitioned_at = now_iso()
        self.pending_actions = [_action_to_dict(a)
                                 for a in definition.on_enter(target)]
        self._raise(_instance_event(
            "workflow.instance.transitioned", self.instance_id, self.version, {
                "instance_id": self.instance_id,
                "definition_name": self.definition_name,
                "definition_version": self.definition_version,
                "command": command,
                "actor": actor,
                "from_state": previous,
                "to_state": target,
                "payload": dict(payload or {}),
            }))
        if definition.is_terminal(target):
            self._complete_terminal(definition)

    def cancel(self, *, actor: str, reason: str) -> None:
        if self.lifecycle in TERMINAL_INSTANCE_STATES:
            raise TerminalInstanceError(
                f"instance {self.instance_id} already terminal ({self.lifecycle})")
        self.lifecycle = InstanceState.CANCELLED.value
        self.version += 1
        self.terminated_at = now_iso()
        self.pending_actions = []
        self._raise(_instance_event(
            "workflow.instance.cancelled", self.instance_id, self.version, {
                "instance_id": self.instance_id,
                "actor": actor,
                "reason": reason,
                "at_state": self.business_state,
            }))

    def suspend(self, *, actor: str, reason: str) -> None:
        if self.lifecycle != InstanceState.RUNNING.value:
            raise TerminalInstanceError(
                f"instance {self.instance_id} not running ({self.lifecycle})")
        self.lifecycle = InstanceState.SUSPENDED.value
        self.suspended_reason = reason
        self.version += 1
        self._raise(_instance_event(
            "workflow.instance.suspended", self.instance_id, self.version, {
                "instance_id": self.instance_id,
                "actor": actor,
                "reason": reason,
            }))

    def reactivate(self, *, actor: str) -> None:
        if self.lifecycle != InstanceState.SUSPENDED.value:
            raise SuspendedInstanceError(
                f"instance {self.instance_id} not suspended ({self.lifecycle})")
        self.lifecycle = InstanceState.RUNNING.value
        self.suspended_reason = None
        self.version += 1
        self._raise(_instance_event(
            "workflow.instance.reactivated", self.instance_id, self.version, {
                "instance_id": self.instance_id,
                "actor": actor,
            }))

    # ---- Internal -----------------------------------------------------

    def _complete_terminal(self, definition: WorkflowDefinition) -> None:
        self.lifecycle = InstanceState.COMPLETED.value
        self.terminated_at = now_iso()
        self.version += 1
        self._raise(_instance_event(
            "workflow.instance.completed", self.instance_id, self.version, {
                "instance_id": self.instance_id,
                "definition_name": self.definition_name,
                "definition_version": self.definition_version,
                "final_state": self.business_state,
            }))

    def to_state(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__
                if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Pure ``apply(state, event)`` for byte-identical replay.
# ---------------------------------------------------------------------------

def _action_to_dict(action) -> dict:
    return {"verb": action.verb, "params": dict(action.params)}


def replay_apply(state: Optional[dict], envelope_payload: dict,
                  event_type: str, aggregate_version: int) -> dict:
    """Pure ``apply`` used by the engine's replay path.

    The function is intentionally side-effect-free: given the prior state
    (None on the first event) and an event payload, return the new state
    dict. The engine accumulates these to rebuild a WorkflowInstance.

    Replay is byte-identical because:
    * No clock reads (timestamps come from the event payload + envelope).
    * No randomness (ids come from the event payload).
    * No conditional on side-effecting operations.
    """
    p = envelope_payload
    if event_type == "workflow.instance.started":
        return {
            "instance_id": p["instance_id"],
            "definition_name": p["definition_name"],
            "definition_version": int(p["definition_version"]),
            "tenant_id": p.get("tenant_id", ""),
            "country_code": p.get("country_code", ""),
            "initiator_id": p["initiator_id"],
            "created_at": p.get("created_at", ""),
            "business_state": p["initial_state"],
            "lifecycle": InstanceState.RUNNING.value,
            "correlation_id": p.get("correlation_id"),
            "payload": dict(p.get("payload") or {}),
            "version": aggregate_version,
            "schema_version": SCHEMA_VERSION_CURRENT,
            "pending_actions": [],
            "last_command": None,
            "last_actor": None,
            "last_transitioned_at": p.get("created_at", ""),
            "terminated_at": None,
            "suspended_reason": None,
        }
    assert state is not None, f"event {event_type!r} requires prior state"
    s = dict(state)
    s["version"] = aggregate_version
    if event_type == "workflow.instance.transitioned":
        s["business_state"] = p["to_state"]
        s["last_command"] = p["command"]
        s["last_actor"] = p["actor"]
    elif event_type == "workflow.instance.completed":
        s["lifecycle"] = InstanceState.COMPLETED.value
        s["business_state"] = p.get("final_state", s["business_state"])
    elif event_type == "workflow.instance.cancelled":
        s["lifecycle"] = InstanceState.CANCELLED.value
    elif event_type == "workflow.instance.suspended":
        s["lifecycle"] = InstanceState.SUSPENDED.value
        s["suspended_reason"] = p.get("reason")
    elif event_type == "workflow.instance.reactivated":
        s["lifecycle"] = InstanceState.RUNNING.value
        s["suspended_reason"] = None
    else:
        raise ValueError(f"replay_apply: unknown event_type {event_type!r}")
    return s
