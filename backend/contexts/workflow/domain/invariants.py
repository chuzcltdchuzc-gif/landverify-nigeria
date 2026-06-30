"""Workflow invariants and exceptions (Phase 4 — Slice 4.0)."""
from __future__ import annotations


class InvariantViolation(Exception):
    """Base class for any workflow invariant breach."""


class IllegalTransitionError(InvariantViolation):
    """Command rejected because the target state is unreachable from the
    current state under the workflow definition."""


class TerminalInstanceError(InvariantViolation):
    """Operation rejected because the instance is already terminal."""


class SuspendedInstanceError(InvariantViolation):
    """Operation rejected because the instance is suspended."""


class ImmutableFieldError(InvariantViolation):
    """Attempt to mutate a write-once field."""


class ConcurrencyConflict(InvariantViolation):
    """Optimistic concurrency check failed (version mismatch)."""


class DefinitionError(InvariantViolation):
    """Workflow definition JSON failed structural validation
    (unknown state, cyclical spawn, malformed transition, etc.)."""


class TaskStateError(InvariantViolation):
    """Task command rejected (e.g. completing a task that's not claimed)."""


class TimerStateError(InvariantViolation):
    """Timer command rejected (e.g. firing a cancelled timer)."""


class UnknownCommandError(InvariantViolation):
    """Command name is not declared by the workflow definition."""
