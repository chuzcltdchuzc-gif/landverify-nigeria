"""Domain Event Envelope — the binding shape every event carries (Section 2.3).

Versioning policy:
    * `event_version` is the schema version of the payload for this event_type.
      It starts at 1; additive changes increment minor; breaking changes mint a
      NEW event_type (Section 2.2). Old versions are never mutated.
    * `aggregate_version` is the optimistic-concurrency value of the source
      aggregate at the moment of the event — invaluable for read models.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Envelope:
    event_id: str
    event_type: str
    event_version: int
    aggregate_type: str
    aggregate_id: str
    aggregate_version: int
    occurred_at: str
    producer: str                       # "identity" | "registry" | "landvault" | ...
    payload: dict
    # Scope (mirrors ExecutionContext at emission time)
    tenant_id: Optional[str] = None
    country: Optional[str] = None
    organization_id: Optional[str] = None
    # Tracing
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    actor: Optional[str] = None         # principal_id who caused the event

    def to_doc(self) -> dict:
        return asdict(self)


def new_envelope(
    *, event_type: str, event_version: int, aggregate_type: str,
    aggregate_id: str, aggregate_version: int, payload: dict, producer: str,
    tenant_id: Optional[str] = None, country: Optional[str] = None,
    organization_id: Optional[str] = None, correlation_id: Optional[str] = None,
    causation_id: Optional[str] = None, actor: Optional[str] = None,
) -> Envelope:
    return Envelope(
        event_id="evt_" + uuid.uuid4().hex,
        event_type=event_type,
        event_version=event_version,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=aggregate_version,
        occurred_at=_now_iso(),
        producer=producer,
        payload=dict(payload),
        tenant_id=tenant_id, country=country, organization_id=organization_id,
        correlation_id=correlation_id, causation_id=causation_id, actor=actor,
    )
