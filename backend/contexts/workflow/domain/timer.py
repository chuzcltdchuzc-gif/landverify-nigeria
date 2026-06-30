"""Timer aggregate (Phase 4 — Slice 4.0).

A Timer is a scheduled fire that the engine raises against an instance
after the wall-clock reaches ``fire_at``. Timers are persisted so they
survive process restarts (RB-6 mitigation: jitter window applied at
boot to spread post-outage backlog).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from contexts.workflow.domain.events import DomainEvent
from contexts.workflow.domain.invariants import (
    TimerStateError,
    TerminalInstanceError,
)
from contexts.workflow.domain.value_objects import (
    TERMINAL_TIMER_STATES,
    TimerState,
    new_timer_id,
    now_iso,
)

SCHEMA_VERSION_CURRENT = 1


def _timer_event(event_type: str, timer_id: str, version: int,
                  payload: dict) -> DomainEvent:
    return DomainEvent(event_type=event_type, aggregate_id=timer_id,
                       aggregate_version=version, payload=payload,
                       aggregate_type="WorkflowTimer")


@dataclass
class Timer:
    """A scheduled fire bound to a workflow instance."""

    timer_id: str
    instance_id: str
    definition_name: str
    tenant_id: str
    country_code: str
    fire_at: str                          # ISO8601
    command_on_fire: str                  # command applied to the instance when fired
    payload_on_fire: dict
    created_at: str
    state: str = TimerState.SCHEDULED.value
    fired_at: Optional[str] = None
    cancelled_at: Optional[str] = None
    cancelled_reason: Optional[str] = None
    version: int = 1
    schema_version: int = SCHEMA_VERSION_CURRENT

    _events: list[DomainEvent] = field(default_factory=list,
                                        repr=False, compare=False)

    @classmethod
    def schedule(cls, *, instance_id: str, definition_name: str,
                 tenant_id: str, country_code: str, fire_at: str,
                 command_on_fire: str, payload_on_fire: Optional[dict] = None,
                 timer_id: Optional[str] = None) -> "Timer":
        tid = timer_id or new_timer_id()
        created_at = now_iso()
        agg = cls(timer_id=tid, instance_id=instance_id,
                   definition_name=definition_name,
                   tenant_id=tenant_id, country_code=country_code,
                   fire_at=fire_at,
                   command_on_fire=command_on_fire,
                   payload_on_fire=dict(payload_on_fire or {}),
                   created_at=created_at)
        agg._raise(_timer_event("workflow.timer.scheduled", tid, 1, {
            "timer_id": tid, "instance_id": instance_id,
            "definition_name": definition_name,
            "fire_at": fire_at,
            "command_on_fire": command_on_fire,
        }))
        return agg

    @classmethod
    def from_state(cls, state: dict) -> "Timer":
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

    def fire(self) -> None:
        if self.state != TimerState.SCHEDULED.value:
            raise TimerStateError(
                f"timer {self.timer_id} not scheduled (state={self.state})")
        self.state = TimerState.FIRED.value
        self.fired_at = now_iso()
        self.version += 1
        self._raise(_timer_event("workflow.timer.fired", self.timer_id,
                                   self.version, {
            "timer_id": self.timer_id, "instance_id": self.instance_id,
            "command_on_fire": self.command_on_fire,
        }))

    def cancel(self, *, reason: str) -> None:
        if self.state in TERMINAL_TIMER_STATES:
            raise TerminalInstanceError(
                f"timer {self.timer_id} already terminal (state={self.state})")
        self.state = TimerState.CANCELLED.value
        self.cancelled_at = now_iso()
        self.cancelled_reason = reason
        self.version += 1
        self._raise(_timer_event("workflow.timer.cancelled", self.timer_id,
                                   self.version, {
            "timer_id": self.timer_id, "instance_id": self.instance_id,
            "reason": reason,
        }))

    def to_state(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__
                if not k.startswith("_")}
