"""Evidence domain events (Phase 3.4 + 3.5).

Each event is an immutable frozen dataclass; the aggregate raises events
via ``_raise()``; the Application Service drains them post-commit and
publishes via the transactional outbox.

Event names mirror ``kernel.events.outbox.EVENT_TYPES`` and the contract
package ``EVENT_DEFINITIONS``. New event_type strings here MUST be added
to both before they ship.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from kernel.events.envelope import Envelope, new_envelope

PRODUCER = "evidence"

# Canonical Phase 3.4+3.5 event types — mirrored by outbox + contracts.
EVIDENCE_EVENT_TYPES = (
    "evidence.item.uploaded",
    "evidence.item.hash_verified",
    "evidence.item.hash_mismatch",
    "evidence.item.archived_replaced",
    "evidence.seal.created",
    "evidence.seal.worm_applied",
    "evidence.seal.archived",
    "evidence.signed_url.issued",
    # Phase 3.6
    "evidence.lock.applied",
    "evidence.lock.extended",
    "evidence.integrity.check_started",
    "evidence.integrity.passed",
    "evidence.integrity.failed",
    "evidence.integrity.check_errored",
    "evidence.anchor.batched",
    "evidence.anchor.submitted",
    "evidence.anchor.confirmed",
    "evidence.anchor.failed",
    "evidence.anchor.replayed",
    "evidence.ctlog.checkpoint_published",
)


@dataclass(frozen=True)
class DomainEvent:
    """Base class for in-memory domain events raised by the aggregate."""
    event_type: str
    aggregate_id: str
    aggregate_version: int
    payload: dict
    event_version: int = 1
    aggregate_type: str = "EvidenceItem"

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


# ---- Factories -----------------------------------------------------------

def item_uploaded(*, evidence_id: str, version: int, payload: dict) -> DomainEvent:
    return DomainEvent(event_type="evidence.item.uploaded",
                       aggregate_id=evidence_id, aggregate_version=version,
                       payload=payload)


def item_hash_verified(*, evidence_id: str, version: int,
                        payload: dict) -> DomainEvent:
    return DomainEvent(event_type="evidence.item.hash_verified",
                       aggregate_id=evidence_id, aggregate_version=version,
                       payload=payload)


def item_hash_mismatch(*, evidence_id: str, version: int,
                       payload: dict) -> DomainEvent:
    return DomainEvent(event_type="evidence.item.hash_mismatch",
                       aggregate_id=evidence_id, aggregate_version=version,
                       payload=payload)


def item_archived_replaced(*, evidence_id: str, version: int,
                            payload: dict) -> DomainEvent:
    return DomainEvent(event_type="evidence.item.archived_replaced",
                       aggregate_id=evidence_id, aggregate_version=version,
                       payload=payload)


def seal_created(*, seal_id: str, version: int, payload: dict) -> DomainEvent:
    return DomainEvent(event_type="evidence.seal.created",
                       aggregate_id=seal_id, aggregate_version=version,
                       payload=payload, aggregate_type="Seal")


def seal_worm_applied(*, seal_id: str, version: int, payload: dict) -> DomainEvent:
    return DomainEvent(event_type="evidence.seal.worm_applied",
                       aggregate_id=seal_id, aggregate_version=version,
                       payload=payload, aggregate_type="Seal")


def seal_archived(*, seal_id: str, version: int, payload: dict) -> DomainEvent:
    return DomainEvent(event_type="evidence.seal.archived",
                       aggregate_id=seal_id, aggregate_version=version,
                       payload=payload, aggregate_type="Seal")


def signed_url_issued(*, evidence_id: str, version: int,
                       payload: dict) -> DomainEvent:
    return DomainEvent(event_type="evidence.signed_url.issued",
                       aggregate_id=evidence_id, aggregate_version=version,
                       payload=payload)
