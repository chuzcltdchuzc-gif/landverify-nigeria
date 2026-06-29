# Phase 3 — Domain Map, Port Contracts, Event Catalog Draft

_Companion to `PHASE3_SPEC.md` and ADR-0003 / 0004 / 0005 / 0006._
_Blueprint output; no implementation code lands until Phase 3.0 sign-off._

## 1. Domain map

```text
backend/contexts/evidence/
├── domain/
│   ├── value_objects.py        # EvidenceId, SealId, HoldId, AnchorBatchId,
│   │                           # ContentHash, MediaType, StorageLocator,
│   │                           # EncryptionEnvelope, EvidenceKind,
│   │                           # EvidenceStatus, SealStatus, AnchorState,
│   │                           # RemediationState, Origin (re-uses Registry pattern)
│   ├── invariants.py           # ImmutableFieldError, SealedItemError,
│   │                           # HashMismatchError, WormViolationError,
│   │                           # LegalHoldViolation, RemediationStateError
│   ├── events.py               # 17 immutable domain events (see §3)
│   ├── evidence_item.py        # EvidenceItem aggregate root
│   ├── seal.py                 # Seal aggregate root (immutable manifest)
│   ├── legal_hold.py           # LegalHold aggregate root
│   ├── anchor_batch.py         # AnchorBatch aggregate root (saga state)
│   ├── remediation.py          # RemediationRequest aggregate (saga state)
│   └── chain.py                # Append-only chain helpers (sha256(prev || canon(entry)))
├── ports/
│   ├── repository.py           # EvidenceItemRepo, SealRepo, LegalHoldRepo,
│   │                           # AnchorBatchRepo, RemediationRepo
│   ├── storage.py              # StoragePort (multipart, WORM, signed URL, move)
│   ├── encryption.py           # EncryptionPort (envelope encrypt/decrypt, residency)
│   ├── anchor.py               # AnchorPort (request/confirm/inclusion-proof)
│   ├── signed_url.py           # SignedUrlPort (issue + sync audit)
│   └── specifications.py       # ByTenant, ByRegistry, ByStatus, ByHold, …
├── adapters/
│   ├── mongo_evidence_repository.py   # All five repositories in one module
│   ├── fs_worm_storage.py             # LocalFs WORM (dev)
│   ├── r2_storage.py                  # Cloudflare R2 (production)
│   ├── software_kms.py                # Per-tenant DEK + per-country master
│   ├── ctlog_anchor.py                # Internal CT log
│   ├── ots_anchor.py                  # OpenTimestamps
│   ├── signed_url_motor.py            # Generates + audits short-lived URLs
│   └── chain_logs.py                  # Append-only writer for timeline/locks/integrity/custody
├── application/
│   ├── evidence_service.py            # Commands: initiate, complete, verify, seal,
│   │                                  # place_hold, lift_hold, set_retention, archive
│   ├── anchor_saga.py                 # State machine for the anchor saga
│   ├── remediation_saga.py            # Verify-then-cutover state machine
│   ├── legal_hold_service.py
│   ├── orphan_reconciliation.py
│   └── exporters/
│       └── court_export.py            # Produces the export bundle (§3.5*)
├── api/
│   ├── dtos.py                        # Per-role Pydantic models (extra=forbid)
│   ├── router.py                      # FastAPI router /api/v1/evidence/*
│   └── streaming.py                   # Multipart streaming helpers
├── jobs/
│   ├── anchor_batcher.py              # Cron: scoop sealed items into batches
│   ├── anchor_confirmer.py            # Cron: poll provider, advance saga
│   ├── orphan_worker.py               # Cron: storage ↔ aggregate reconciliation
│   ├── retention_sweeper.py           # Cron: purge expired + not-held items
│   └── ctlog_checkpointer.py          # Cron: append to internal CT log + publish head
└── authorization.py                   # ~16 PDP policies
```

Collections:

| Collection                       | Purpose                                                |
| -------------------------------- | ------------------------------------------------------ |
| `evidence_items`                 | EvidenceItem aggregate                                 |
| `evidence_seals`                 | Seal aggregate                                         |
| `evidence_holds`                 | LegalHold aggregate                                    |
| `evidence_anchor_batches`        | AnchorBatch saga state                                 |
| `evidence_anchor_attempts`       | One row per saga attempt                               |
| `evidence_remediation_sagas`     | RemediationSaga state                                  |
| `evidence_timeline`              | Append-only operator-visible events                    |
| `evidence_locks`                 | WORM lock events                                       |
| `evidence_integrity`             | Hash claim/computation/mismatch events                 |
| `evidence_custody`               | Chain-of-custody — uploads, downloads, signed-URL audit |
| `evidence_signed_url_audit`      | Every issued URL (hashed, never plaintext)             |
| `evidence_orphans`               | Quarantined unmodeled storage objects                  |
| `evidence_ctlog_tree`            | Internal CT-log leaves                                 |
| `evidence_ctlog_checkpoints`     | Signed tree heads (publishable)                        |
| `evidence_tenant_deks`           | Per-tenant DEK envelopes                               |
| `evidence_country_masters`       | Per-country master keys (never leave country)          |

## 2. Port contracts (Python Protocols)

### 2.1 `StoragePort`

```python
class StoragePort(Protocol):
    provider_id: str  # "local_fs_worm" | "r2"

    async def initiate_multipart(self, *, key: str, media_type: str,
                                 max_size: int) -> MultipartHandle: ...
    async def upload_part(self, handle: MultipartHandle, part_no: int,
                          stream) -> PartReceipt: ...
    async def complete_multipart(self, handle: MultipartHandle,
                                 parts: list[PartReceipt]) -> StoredObject: ...
    async def abort_multipart(self, handle: MultipartHandle) -> None: ...

    async def open_for_streaming_hash(self, key: str) -> AsyncIterator[bytes]: ...

    async def issue_signed_url(self, key: str, *, ttl_seconds: int,
                                audit_ctx: SignedUrlAuditCtx) -> str: ...

    # WORM
    async def apply_object_lock(self, key: str, *, retention_until: datetime,
                                 mode: str = "compliance") -> None: ...
    async def extend_object_lock(self, key: str, *,
                                  retention_until: datetime) -> None: ...
    async def lock_status(self, key: str) -> ObjectLockStatus: ...

    # Remediation only — never expose to application logic outside the saga
    async def move(self, src_key: str, dst_key: str, *,
                    verify_callback: Callable[[bytes], None]) -> None: ...
```

### 2.2 `EncryptionPort`

```python
class EncryptionPort(Protocol):
    kms_id: str  # "software_kms_v1"

    async def issue_tenant_dek(self, *, tenant_id: str,
                                country: str) -> TenantDek: ...
    async def encrypt_stream(self, *, dek: TenantDek,
                              plaintext: AsyncIterator[bytes]
                              ) -> AsyncIterator[bytes]: ...
    async def decrypt_stream(self, *, envelope: EncryptionEnvelope,
                              ciphertext: AsyncIterator[bytes]
                              ) -> AsyncIterator[bytes]: ...
```

### 2.3 `AnchorPort`

```python
class AnchorPort(Protocol):
    provider_id: str  # "ctlog_internal" | "ots_v1"

    async def request_anchor(self, *, batch_id: str,
                              root: str) -> AnchorRequest: ...
    async def poll_confirmation(self,
                                 request: AnchorRequest) -> AnchorState: ...
    async def fetch_inclusion_proof(self, request: AnchorRequest,
                                     leaf_hash: str) -> InclusionProof: ...
```

### 2.4 `SignedUrlPort`

```python
class SignedUrlPort(Protocol):
    async def issue(self, *, key: str, ttl_seconds: int,
                     principal_id: str, action: str,
                     evidence_id: str) -> SignedUrl: ...
```

Synchronously writes to `evidence_signed_url_audit` before returning.

## 3. Event catalog (draft, additive for v1.2.0)

Same envelope shape as Phase 1 / Phase 2 events. Every event payload
carries `registry_id` so downstream contexts can fan out per LandVault.

| Event                                          | Aggregate     | Payload keys (highlights)                                                                                          |
| ---------------------------------------------- | ------------- | ------------------------------------------------------------------------------------------------------------------ |
| `evidence.item.uploaded.v1`                    | EvidenceItem  | `evidence_id, registry_id, kind, size_bytes, storage_provider`                                                     |
| `evidence.item.hash_verified.v1`               | EvidenceItem  | `evidence_id, registry_id, server_hash, hash_algorithm`                                                            |
| `evidence.item.hash_mismatch.v1`               | EvidenceItem  | `evidence_id, registry_id, client_hash_claim, server_hash, reason`                                                 |
| `evidence.item.archived_replaced.v1`           | EvidenceItem  | `evidence_id, registry_id, replaced_by`                                                                            |
| `evidence.seal.created.v1`                     | Seal          | `seal_id, registry_id, evidence_ids, merkle_root, manifest_hash`                                                   |
| `evidence.seal.worm_applied.v1`                | Seal          | `seal_id, registry_id, items: [{evidence_id, lock_until}]`                                                         |
| `evidence.legal_hold.placed.v1`                | LegalHold     | `hold_id, scope, registry_id?, reason, issued_by`                                                                  |
| `evidence.legal_hold.lifted.v1`                | LegalHold     | `hold_id, lifted_by, reason`                                                                                       |
| `evidence.anchor.batched.v1`                   | AnchorBatch   | `batch_id, provider_ids, root, seal_ids`                                                                           |
| `evidence.anchor.submitted.v1`                 | AnchorBatch   | `batch_id, provider_id, attempt`                                                                                   |
| `evidence.anchor.confirmed.v1`                 | AnchorBatch   | `batch_id, provider_id, attempt, inclusion_proofs_by_seal`                                                         |
| `evidence.anchor.failed.v1`                    | AnchorBatch   | `batch_id, provider_id, attempts, final_state, error_summary`                                                      |
| `evidence.remediation.committed.v1`            | EvidenceItem  | `saga_id, old_evidence_id, new_evidence_id, registry_id`                                                           |
| `evidence.remediation.failed.v1`               | EvidenceItem  | `saga_id, evidence_id, registry_id, failure_state, error_summary`                                                  |
| `evidence.orphan.detected.v1`                  | OrphanRecord  | `orphan_id, tenant_id, country, storage_provider, key, observed_at`                                                |
| `evidence.signed_url.issued.v1`                | EvidenceItem  | `evidence_id, principal_id, action, ttl_seconds, url_sha256`                                                       |
| `evidence.exported.v1`                         | Seal          | `seal_id, registry_id, bundle_sha256, exported_by`                                                                 |

(17 events. Versions all start at 1. New event types are added in
later minor bumps; breaking changes to an existing event mint a new
type name per the envelope policy.)

## 4. New PDP policies (16 actions)

To be registered at startup alongside Identity and Registry policies:

```text
evidence.item.upload.initiate                   priority 200
evidence.item.upload.complete                   priority 201
evidence.item.read.signed_url                   priority 210
evidence.item.verify                            priority 220
evidence.seal.create                            priority 230
evidence.seal.apply_worm                        priority 231
evidence.seal.read                              priority 240
evidence.anchor.batch.run                       priority 250
evidence.anchor.batch.replay_dlq                priority 251
evidence.anchor.batch.read                      priority 252
evidence.legal_hold.place                       priority 260
evidence.legal_hold.lift                        priority 261
evidence.remediate                              priority 270
evidence.export                                 priority 280
evidence.item.reserve                           priority 290    # offline-first
evidence.orphan.resolve                         priority 295
```

Each maps to the role tier in `PHASE3_SPEC.md §3` and consults the
ExecutionContext for tenant/country scope.

## 5. API surface summary (additive, all `/api/v1/evidence/*`)

| Method | Path                                                       | Purpose                                  |
| ------ | ---------------------------------------------------------- | ---------------------------------------- |
| POST   | `/items`                                                   | Initiate (returns id + signed parts)     |
| PUT    | `/items/{id}/parts/{part_no}`                              | Stream a part                            |
| POST   | `/items/{id}/complete`                                     | Finalize multipart                       |
| POST   | `/items/{id}/verify`                                       | Read-back + re-hash                      |
| GET    | `/items/{id}`                                              | Read metadata (role-projected)           |
| GET    | `/items/{id}/signed-url`                                   | Issue short-lived URL                    |
| POST   | `/items/reserve`                                           | Pre-mint ids for offline-first           |
| POST   | `/items/{id}/sync`                                         | Offline-first sync entry point           |
| POST   | `/items/{id}/remediate`                                    | Start verify-then-cutover                |
| POST   | `/seals`                                                   | Create a seal manifest                   |
| POST   | `/seals/{id}/apply-worm`                                   | Trigger Object Lock on referenced items  |
| GET    | `/seals/{id}`                                              | Read manifest + inclusion proofs          |
| POST   | `/seals/{id}/export`                                       | Produce court-export bundle              |
| POST   | `/legal-holds`                                             | Place                                    |
| POST   | `/legal-holds/{id}/lift`                                   | Lift                                     |
| GET    | `/legal-holds`                                             | List                                     |
| POST   | `/anchor-batches/{id}/replay`                              | Replay DLQ                               |
| GET    | `/anchor-batches/{id}`                                     | Saga state + attempts                    |
| GET    | `/anchor-batches/by-seal/{seal_id}`                        | Inclusion proof bundle                   |

## 6. Test plan (acceptance matrix maps 1:1 to PHASE3_SPEC.md §5)

| Test file                                            | Cases (target) | Notes                                                |
| ---------------------------------------------------- | -------------- | ---------------------------------------------------- |
| `test_evidence_invariants.py`                        | ~25            | Pure-Python aggregate tests                          |
| `test_evidence_hashing.py`                           | ~10            | NIST vectors + claim/server-verified flow            |
| `test_storage_worm_local_fs.py`                      | ~8             | Adapter contract tests                               |
| `test_storage_worm_r2.py`                            | ~6             | Skipped unless R2 creds present                      |
| `test_encryption_envelope.py`                        | ~8             | Round-trip + cross-tenant isolation                  |
| `test_signed_url_audit.py`                           | ~4             | Audit-before-return guarantee                        |
| `test_anchor_saga.py`                                | ~12            | Happy path + DLQ + replay                            |
| `test_legal_hold.py`                                 | ~6             | Retention precedence + lift authorization            |
| `test_remediation_saga.py`                           | ~10            | Crash recovery + reverify-fail safety                |
| `test_orphan_worker.py`                              | ~4             | Detection + quarantine                                |
| `test_evidence_api.py`                               | ~20            | E2E authz matrix + tenant isolation + projection     |
| `test_offline_capture.py`                            | ~6             | Reserve + sync + idempotency                         |
| `test_court_export_bundle.py`                        | ~8             | Bundle structure + offline verifier PASS             |
| `test_contract_freeze.py`                            | refreshed      | Drift gate green at 1.2.0                            |

Total target: ~125 new tests on top of the existing 130+.

## 7. Implementation order (after sign-off)

3.1 → 3.2 (LocalFs only, R2 deferred) → 3.3 → 3.4 → 3.5 → 3.6 → 3.7 →
3.8 (CT-log only first, OTS second) → 3.9 → 3.10 → 3.5* (export +
offline verifier).

R2 storage adapter and OTS anchor adapter ship as additive
implementations of the same ports — no new domain code, no contract
bump.

## 8. Open questions for sign-off

* **Encryption "residency" enforcement** — current draft refuses
  cross-country DEK unwrap with super_admin bypass logged. Acceptable?
* **CT-log checkpoint publishing target** — for production, do we
  publish daily heads to R2 public, IPFS, or both?
* **Saga schedule cadence** — default polling: anchor batcher 60s,
  confirmer backoff `[10s, 60s, 5min, 1h, 6h, 24h]`. Tunable?
* **Offline-first reservation batch size** — default 50 ids per
  reservation. Acceptable?
