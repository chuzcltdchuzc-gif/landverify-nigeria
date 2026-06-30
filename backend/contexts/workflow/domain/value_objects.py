"""Workflow value objects (Phase 4 — Slice 4.0).

Pure data structures used by the engine + definitions. No IO.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_instance_id() -> str:
    return "wfi_" + uuid.uuid4().hex


def new_task_id() -> str:
    return "wft_" + uuid.uuid4().hex


def new_timer_id() -> str:
    return "wfm_" + uuid.uuid4().hex


def new_compensation_id() -> str:
    return "wfc_" + uuid.uuid4().hex


class InstanceState(str, Enum):
    """Engine-level lifecycle states. Distinct from workflow-specific
    business states defined in the JSON definition.

    Mapping:
    * ``RUNNING`` — instance is alive and at a non-terminal business state.
    * ``SUSPENDED`` — operator paused; no commands or timers fire.
    * ``CANCELLED`` — operator cancelled before reaching terminal.
    * ``COMPLETED`` — instance reached a terminal state per the definition.
    """
    RUNNING = "running"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


TERMINAL_INSTANCE_STATES: frozenset[str] = frozenset({
    InstanceState.CANCELLED.value,
    InstanceState.COMPLETED.value,
})


class TaskState(str, Enum):
    OPEN = "open"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


TERMINAL_TASK_STATES: frozenset[str] = frozenset({
    TaskState.COMPLETED.value,
    TaskState.CANCELLED.value,
    TaskState.EXPIRED.value,
})


class TimerState(str, Enum):
    SCHEDULED = "scheduled"
    FIRED = "fired"
    CANCELLED = "cancelled"


TERMINAL_TIMER_STATES: frozenset[str] = frozenset({
    TimerState.FIRED.value,
    TimerState.CANCELLED.value,
})


@dataclass(frozen=True)
class StateTransition:
    """A single declared transition in a WorkflowDefinition."""
    from_state: str
    command: str
    to_state: str
