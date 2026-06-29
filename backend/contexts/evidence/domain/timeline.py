"""Phase 3.7 — Evidence Timeline, Custody Chain, Supersession, Legal Hold.

Three append-only chained aggregates + one supersession value object:

* ``TimelineEntry`` — chronological event log per evidence_id.
* ``CustodyEntry``  — chain-of-custody per evidence_id with cryptographic
  signature metadata.
* ``LegalHold``     — independent aggregate that overrides retention.
* Supersession is recorded inline on ``EvidenceItem`` (Phase 3.4 already
  has ``replaced_by``/``replaced_at``); Phase 3.7 adds ``previous_version_id``
  + ``superseded_reason`` and surfaces a traversal API.

All four use the ``compute_entry_hash`` chain primitive from
``domain/chain.py`` so any link can be independently verified by an
offline auditor (Phase 3.10).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from contexts.evidence.domain.chain import compute_entry_hash
from contexts.evidence.domain.events import DomainEvent
from contexts.evidence.domain.invariants import (
    ImmutableFieldError,
    InvariantViolation,
    TransitionError,
)
from contexts.evidence.domain.value_objects import now_iso


# ============================================================================
# Timeline
# ============================================================================

class TimelineEventKind(str, Enum):
    UPLOAD = "upload"
    VERIFICATION = "verification"
    SEAL = "seal"
    LOCK = "lock"
    LOCK_EXTENDED = "lock_extended"
    INTEGRITY = "integrity"
    ANCHOR = "anchor"
    VERSION_CREATED = "version_created"
    SUPERSESSION = "supersession"
    LEGAL_HOLD_APPLIED = "legal_hold_applied"
    LEGAL_HOLD_RELEASED = "legal_hold_released"
    ACCESS_GRANTED = "access_granted"
    ACCESS_REVOKED = "access_revoked"


def new_timeline_id() -> str:
    return "tln_" + uuid.uuid4().hex


@dataclass
class TimelineEntry:
    """Single immutable timeline link. Insert-only at the adapter."""

    timeline_id: str
    evidence_id: str
    tenant_id: str
    country_code: str
    kind: str           # TimelineEventKind
    actor: str
    occurred_at: str
    seq: int
    prev_hash: Optional[str]
    entry_hash: str
    summary: str        # short human-readable line
    payload: dict       # structured detail (event_id, refs, etc.)
    schema_version: int = 1

    @classmethod
    def create(cls, *, evidence_id: str, tenant_id: str, country_code: str,
               kind: str, actor: str, seq: int,
               prev_hash: Optional[str], summary: str,
               payload: dict) -> "TimelineEntry":
        if kind not in {k.value for k in TimelineEventKind}:
            raise InvariantViolation(f"invalid timeline kind: {kind!r}")
        if seq < 0:
            raise InvariantViolation("seq must be >= 0")
        if seq == 0 and prev_hash is not None:
            raise InvariantViolation("genesis entry must have prev_hash=None")
        if seq > 0 and prev_hash is None:
            raise InvariantViolation("non-genesis requires prev_hash")
        tid = new_timeline_id()
        occurred_at = now_iso()
        chain_payload = {
            "timeline_id": tid, "evidence_id": evidence_id, "kind": kind,
            "actor": actor, "occurred_at": occurred_at, "seq": seq,
            "summary": summary, "payload": payload,
        }
        entry_hash = compute_entry_hash(prev_hash, chain_payload)
        return cls(timeline_id=tid, evidence_id=evidence_id,
                    tenant_id=tenant_id, country_code=country_code,
                    kind=kind, actor=actor, occurred_at=occurred_at,
                    seq=seq, prev_hash=prev_hash, entry_hash=entry_hash,
                    summary=summary, payload=payload)

    @classmethod
    def from_state(cls, state: dict) -> "TimelineEntry":
        clean = {k: v for k, v in state.items()
                 if k in cls.__dataclass_fields__}
        return cls(**clean)

    def to_state(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


# ============================================================================
# Custody
# ============================================================================

class CustodyAction(str, Enum):
    CREATED = "created"
    TRANSFERRED = "transferred"
    SIGNED = "signed"
    ACCESSED = "accessed"
    EXPORTED = "exported"
    RELEASED = "released"


def new_custody_id() -> str:
    return "cus_" + uuid.uuid4().hex


@dataclass
class CustodyEntry:
    """Chain-of-custody link. Insert-only at the adapter."""

    custody_id: str
    evidence_id: str
    tenant_id: str
    country_code: str
    actor: str
    role: str
    action: str          # CustodyAction
    occurred_at: str
    justification: str
    signature_kid: Optional[str]
    signature: Optional[str]
    previous_custody_id: Optional[str]
    seq: int
    prev_hash: Optional[str]
    entry_hash: str
    schema_version: int = 1

    @classmethod
    def create(cls, *, evidence_id: str, tenant_id: str, country_code: str,
               actor: str, role: str, action: str,
               justification: str, seq: int,
               prev_hash: Optional[str],
               previous_custody_id: Optional[str] = None,
               signature_kid: Optional[str] = None,
               signature: Optional[str] = None) -> "CustodyEntry":
        if action not in {a.value for a in CustodyAction}:
            raise InvariantViolation(f"invalid custody action: {action!r}")
        if not justification or len(justification) < 3:
            raise InvariantViolation("custody requires non-empty justification")
        if seq < 0:
            raise InvariantViolation("seq must be >= 0")
        if seq == 0 and prev_hash is not None:
            raise InvariantViolation("genesis custody requires prev_hash=None")
        if seq > 0 and prev_hash is None:
            raise InvariantViolation("non-genesis requires prev_hash")
        cid = new_custody_id()
        occurred_at = now_iso()
        chain_payload = {
            "custody_id": cid, "evidence_id": evidence_id, "actor": actor,
            "role": role, "action": action, "occurred_at": occurred_at,
            "justification": justification, "seq": seq,
            "previous_custody_id": previous_custody_id,
            "signature_kid": signature_kid, "signature": signature,
        }
        entry_hash = compute_entry_hash(prev_hash, chain_payload)
        return cls(custody_id=cid, evidence_id=evidence_id,
                    tenant_id=tenant_id, country_code=country_code,
                    actor=actor, role=role, action=action,
                    occurred_at=occurred_at, justification=justification,
                    signature_kid=signature_kid, signature=signature,
                    previous_custody_id=previous_custody_id,
                    seq=seq, prev_hash=prev_hash, entry_hash=entry_hash)

    @classmethod
    def from_state(cls, state: dict) -> "CustodyEntry":
        clean = {k: v for k, v in state.items()
                 if k in cls.__dataclass_fields__}
        return cls(**clean)

    def to_state(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


# ============================================================================
# Legal Hold (independent aggregate that overrides retention)
# ============================================================================

class LegalHoldStatus(str, Enum):
    ACTIVE = "active"
    RELEASED = "released"


def new_hold_id() -> str:
    return "hld_" + uuid.uuid4().hex


def _hold_event(event_type: str, hold_id: str, version: int,
                payload: dict) -> DomainEvent:
    return DomainEvent(event_type=event_type, aggregate_id=hold_id,
                       aggregate_version=version, payload=payload,
                       aggregate_type="LegalHold")


@dataclass
class LegalHold:
    """Independent retention-override aggregate.

    A LegalHold is **immutable post-creation** except for the explicit
    one-way ``release()`` transition. Both creation and release emit
    immutable events. While ACTIVE, evidence under hold MUST NOT
    expire, be deleted, or be archived prematurely — the enforcement is
    in the retention sweeper (Phase 3.8 territory; this aggregate is
    the system of record).
    """

    hold_id: str
    evidence_id: str
    tenant_id: str
    country_code: str
    case_reference: str
    issued_by: str
    issued_at: str
    reason: str
    status: str = LegalHoldStatus.ACTIVE.value
    released_at: Optional[str] = None
    released_by: Optional[str] = None
    release_reason: Optional[str] = None
    version: int = 1
    schema_version: int = 1

    _events: list[DomainEvent] = field(default_factory=list, repr=False,
                                        compare=False)

    @classmethod
    def create(cls, *, evidence_id: str, tenant_id: str, country_code: str,
               case_reference: str, issued_by: str, reason: str,
               hold_id: Optional[str] = None) -> "LegalHold":
        if not case_reference or len(case_reference) < 3:
            raise InvariantViolation("case_reference required")
        if not reason or len(reason) < 3:
            raise InvariantViolation("reason required")
        hid = hold_id or new_hold_id()
        issued_at = now_iso()
        agg = cls(hold_id=hid, evidence_id=evidence_id,
                   tenant_id=tenant_id, country_code=country_code,
                   case_reference=case_reference, issued_by=issued_by,
                   issued_at=issued_at, reason=reason)
        agg._raise(_hold_event("evidence.legal_hold.applied", hid, 1, {
            "hold_id": hid, "evidence_id": evidence_id,
            "case_reference": case_reference,
            "issued_by": issued_by, "reason": reason,
        }))
        return agg

    @classmethod
    def from_state(cls, state: dict) -> "LegalHold":
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

    def release(self, *, released_by: str, release_reason: str) -> None:
        if self.status == LegalHoldStatus.RELEASED.value:
            raise TransitionError("legal hold already released")
        if not release_reason or len(release_reason) < 3:
            raise InvariantViolation("release_reason required")
        self.status = LegalHoldStatus.RELEASED.value
        self.released_at = now_iso()
        self.released_by = released_by
        self.release_reason = release_reason
        self.version += 1
        self._raise(_hold_event("evidence.legal_hold.released",
                                  self.hold_id, self.version, {
            "hold_id": self.hold_id, "evidence_id": self.evidence_id,
            "released_by": released_by,
            "release_reason": release_reason,
        }))

    @property
    def is_active(self) -> bool:
        return self.status == LegalHoldStatus.ACTIVE.value

    def to_state(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__
                if not k.startswith("_")}


# ============================================================================
# Supersession value object (read API over EvidenceItem.replaced_by chain)
# ============================================================================

@dataclass(frozen=True)
class SupersessionLink:
    evidence_id: str
    previous_version_id: Optional[str]
    superseded_by: Optional[str]
    superseded_at: Optional[str]
    superseded_reason: Optional[str]

    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "previous_version_id": self.previous_version_id,
            "superseded_by": self.superseded_by,
            "superseded_at": self.superseded_at,
            "superseded_reason": self.superseded_reason,
        }
