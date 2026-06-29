"""AnchorBatch — Phase 3.6 saga aggregate.

Per ADR-0008 §3.3 and §6: eight-state FSM with strict transition rules.
Companion ``AnchorAttempt`` value object is the append-only attempt log
(persisted to ``evidence_anchor_attempts`` via the chain in
``domain/chain.py``).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from contexts.evidence.domain.events import DomainEvent
from contexts.evidence.domain.invariants import (
    ImmutableFieldError,
    InvariantViolation,
    TransitionError,
)
from contexts.evidence.domain.value_objects import (
    compute_merkle_root,
    now_iso,
)

SCHEMA_VERSION_CURRENT = 1


def new_batch_id() -> str:
    return "bch_" + uuid.uuid4().hex


class AnchorProvider(str, Enum):
    CTLOG_INTERNAL = "ctlog_internal"
    OTS_V1 = "ots_v1"


class BatchState(str, Enum):
    PENDING_BATCH = "pending_batch"
    SEALED = "sealed"
    SUBMITTED = "submitted"
    CONFIRMING = "confirming"
    CONFIRMED = "confirmed"  # terminal positive
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"  # terminal negative
    REPLAY = "replay"  # transient — emits a NEW batch


TERMINAL_STATES = frozenset({BatchState.CONFIRMED.value,
                              BatchState.DEAD_LETTER.value})


# Legal transitions: src -> {dst...}
LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    BatchState.PENDING_BATCH.value: frozenset({BatchState.SEALED.value}),
    BatchState.SEALED.value:        frozenset({BatchState.SUBMITTED.value}),
    BatchState.SUBMITTED.value:     frozenset({BatchState.CONFIRMING.value,
                                                 BatchState.FAILED.value}),
    BatchState.CONFIRMING.value:    frozenset({BatchState.CONFIRMED.value,
                                                 BatchState.FAILED.value}),
    BatchState.FAILED.value:        frozenset({BatchState.SUBMITTED.value,
                                                 BatchState.DEAD_LETTER.value}),
    BatchState.CONFIRMED.value:     frozenset(),  # terminal
    BatchState.DEAD_LETTER.value:   frozenset({BatchState.REPLAY.value}),
    BatchState.REPLAY.value:        frozenset(),  # produces new batch
}


@dataclass(frozen=True)
class LeafRecord:
    seal_id: str
    merkle_root: str

    def to_dict(self) -> dict:
        return {"seal_id": self.seal_id, "merkle_root": self.merkle_root}


def _anchor_event(event_type: str, batch_id: str, version: int,
                    payload: dict) -> DomainEvent:
    return DomainEvent(event_type=event_type, aggregate_id=batch_id,
                       aggregate_version=version, payload=payload,
                       aggregate_type="AnchorBatch")


@dataclass
class AnchorBatch:
    """Saga aggregate. One row per (Seal-set, provider) pair."""

    # ---- Identity (immutable) ------------------------------------------
    batch_id: str
    provider_id: str
    tenant_id: str
    country_code: str
    seal_ids: list[str]           # sorted lexicographically
    seal_leaves: list[dict]       # [{seal_id, merkle_root}], sorted
    merkle_root: str
    created_at: str

    # ---- Saga state ----------------------------------------------------
    state: str = BatchState.PENDING_BATCH.value
    attempts: int = 0
    last_attempt_at: Optional[str] = None
    next_attempt_at: Optional[str] = None
    provider_request_id: Optional[str] = None
    provider_response: Optional[dict] = None
    inclusion_proofs: Optional[dict] = None  # write-once on CONFIRMED
    dlq_reason: Optional[str] = None
    replayed_from: Optional[str] = None
    confirmed_at: Optional[str] = None
    version: int = 1
    schema_version: int = SCHEMA_VERSION_CURRENT

    _events: list[DomainEvent] = field(default_factory=list,
                                        repr=False, compare=False)

    @classmethod
    def create(cls, *, provider_id: str, tenant_id: str, country_code: str,
                seals: list[dict], replayed_from: Optional[str] = None,
                batch_id: Optional[str] = None) -> "AnchorBatch":
        """`seals` is a list of `{seal_id, merkle_root}` for sealed,
        WORM-applied Seals. Determinism: leaves are sorted by seal_id."""
        if not seals:
            raise InvariantViolation("anchor batch requires >= 1 seal")
        if provider_id not in {p.value for p in AnchorProvider}:
            raise InvariantViolation(f"unknown provider: {provider_id!r}")
        seen: set[str] = set()
        for s in seals:
            for f in ("seal_id", "merkle_root"):
                if not s.get(f):
                    raise InvariantViolation(f"seal missing {f}: {s!r}")
            if s["seal_id"] in seen:
                raise InvariantViolation(f"duplicate seal in batch: {s['seal_id']}")
            seen.add(s["seal_id"])
        leaves_sorted = sorted(seals, key=lambda s: s["seal_id"])
        seal_ids = [s["seal_id"] for s in leaves_sorted]
        leaf_hashes = [s["merkle_root"] for s in leaves_sorted]
        root = compute_merkle_root(leaf_hashes)
        bid = batch_id or new_batch_id()
        created_at = now_iso()
        agg = cls(
            batch_id=bid, provider_id=provider_id, tenant_id=tenant_id,
            country_code=country_code, seal_ids=seal_ids,
            seal_leaves=[LeafRecord(s["seal_id"], s["merkle_root"]).to_dict()
                          for s in leaves_sorted],
            merkle_root=root, created_at=created_at,
            replayed_from=replayed_from,
        )
        return agg

    @classmethod
    def from_state(cls, state: dict) -> "AnchorBatch":
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

    # ---- FSM enforcement ------------------------------------------------

    def _enforce_transition(self, new_state: str) -> None:
        legal = LEGAL_TRANSITIONS.get(self.state, frozenset())
        if new_state not in legal:
            raise TransitionError(
                f"illegal AnchorBatch transition {self.state!r} -> "
                f"{new_state!r} (legal: {sorted(legal)})")

    def _ensure_not_terminal_locked(self) -> None:
        """Frozen records: confirmed + dead_letter MUST NOT be mutated."""
        if self.state in TERMINAL_STATES:
            raise ImmutableFieldError(
                f"batch {self.batch_id} is terminal ({self.state}); "
                f"mutation forbidden")

    # ---- Commands -------------------------------------------------------

    def mark_sealed(self) -> None:
        """Persist-commit handshake — moves from pending_batch to sealed."""
        self._enforce_transition(BatchState.SEALED.value)
        self.state = BatchState.SEALED.value
        self.version += 1
        self._raise(_anchor_event("evidence.anchor.batched",
                                     self.batch_id, self.version, {
            "batch_id": self.batch_id,
            "provider_id": self.provider_id,
            "merkle_root": self.merkle_root,
            "seal_ids": list(self.seal_ids),
            "seal_count": len(self.seal_ids),
            "replayed_from": self.replayed_from,
        }))

    def mark_submitted(self, *, provider_request_id: str,
                         provider_response: Optional[dict] = None) -> None:
        self._ensure_not_terminal_locked()
        self._enforce_transition(BatchState.SUBMITTED.value)
        if self.provider_request_id and self.provider_request_id != provider_request_id:
            raise ImmutableFieldError(
                f"provider_request_id is write-once: existing="
                f"{self.provider_request_id} new={provider_request_id}")
        self.provider_request_id = provider_request_id
        if provider_response is not None:
            self.provider_response = provider_response
        self.state = BatchState.SUBMITTED.value
        self.attempts += 1
        self.last_attempt_at = now_iso()
        self.next_attempt_at = None
        self.version += 1
        self._raise(_anchor_event("evidence.anchor.submitted",
                                     self.batch_id, self.version, {
            "batch_id": self.batch_id,
            "provider_id": self.provider_id,
            "provider_request_id": provider_request_id,
            "attempts": self.attempts,
        }))

    def mark_confirming(self) -> None:
        self._ensure_not_terminal_locked()
        self._enforce_transition(BatchState.CONFIRMING.value)
        self.state = BatchState.CONFIRMING.value
        self.version += 1

    def mark_confirmed(self, *, inclusion_proofs: dict,
                         provider_response: Optional[dict] = None) -> None:
        self._ensure_not_terminal_locked()
        self._enforce_transition(BatchState.CONFIRMED.value)
        if not inclusion_proofs:
            raise InvariantViolation("inclusion_proofs required for confirm")
        # write-once
        if self.inclusion_proofs is not None:
            raise ImmutableFieldError("inclusion_proofs already set")
        self.inclusion_proofs = inclusion_proofs
        if provider_response is not None:
            self.provider_response = provider_response
        self.state = BatchState.CONFIRMED.value
        self.confirmed_at = now_iso()
        self.version += 1
        self._raise(_anchor_event("evidence.anchor.confirmed",
                                     self.batch_id, self.version, {
            "batch_id": self.batch_id,
            "provider_id": self.provider_id,
            "merkle_root": self.merkle_root,
            "seal_ids": list(self.seal_ids),
            "confirmed_at": self.confirmed_at,
        }))

    def mark_failed(self, *, reason: str, next_attempt_at: Optional[str],
                      transient: bool = True) -> None:
        self._ensure_not_terminal_locked()
        self._enforce_transition(BatchState.FAILED.value)
        self.state = BatchState.FAILED.value
        self.next_attempt_at = next_attempt_at if transient else None
        self.version += 1
        self._raise(_anchor_event("evidence.anchor.failed",
                                     self.batch_id, self.version, {
            "batch_id": self.batch_id,
            "provider_id": self.provider_id,
            "reason": reason,
            "attempts": self.attempts,
            "transient": transient,
            "next_attempt_at": next_attempt_at,
        }))

    def mark_dead_letter(self, *, reason: str) -> None:
        self._ensure_not_terminal_locked()
        self._enforce_transition(BatchState.DEAD_LETTER.value)
        self.state = BatchState.DEAD_LETTER.value
        self.dlq_reason = reason
        self.next_attempt_at = None
        self.version += 1
        self._raise(_anchor_event("evidence.anchor.failed",
                                     self.batch_id, self.version, {
            "batch_id": self.batch_id,
            "provider_id": self.provider_id,
            "reason": reason,
            "attempts": self.attempts,
            "terminal": True,
        }))

    def mark_replay_initiated(self, *, new_batch_id: str) -> None:
        """The original DLQ row receives a one-time marker pointing at
        the replacement batch. The original state stays in dead_letter
        forever; only ``replayed_to`` metadata is appended (write-once)."""
        if self.state != BatchState.DEAD_LETTER.value:
            raise TransitionError(
                f"replay requires DEAD_LETTER; current={self.state}")
        if self.provider_response is None:
            self.provider_response = {}
        if "replayed_to" in self.provider_response:
            raise ImmutableFieldError("replayed_to already set")
        self.provider_response = {**self.provider_response,
                                    "replayed_to": new_batch_id}
        self.version += 1
        self._raise(_anchor_event("evidence.anchor.replayed",
                                     self.batch_id, self.version, {
            "batch_id": self.batch_id,
            "provider_id": self.provider_id,
            "replayed_to": new_batch_id,
        }))

    def to_state(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__
                if not k.startswith("_")}


# ---- AnchorAttempt (append-only chain entry) ----------------------------

def new_attempt_id() -> str:
    return "att_" + uuid.uuid4().hex


@dataclass(frozen=True)
class AnchorAttempt:
    attempt_id: str
    batch_id: str
    attempt_no: int
    started_at: str
    completed_at: Optional[str]
    outcome: str   # 'submitted' | 'confirming' | 'confirmed' | 'failed_transient' | 'failed_permanent'
    error_summary: Optional[str]
    provider_response_snapshot: Optional[dict]
    seq: int
    prev_hash: Optional[str]
    entry_hash: str

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name)
                 for f in self.__dataclass_fields__.values()}
