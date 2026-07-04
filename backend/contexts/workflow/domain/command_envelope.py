"""CommandEnvelope aggregate (Phase 4 — Slice 4.1).

An outbound command envelope raised by an ``emit_command`` action in a
workflow definition. The engine persists the envelope in a dedicated
Mongo collection (``workflow_command_outbox``) inside the SAME
transaction as the workflow state write. A downstream dispatcher (in
this bounded context) attempts delivery, retries with exponential
backoff, and dead-letters on exhaustion.

Constitutional rules:
* The workflow engine NEVER writes directly to another bounded
  context (ADR-0022). Commands are envelopes on our own queue; target
  contexts pull / subscribe.
* Commands are content, not code: only fixed fields (target, command,
  payload). No expressions.
* Every state change on a CommandEnvelope produces an audit trail but
  NO public contract event (v2.0.0 contract is frozen). Internal
  state is kept in Mongo only.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from contexts.workflow.domain.value_objects import now_iso


class CommandStatus(str, Enum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    DELIVERED = "delivered"
    FAILED = "failed"
    DEAD_LETTERED = "dead_lettered"


TERMINAL_COMMAND_STATUSES = frozenset({
    CommandStatus.DELIVERED.value,
    CommandStatus.DEAD_LETTERED.value,
})


def new_command_id() -> str:
    return "wfcmd_" + uuid.uuid4().hex


@dataclass
class CommandEnvelope:
    """One outbound command envelope produced by ``emit_command``."""

    command_id: str
    instance_id: str
    definition_name: str
    tenant_id: str
    country_code: str
    target_context: str          # e.g. "registry" | "evidence"
    command_name: str            # e.g. "record_ownership_transfer"
    payload: dict
    created_at: str
    status: str = CommandStatus.PENDING.value
    attempts: int = 0
    max_attempts: int = 5
    next_attempt_at: Optional[str] = None       # ISO8601; None = ready now
    last_error: Optional[str] = None
    delivered_at: Optional[str] = None
    dead_lettered_at: Optional[str] = None
    version: int = 1
    schema_version: int = 1

    @classmethod
    def create(cls, *, instance_id: str, definition_name: str,
               tenant_id: str, country_code: str,
               target_context: str, command_name: str,
               payload: Optional[dict] = None,
               max_attempts: int = 5,
               command_id: Optional[str] = None) -> "CommandEnvelope":
        return cls(
            command_id=command_id or new_command_id(),
            instance_id=instance_id,
            definition_name=definition_name,
            tenant_id=tenant_id,
            country_code=country_code,
            target_context=target_context,
            command_name=command_name,
            payload=dict(payload or {}),
            created_at=now_iso(),
            max_attempts=max_attempts,
        )

    @classmethod
    def from_state(cls, state: dict) -> "CommandEnvelope":
        clean = {k: v for k, v in state.items()
                 if k in cls.__dataclass_fields__ and not k.startswith("_")}
        return cls(**clean)

    def mark_in_flight(self) -> None:
        if self.status in TERMINAL_COMMAND_STATUSES:
            return
        self.status = CommandStatus.IN_FLIGHT.value
        self.version += 1

    def mark_delivered(self) -> None:
        self.status = CommandStatus.DELIVERED.value
        self.delivered_at = now_iso()
        self.attempts += 1
        self.last_error = None
        self.next_attempt_at = None
        self.version += 1

    def mark_failed(self, *, error: str,
                    next_attempt_at: Optional[str]) -> None:
        self.attempts += 1
        self.last_error = error
        if self.attempts >= self.max_attempts:
            self.status = CommandStatus.DEAD_LETTERED.value
            self.dead_lettered_at = now_iso()
            self.next_attempt_at = None
        else:
            self.status = CommandStatus.FAILED.value
            self.next_attempt_at = next_attempt_at
        self.version += 1

    def to_state(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__
                if not k.startswith("_")}
