"""EvidenceIntegrityCheck — Phase 3.6 immutable re-hash verification log.

Per ADR-0008 §3.2 + §15 Decision 4. Append-only, chained via
``prev_hash``/``entry_hash`` (see `domain/chain.py`). Mandatory triggers
enumerated in §15 Decision 4.
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
from contexts.evidence.domain.value_objects import ContentHash, now_iso

SCHEMA_VERSION_CURRENT = 1


def new_check_id() -> str:
    return "chk_" + uuid.uuid4().hex


class IntegrityTrigger(str, Enum):
    SCHEDULED = "scheduled"
    ON_DEMAND = "on_demand"
    PRE_SEAL = "pre_seal"
    PRE_CERTIFICATE = "pre_certificate"
    PRE_PUBLIC_VERIFICATION = "pre_public_verification"
    PRE_OWNERSHIP_TRANSFER = "pre_ownership_transfer"
    PRE_SUBDIVISION = "pre_subdivision"
    POST_STORAGE_MIGRATION = "post_storage_migration"
    POST_REMEDIATION = "post_remediation"
    SECURITY_INCIDENT = "security_incident"


class IntegrityOutcome(str, Enum):
    RUNNING = "running"
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"


def _integrity_event(event_type: str, check_id: str, version: int,
                       payload: dict) -> DomainEvent:
    return DomainEvent(event_type=event_type, aggregate_id=check_id,
                       aggregate_version=version, payload=payload,
                       aggregate_type="EvidenceIntegrityCheck")


@dataclass
class EvidenceIntegrityCheck:
    """Single re-hash verification record. Insert-once at the repository."""

    # ---- Identity (immutable) ------------------------------------------
    check_id: str
    evidence_id: str
    tenant_id: str
    country_code: str
    triggered_by: str  # IntegrityTrigger
    triggered_by_principal: Optional[str]
    expected_hash: str
    started_at: str
    seq: int

    # ---- Chain (immutable) ---------------------------------------------
    prev_hash: Optional[str]
    entry_hash: str

    # ---- Outcome (write-once) ------------------------------------------
    outcome: str = IntegrityOutcome.RUNNING.value
    observed_hash: Optional[str] = None
    lock_status_observed: Optional[dict] = None
    completed_at: Optional[str] = None
    error_summary: Optional[str] = None

    schema_version: int = SCHEMA_VERSION_CURRENT
    version: int = 1

    _events: list[DomainEvent] = field(default_factory=list,
                                        repr=False, compare=False)

    @classmethod
    def start(cls, *, evidence_id: str, tenant_id: str, country_code: str,
              triggered_by: str, expected_hash: str, seq: int,
              prev_hash: Optional[str],
              triggered_by_principal: Optional[str] = None,
              check_id: Optional[str] = None) -> "EvidenceIntegrityCheck":
        if triggered_by not in {t.value for t in IntegrityTrigger}:
            raise InvariantViolation(
                f"invalid triggered_by: {triggered_by!r}")
        ContentHash(value=expected_hash)
        if seq < 0:
            raise InvariantViolation("seq must be >= 0")
        if seq == 0 and prev_hash is not None:
            raise InvariantViolation("genesis entry must have prev_hash=None")
        if seq > 0 and prev_hash is None:
            raise InvariantViolation("non-genesis entry requires prev_hash")
        cid = check_id or new_check_id()
        started_at = now_iso()
        payload = {
            "check_id": cid, "evidence_id": evidence_id,
            "tenant_id": tenant_id, "country_code": country_code,
            "triggered_by": triggered_by,
            "triggered_by_principal": triggered_by_principal,
            "expected_hash": expected_hash, "seq": seq,
            "started_at": started_at,
        }
        entry_hash = compute_entry_hash(prev_hash, payload)
        agg = cls(check_id=cid, evidence_id=evidence_id,
                   tenant_id=tenant_id, country_code=country_code,
                   triggered_by=triggered_by,
                   triggered_by_principal=triggered_by_principal,
                   expected_hash=expected_hash, started_at=started_at,
                   seq=seq, prev_hash=prev_hash, entry_hash=entry_hash)
        agg._raise(_integrity_event("evidence.integrity.check_started",
                                       cid, 1, {
            "check_id": cid, "evidence_id": evidence_id,
            "triggered_by": triggered_by,
            "expected_hash": expected_hash, "seq": seq,
        }))
        return agg

    @classmethod
    def from_state(cls, state: dict) -> "EvidenceIntegrityCheck":
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

    def _ensure_running(self) -> None:
        if self.outcome != IntegrityOutcome.RUNNING.value:
            raise TransitionError(
                f"check {self.check_id} already terminal ({self.outcome})")

    def record_pass(self, *, observed_hash: str,
                     lock_status: Optional[dict] = None) -> None:
        self._ensure_running()
        ContentHash(value=observed_hash)
        if observed_hash != self.expected_hash:
            raise InvariantViolation(
                "record_pass requires observed_hash == expected_hash")
        self.observed_hash = observed_hash
        self.lock_status_observed = lock_status
        self.completed_at = now_iso()
        self.outcome = IntegrityOutcome.PASS.value
        self.version += 1
        self._raise(_integrity_event("evidence.integrity.passed",
                                        self.check_id, self.version, {
            "check_id": self.check_id,
            "evidence_id": self.evidence_id,
            "triggered_by": self.triggered_by,
            "expected_hash": self.expected_hash,
            "observed_hash": observed_hash,
        }))

    def record_fail(self, *, observed_hash: str, reason: str,
                     lock_status: Optional[dict] = None) -> None:
        self._ensure_running()
        ContentHash(value=observed_hash)
        if observed_hash == self.expected_hash:
            raise InvariantViolation(
                "record_fail requires observed_hash != expected_hash")
        self.observed_hash = observed_hash
        self.lock_status_observed = lock_status
        self.completed_at = now_iso()
        self.outcome = IntegrityOutcome.FAIL.value
        self.error_summary = reason
        self.version += 1
        self._raise(_integrity_event("evidence.integrity.failed",
                                        self.check_id, self.version, {
            "check_id": self.check_id,
            "evidence_id": self.evidence_id,
            "triggered_by": self.triggered_by,
            "expected_hash": self.expected_hash,
            "observed_hash": observed_hash,
            "reason": reason,
        }))

    def record_error(self, *, error_summary: str) -> None:
        self._ensure_running()
        self.completed_at = now_iso()
        self.outcome = IntegrityOutcome.ERROR.value
        self.error_summary = error_summary
        self.version += 1
        self._raise(_integrity_event("evidence.integrity.check_errored",
                                        self.check_id, self.version, {
            "check_id": self.check_id,
            "evidence_id": self.evidence_id,
            "triggered_by": self.triggered_by,
            "error_summary": error_summary,
        }))

    def to_state(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__
                if not k.startswith("_")}
