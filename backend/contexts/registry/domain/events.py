"""Registry domain events.

Each event is an immutable frozen dataclass. The aggregate raises events
via `_raise()`; the Application Service drains them post-commit and
hands them to the transactional outbox.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from kernel.events.envelope import Envelope, new_envelope

# Canonical registry event types — mirror the contract package's
# EVENT_DEFINITIONS. New event_type strings here MUST be added to:
#   * kernel.events.outbox.EVENT_TYPES
#   * contracts/generate.py:EVENT_DEFINITIONS (then `python -m contracts.generate`)
REGISTRY_EVENT_TYPES = (
    "registry.landvault.created",
    "registry.landvault.updated",
    "registry.parcel_reference.allocated",
    "registry.ownership.recorded",
    "registry.landvault.archived",
)

PRODUCER = "registry"


@dataclass(frozen=True)
class DomainEvent:
    """Base class for in-memory domain events raised by the aggregate."""
    event_type: str
    aggregate_id: str
    aggregate_version: int
    payload: dict
    event_version: int = 1
    aggregate_type: str = "LandVault"

    def to_envelope(
        self, *, tenant_id: Optional[str], country: Optional[str],
        organization_id: Optional[str] = None, actor: Optional[str] = None,
        correlation_id: Optional[str] = None, causation_id: Optional[str] = None,
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


def landvault_created(*, registry_id: str, version: int, payload: dict) -> DomainEvent:
    return DomainEvent(event_type="registry.landvault.created",
                       aggregate_id=registry_id, aggregate_version=version,
                       payload=payload)


def landvault_updated(*, registry_id: str, version: int, payload: dict) -> DomainEvent:
    return DomainEvent(event_type="registry.landvault.updated",
                       aggregate_id=registry_id, aggregate_version=version,
                       payload=payload)


def parcel_reference_allocated(*, registry_id: str, version: int,
                               payload: dict) -> DomainEvent:
    return DomainEvent(event_type="registry.parcel_reference.allocated",
                       aggregate_id=registry_id, aggregate_version=version,
                       payload=payload)


def ownership_recorded(*, registry_id: str, version: int, payload: dict) -> DomainEvent:
    return DomainEvent(event_type="registry.ownership.recorded",
                       aggregate_id=registry_id, aggregate_version=version,
                       payload=payload)


def landvault_archived(*, registry_id: str, version: int, payload: dict) -> DomainEvent:
    return DomainEvent(event_type="registry.landvault.archived",
                       aggregate_id=registry_id, aggregate_version=version,
                       payload=payload)
