"""EvidenceLock — Phase 3.6 first-class WORM lock aggregate.

Per ADR-0008 §3.1: elevates the lock outcome from a Phase 3.5 event
payload into a queryable, auditable aggregate. Retention is
forward-only — extensions allowed, reductions structurally impossible.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from contexts.evidence.domain.events import DomainEvent
from contexts.evidence.domain.invariants import (
    ImmutableFieldError,
    InvariantViolation,
)
from contexts.evidence.domain.value_objects import now_iso

SCHEMA_VERSION_CURRENT = 1


def new_lock_id() -> str:
    return "lck_" + uuid.uuid4().hex


class LockMode(str, Enum):
    COMPLIANCE = "compliance"  # only legal mode in v1


@dataclass(frozen=True)
class ExtensionRecord:
    at: str
    by: str
    previous_until: str
    new_until: str
    reason: str

    def to_dict(self) -> dict:
        return {"at": self.at, "by": self.by,
                "previous_until": self.previous_until,
                "new_until": self.new_until, "reason": self.reason}


def _lock_event(event_type: str, lock_id: str, version: int,
                payload: dict) -> DomainEvent:
    return DomainEvent(event_type=event_type, aggregate_id=lock_id,
                       aggregate_version=version, payload=payload,
                       aggregate_type="EvidenceLock")


@dataclass
class EvidenceLock:
    """Aggregate root for one WORM lock applied to an EvidenceItem."""

    # ---- Identity (immutable) ------------------------------------------
    lock_id: str
    evidence_id: str
    seal_id: str
    tenant_id: str
    country_code: str
    storage_provider: str
    storage_locator: str
    mode: str  # LockMode value
    applied_at: str
    applied_by: str

    # ---- Lifecycle -----------------------------------------------------
    retention_until: str
    extensions: list[dict] = field(default_factory=list)
    last_status_check: Optional[str] = None
    version: int = 1
    schema_version: int = SCHEMA_VERSION_CURRENT

    _events: list[DomainEvent] = field(default_factory=list,
                                        repr=False, compare=False)

    # ---- Factory --------------------------------------------------------

    @classmethod
    def create(cls, *, evidence_id: str, seal_id: str, tenant_id: str,
               country_code: str, storage_provider: str,
               storage_locator: str, retention_until: str,
               applied_by: str, mode: str = LockMode.COMPLIANCE.value,
               lock_id: Optional[str] = None) -> "EvidenceLock":
        if mode != LockMode.COMPLIANCE.value:
            raise InvariantViolation(
                f"only compliance mode supported in v1; got {mode!r}")
        if not retention_until:
            raise InvariantViolation("retention_until is required")
        # Validate parsing
        try:
            datetime.fromisoformat(retention_until)
        except ValueError as exc:
            raise InvariantViolation(
                f"retention_until not ISO8601: {retention_until!r}") from exc
        lid = lock_id or new_lock_id()
        applied_at = now_iso()
        agg = cls(lock_id=lid, evidence_id=evidence_id, seal_id=seal_id,
                   tenant_id=tenant_id, country_code=country_code,
                   storage_provider=storage_provider,
                   storage_locator=storage_locator, mode=mode,
                   retention_until=retention_until,
                   applied_at=applied_at, applied_by=applied_by)
        agg._raise(_lock_event("evidence.lock.applied", lid, 1, {
            "lock_id": lid,
            "evidence_id": evidence_id,
            "seal_id": seal_id,
            "storage_provider": storage_provider,
            "storage_locator": storage_locator,
            "mode": mode,
            "retention_until": retention_until,
            "applied_by": applied_by,
        }))
        return agg

    @classmethod
    def from_state(cls, state: dict) -> "EvidenceLock":
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

    # ---- Commands -------------------------------------------------------

    def extend_retention(self, *, new_until: str, by: str,
                          reason: str) -> None:
        """Forward-only retention extension. Reduction is impossible —
        there is no command for it."""
        try:
            new_dt = datetime.fromisoformat(new_until)
            cur_dt = datetime.fromisoformat(self.retention_until)
        except ValueError as exc:
            raise InvariantViolation(
                f"retention timestamps must be ISO8601: {exc}") from exc
        if new_dt <= cur_dt:
            raise ImmutableFieldError(
                f"retention_until is forward-only; new={new_until} "
                f"<= current={self.retention_until}")
        ext = ExtensionRecord(at=now_iso(), by=by,
                               previous_until=self.retention_until,
                               new_until=new_until, reason=reason)
        self.extensions = list(self.extensions) + [ext.to_dict()]
        self.retention_until = new_until
        self.version += 1
        self._raise(_lock_event("evidence.lock.extended",
                                  self.lock_id, self.version, {
            "lock_id": self.lock_id,
            "evidence_id": self.evidence_id,
            "previous_until": ext.previous_until,
            "new_until": ext.new_until,
            "by": by,
            "reason": reason,
        }))

    def record_status_check(self, *, probed_at: str) -> None:
        """Bumps the operational `last_status_check`. No event."""
        self.last_status_check = probed_at

    def to_state(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__
                if not k.startswith("_")}
