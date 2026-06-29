"""Seal — Phase 3.5 immutable manifest aggregate.

A Seal groups one or more verified ``EvidenceItem``s into a single,
tamper-evident envelope. Once constructed, every field except
``status``, ``anchor_batch_id``, and the version counters is FROZEN.
``status`` advances through a strict FSM:

    created → worm_applied → archived

Sealing IS the WORM gate. Once a seal moves to ``worm_applied`` the
StoragePort Object-Lock is active for every referenced evidence item;
the seal can never be deleted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from contexts.evidence.domain.events import (
    DomainEvent,
    seal_archived,
    seal_created,
    seal_worm_applied,
)
from contexts.evidence.domain.invariants import (
    ImmutableFieldError,
    InvariantViolation,
    TransitionError,
)
from contexts.evidence.domain.value_objects import (
    SealStatus,
    canonical_json_hash,
    compute_merkle_root,
    new_seal_id,
    now_iso,
)

SCHEMA_VERSION_CURRENT = 1


@dataclass
class Seal:
    """Aggregate root for an immutable evidence manifest."""

    # ---- Identity + scope (immutable) ----------------------------------
    seal_id: str
    registry_id: str
    tenant_id: str
    country_code: str

    # ---- Manifest (immutable) ------------------------------------------
    evidence_ids: tuple[str, ...]
    merkle_root: str
    manifest: dict
    manifest_hash: str
    leaf_hashes: tuple[str, ...]

    # ---- Audit ---------------------------------------------------------
    created_at: str
    created_by: str

    # ---- Lifecycle -----------------------------------------------------
    status: str = SealStatus.CREATED.value
    version: int = 1
    schema_version: int = SCHEMA_VERSION_CURRENT
    anchor_batch_id: Optional[str] = None  # write-once (Phase 3.6 territory)
    worm_applied_at: Optional[str] = None
    retention_until: Optional[str] = None
    archived_at: Optional[str] = None

    # ---- Transient -----------------------------------------------------
    _events: list[DomainEvent] = field(default_factory=list,
                                        repr=False, compare=False)

    # ---- Factory --------------------------------------------------------

    @classmethod
    def create(cls, *, registry_id: str, tenant_id: str, country_code: str,
               items: list[dict], created_by: str,
               retention_until: Optional[str] = None,
               seal_id: Optional[str] = None) -> "Seal":
        """Construct a Seal from a list of VERIFIED evidence dicts.

        ``items`` must be the projection ``{evidence_id, server_hash,
        size_bytes, kind, media_type}`` for each evidence to be sealed.
        The factory enforces all manifest invariants.
        """
        if not items:
            raise InvariantViolation("seal requires at least one evidence item")
        seen_ids: set[str] = set()
        for it in items:
            for f in ("evidence_id", "server_hash", "size_bytes", "kind"):
                if it.get(f) is None:
                    raise InvariantViolation(f"item missing {f}: {it!r}")
            if it["evidence_id"] in seen_ids:
                raise InvariantViolation(
                    f"duplicate evidence in seal: {it['evidence_id']}"
                )
            seen_ids.add(it["evidence_id"])

        evidence_ids = tuple(it["evidence_id"] for it in items)
        leaf_hashes = tuple(it["server_hash"] for it in items)
        merkle_root = compute_merkle_root(list(leaf_hashes))
        # Canonical manifest — sorted-by-evidence_id list so the
        # manifest_hash is independent of selection order.
        sorted_items = sorted(items, key=lambda x: x["evidence_id"])
        sid = seal_id or new_seal_id()
        created_at = now_iso()
        manifest = {
            "seal_id": sid,
            "schema": SCHEMA_VERSION_CURRENT,
            "registry_id": registry_id,
            "tenant_id": tenant_id,
            "country_code": country_code,
            "created_at": created_at,
            "created_by": created_by,
            "merkle_root": merkle_root,
            "items": [{
                "evidence_id": it["evidence_id"],
                "server_hash": it["server_hash"],
                "hash_algorithm": "SHA-256",
                "size_bytes": int(it["size_bytes"]),
                "kind": it["kind"],
                "media_type": it.get("media_type"),
            } for it in sorted_items],
        }
        manifest_hash = canonical_json_hash(manifest)

        agg = cls(
            seal_id=sid,
            registry_id=registry_id, tenant_id=tenant_id,
            country_code=country_code,
            evidence_ids=evidence_ids,
            merkle_root=merkle_root,
            manifest=manifest,
            manifest_hash=manifest_hash,
            leaf_hashes=leaf_hashes,
            created_at=created_at,
            created_by=created_by,
            retention_until=retention_until,
        )
        agg._raise(seal_created(
            seal_id=sid, version=agg.version,
            payload={
                "seal_id": sid,
                "registry_id": registry_id,
                "evidence_ids": list(evidence_ids),
                "merkle_root": merkle_root,
                "manifest_hash": manifest_hash,
                "item_count": len(evidence_ids),
                "created_by": created_by,
            },
        ))
        return agg

    # ---- Reconstitution -------------------------------------------------

    @classmethod
    def from_state(cls, state: dict) -> "Seal":
        clean = {k: v for k, v in state.items()
                 if k in cls.__dataclass_fields__ and not k.startswith("_")}
        if isinstance(clean.get("evidence_ids"), list):
            clean["evidence_ids"] = tuple(clean["evidence_ids"])
        if isinstance(clean.get("leaf_hashes"), list):
            clean["leaf_hashes"] = tuple(clean["leaf_hashes"])
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

    def apply_worm(self, *, actor: str, lock_results: list[dict]) -> None:
        """Move from CREATED → WORM_APPLIED. The application service has
        already invoked ``StoragePort.apply_object_lock`` on each
        referenced item; ``lock_results`` records the per-item outcome.
        """
        if self.status == SealStatus.WORM_APPLIED.value:
            return  # idempotent
        if self.status != SealStatus.CREATED.value:
            raise TransitionError(
                f"apply_worm requires status=created; current={self.status}"
            )
        self.status = SealStatus.WORM_APPLIED.value
        self.worm_applied_at = now_iso()
        self.version += 1
        self._raise(seal_worm_applied(
            seal_id=self.seal_id, version=self.version,
            payload={
                "seal_id": self.seal_id,
                "registry_id": self.registry_id,
                "applied_by": actor,
                "item_count": len(self.evidence_ids),
                "items": lock_results,
                "retention_until": self.retention_until,
            },
        ))

    def attach_anchor_batch(self, *, batch_id: str) -> None:
        """Write-once link to a Phase 3.6 anchor batch."""
        if self.anchor_batch_id is not None:
            if self.anchor_batch_id == batch_id:
                return
            raise ImmutableFieldError(
                f"seal {self.seal_id} already attached to batch "
                f"{self.anchor_batch_id}"
            )
        self.anchor_batch_id = batch_id
        self.version += 1

    def archive(self, *, actor: str, reason: str) -> None:
        if self.status == SealStatus.ARCHIVED.value:
            raise InvariantViolation("seal already archived")
        self.status = SealStatus.ARCHIVED.value
        self.archived_at = now_iso()
        self.version += 1
        self._raise(seal_archived(
            seal_id=self.seal_id, version=self.version,
            payload={
                "seal_id": self.seal_id,
                "registry_id": self.registry_id,
                "actor": actor,
                "reason": reason,
            },
        ))

    # ---- Concurrency ----------------------------------------------------

    def check_expected_version(self, expected: Optional[int]) -> None:
        if expected is not None and expected != self.version:
            from contexts.evidence.domain.invariants import ConcurrencyConflict
            raise ConcurrencyConflict(
                f"expected version {expected}, found {self.version}"
            )

    # ---- Projection -----------------------------------------------------

    def to_state(self) -> dict:
        state = {k: getattr(self, k) for k in self.__dataclass_fields__
                 if not k.startswith("_")}
        # Tuples → lists for Mongo persistence (BSON has no tuple).
        state["evidence_ids"] = list(self.evidence_ids)
        state["leaf_hashes"] = list(self.leaf_hashes)
        return state
