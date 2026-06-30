"""Workflow domain events (Phase 4 — Slice 4.0).

Names mirror ``kernel.events.outbox.EVENT_TYPES`` and the contract
package ``EVENT_DEFINITIONS``. New event_type strings here MUST be added
to both before they ship.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from kernel.events.envelope import Envelope, new_envelope

PRODUCER = "workflow"


# Canonical Phase 4 Slice 4.0 event types.
WORKFLOW_EVENT_TYPES = (
    "workflow.instance.started",
    "workflow.instance.transitioned",
    "workflow.instance.completed",
    "workflow.instance.cancelled",
    "workflow.instance.suspended",
    "workflow.instance.reactivated",
    "workflow.task.created",
    "workflow.task.claimed",
    "workflow.task.completed",
    "workflow.task.cancelled",
    "workflow.task.expired",
    "workflow.timer.scheduled",
    "workflow.timer.fired",
    "workflow.timer.cancelled",
    "workflow.compensation.recorded",
)


@dataclass(frozen=True)
class DomainEvent:
    """In-memory domain event raised by an aggregate; the engine
    drains them post-commit and publishes via the transactional outbox."""
    event_type: str
    aggregate_id: str
    aggregate_version: int
    payload: dict
    event_version: int = 1
    aggregate_type: str = "WorkflowInstance"

    def to_envelope(
        self, *, tenant_id: Optional[str], country: Optional[str],
        organization_id: Optional[str] = None, actor: Optional[str] = None,
        correlation_id: Optional[str] = None,
        causation_id: Optional[str] = None,
    ) -> Envelope:
        return new_envelope(
            event_type=self.event_type, event_version=self.event_version,
            aggregate_type=self.aggregate_type,
            aggregate_id=self.aggregate_id,
            aggregate_version=self.aggregate_version,
            payload=self.payload, producer=PRODUCER,
            tenant_id=tenant_id, country=country,
            organization_id=organization_id, actor=actor,
            correlation_id=correlation_id, causation_id=causation_id,
        )
