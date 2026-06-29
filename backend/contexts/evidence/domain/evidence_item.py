"""EvidenceItem — canonical aggregate root for evidentiary records.

Phase 3.4 / 3.5 directive:

* The aggregate owns the lifecycle of one evidence binary's metadata.
* Binaries NEVER live in Mongo — they live behind the StoragePort.
* Identity, registry reference, tenant, country, created_at, origin,
  storage_locator (after upload finalization), server_hash (after
  verification) are IMMUTABLE.
* Status follows a strict one-way FSM:
      pending_upload → pending_verification → verified → sealed → archived_replaced
* Sealing is the WORM gate: once sealed, the only legal commands are
  ``archive_replaced(replaced_by=...)`` from a remediation cutover
  (Phase 3.3 saga). Every other mutation raises ``SealedItemError``.
* Server hashes are authoritative. Client hashes are recorded as
  "claims" only — a mismatch is a hard 409 + integrity event.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from contexts.evidence.domain.events import (
    DomainEvent,
    item_archived_replaced,
    item_hash_mismatch,
    item_hash_verified,
    item_uploaded,
    signed_url_issued,
)
from contexts.evidence.domain.invariants import (
    HashMismatchError,
    ImmutableFieldError,
    InvariantViolation,
    SealedItemError,
    TransitionError,
)
from contexts.evidence.domain.value_objects import (
    SEALED_LIKE_STATUSES,
    ContentHash,
    EvidenceKind,
    EvidenceStatus,
    Origin,
    new_evidence_id,
    now_iso,
)

SCHEMA_VERSION_CURRENT = 1

# Immutable field names — guard against silent mutation paths.
IMMUTABLE_FIELDS = frozenset({
    "evidence_id", "registry_id", "tenant_id", "country_code",
    "created_at", "created_by", "origin", "kind",
})


@dataclass
class EvidenceItem:
    """Aggregate root for one evidentiary record."""

    # ---- Identity (immutable) ------------------------------------------
    evidence_id: str
    registry_id: str
    tenant_id: str
    country_code: str
    kind: str  # EvidenceKind value
    created_at: str
    created_by: str
    origin: dict

    # ---- Lifecycle -----------------------------------------------------
    status: str = EvidenceStatus.PENDING_UPLOAD.value
    version: int = 1
    schema_version: int = SCHEMA_VERSION_CURRENT

    # ---- Upload metadata (set as bytes flow through StoragePort) ------
    media_type: Optional[str] = None
    size_bytes: Optional[int] = None
    storage_provider: Optional[str] = None
    storage_locator: Optional[str] = None  # StorageObjectKey.as_str()
    upload_id: Optional[str] = None  # opaque multipart session id

    # ---- Hash discipline (Phase 3.3 / ADR-0004) ------------------------
    client_hash_claim: Optional[str] = None
    server_hash_streamed: Optional[str] = None  # streamed-during-write
    server_hash: Optional[str] = None           # independent read-back
    hash_algorithm: str = "SHA-256"
    hash_verified: bool = False

    # ---- Phase 3.5 sealing -----------------------------------------------
    seal_id: Optional[str] = None  # write-once
    sealed_at: Optional[str] = None
    retention_until: Optional[str] = None

    # ---- Phase 3.3 remediation supersession ----------------------------
    replaced_by: Optional[str] = None
    replaced_at: Optional[str] = None

    # ---- Audit -----------------------------------------------------------
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None

    # ---- Transient (drained by application service) -------------------
    _events: list[DomainEvent] = field(default_factory=list,
                                        repr=False, compare=False)

    # ---- Factory ---------------------------------------------------------

    @classmethod
    def create(
        cls, *, registry_id: str, tenant_id: str, country_code: str,
        kind: str, created_by: str, origin: Origin,
        media_type: Optional[str] = None,
        client_hash_claim: Optional[str] = None,
        evidence_id: Optional[str] = None,
    ) -> "EvidenceItem":
        if kind not in {k.value for k in EvidenceKind}:
            raise InvariantViolation(f"invalid kind: {kind!r}")
        if not registry_id:
            raise InvariantViolation("registry_id is required")
        if not tenant_id:
            raise InvariantViolation("tenant_id is required")
        if not country_code:
            raise InvariantViolation("country_code is required")
        if client_hash_claim is not None:
            # Validate shape now; the equality check happens at verify.
            ContentHash(value=client_hash_claim)

        return cls(
            evidence_id=evidence_id or new_evidence_id(),
            registry_id=registry_id, tenant_id=tenant_id,
            country_code=country_code, kind=kind,
            created_at=now_iso(), created_by=created_by,
            origin=origin.to_dict(),
            media_type=media_type,
            client_hash_claim=client_hash_claim,
        )

    # ---- Reconstitution from storage -----------------------------------

    @classmethod
    def from_state(cls, state: dict) -> "EvidenceItem":
        """Hydrate from a persisted document. NO events raised."""
        clean = {k: v for k, v in state.items()
                 if k in cls.__dataclass_fields__ and not k.startswith("_")}
        agg = cls(**clean)
        agg._events.clear()
        return agg

    # ---- Mutation guards ------------------------------------------------

    def _ensure_writable(self) -> None:
        if self.status in SEALED_LIKE_STATUSES:
            raise SealedItemError(
                f"evidence {self.evidence_id} is sealed/archived; "
                f"WORM lockdown in effect"
            )

    def _bump(self, actor: Optional[str]) -> None:
        self.version += 1
        self.updated_at = now_iso()
        self.updated_by = actor

    def _raise(self, ev: DomainEvent) -> None:
        self._events.append(ev)

    def pull_events(self) -> list[DomainEvent]:
        out = list(self._events)
        self._events.clear()
        return out

    # ---- Commands -------------------------------------------------------

    def attach_upload_session(self, *, upload_id: str,
                              media_type: str) -> None:
        self._ensure_writable()
        if self.status != EvidenceStatus.PENDING_UPLOAD.value:
            raise TransitionError(
                f"attach_upload_session requires PENDING_UPLOAD; "
                f"current={self.status}"
            )
        self.upload_id = upload_id
        self.media_type = media_type

    def mark_uploaded(self, *, storage_locator: str, storage_provider: str,
                      size_bytes: int, streamed_sha256: str,
                      media_type: str, actor: str) -> None:
        """Multipart was finalized — storage object exists."""
        self._ensure_writable()
        if self.status != EvidenceStatus.PENDING_UPLOAD.value:
            raise TransitionError(
                f"mark_uploaded requires PENDING_UPLOAD; current={self.status}"
            )
        ContentHash(value=streamed_sha256)  # validate shape
        if size_bytes < 0:
            raise InvariantViolation("size_bytes must be >= 0")
        self.storage_locator = storage_locator
        self.storage_provider = storage_provider
        self.size_bytes = size_bytes
        self.server_hash_streamed = streamed_sha256
        self.media_type = media_type
        self.status = EvidenceStatus.PENDING_VERIFICATION.value
        self._bump(actor)
        self._raise(item_uploaded(
            evidence_id=self.evidence_id, version=self.version,
            payload={
                "evidence_id": self.evidence_id,
                "registry_id": self.registry_id,
                "kind": self.kind,
                "size_bytes": self.size_bytes,
                "media_type": self.media_type,
                "storage_provider": self.storage_provider,
            },
        ))

    def verify_hash(self, *, readback_sha256: str, actor: str) -> None:
        """Independent server-side read-back hash. Must equal the
        streamed hash AND any client claim. Mismatch → integrity event +
        HashMismatchError; the item rolls back to PENDING_UPLOAD so the
        client can re-upload."""
        self._ensure_writable()
        if self.status != EvidenceStatus.PENDING_VERIFICATION.value:
            raise TransitionError(
                f"verify_hash requires PENDING_VERIFICATION; "
                f"current={self.status}"
            )
        ContentHash(value=readback_sha256)
        if (self.server_hash_streamed and
                readback_sha256 != self.server_hash_streamed):
            self._raise(item_hash_mismatch(
                evidence_id=self.evidence_id, version=self.version,
                payload={
                    "evidence_id": self.evidence_id,
                    "registry_id": self.registry_id,
                    "reason": "readback_streamed_mismatch",
                    "server_hash_streamed": self.server_hash_streamed,
                    "readback_sha256": readback_sha256,
                },
            ))
            # Roll back so a re-upload is possible.
            self.status = EvidenceStatus.PENDING_UPLOAD.value
            self.server_hash_streamed = None
            self.storage_locator = None
            self.storage_provider = None
            self.size_bytes = None
            self._bump(actor)
            raise HashMismatchError(
                "server-side read-back hash does not match streamed hash"
            )
        if (self.client_hash_claim and
                self.client_hash_claim != readback_sha256):
            self._raise(item_hash_mismatch(
                evidence_id=self.evidence_id, version=self.version,
                payload={
                    "evidence_id": self.evidence_id,
                    "registry_id": self.registry_id,
                    "reason": "client_claim_mismatch",
                    "client_hash_claim": self.client_hash_claim,
                    "server_hash": readback_sha256,
                },
            ))
            self.status = EvidenceStatus.PENDING_UPLOAD.value
            self.server_hash_streamed = None
            self.storage_locator = None
            self.storage_provider = None
            self.size_bytes = None
            self._bump(actor)
            raise HashMismatchError(
                "client_hash_claim does not match server-computed hash"
            )
        self.server_hash = readback_sha256
        self.hash_verified = True
        self.status = EvidenceStatus.VERIFIED.value
        self._bump(actor)
        self._raise(item_hash_verified(
            evidence_id=self.evidence_id, version=self.version,
            payload={
                "evidence_id": self.evidence_id,
                "registry_id": self.registry_id,
                "server_hash": self.server_hash,
                "hash_algorithm": self.hash_algorithm,
            },
        ))

    def attach_to_seal(self, *, seal_id: str, actor: str,
                       retention_until: Optional[str] = None) -> None:
        """Called by the Seal aggregate during seal creation. Idempotent."""
        if self.seal_id == seal_id:
            return
        if self.seal_id is not None:
            raise ImmutableFieldError(
                f"evidence {self.evidence_id} already sealed by {self.seal_id}"
            )
        if self.status != EvidenceStatus.VERIFIED.value:
            raise TransitionError(
                f"attach_to_seal requires VERIFIED; current={self.status}"
            )
        self.seal_id = seal_id
        self.sealed_at = now_iso()
        self.retention_until = retention_until
        self.status = EvidenceStatus.SEALED.value
        self._bump(actor)

    def archive_replaced(self, *, replaced_by: str, actor: str,
                          reason: str) -> None:
        """Phase 3.3 remediation cutover — the ONLY legal exit from
        SEALED. Raises an `archived_replaced` event so downstream
        consumers can re-point references."""
        if self.status == EvidenceStatus.ARCHIVED_REPLACED.value:
            raise InvariantViolation("already archived_replaced")
        self.replaced_by = replaced_by
        self.replaced_at = now_iso()
        self.status = EvidenceStatus.ARCHIVED_REPLACED.value
        self._bump(actor)
        self._raise(item_archived_replaced(
            evidence_id=self.evidence_id, version=self.version,
            payload={
                "evidence_id": self.evidence_id,
                "registry_id": self.registry_id,
                "replaced_by": replaced_by,
                "reason": reason,
            },
        ))

    def record_signed_url_issuance(self, *, principal_id: str, action: str,
                                    ttl_seconds: int, url_sha256: str) -> None:
        """Emit a domain event for audit fan-out. No state mutation
        (the audit row is written by the SignedUrlPort adapter itself)."""
        self._raise(signed_url_issued(
            evidence_id=self.evidence_id, version=self.version,
            payload={
                "evidence_id": self.evidence_id,
                "registry_id": self.registry_id,
                "principal_id": principal_id,
                "action": action,
                "ttl_seconds": ttl_seconds,
                "url_sha256": url_sha256,
            },
        ))

    # ---- Concurrency control -------------------------------------------

    def check_expected_version(self, expected: Optional[int]) -> None:
        if expected is not None and expected != self.version:
            from contexts.evidence.domain.invariants import ConcurrencyConflict
            raise ConcurrencyConflict(
                f"expected version {expected}, found {self.version}"
            )

    # ---- Persistence projection ----------------------------------------

    def to_state(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__
                if not k.startswith("_")}
