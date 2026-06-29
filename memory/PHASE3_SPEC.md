# Aquasavannah LandVault — Phase 3 Definitive Delivery Specification

**Files & Evidence Bounded Context**

*Status*: **Blueprint (Phase 3.0) — pending explicit sign-off before any implementation code is written.*
*Contract bump target*: `1.1.0 → 1.2.0` (additive minor; new endpoints, schemas, events, security entries; nothing removed/renamed).
*Bounded context*: `backend/contexts/evidence/` — separate from Identity and Registry.
*Cross-context coupling*: **events only**. Evidence references `registry_id` but **never writes** Registry state.

---

## 0. Build sequence at a glance

| Step | Title                                    | Key deliverable                                                                                   | Acceptance gate                                                                                  |
| ---- | ---------------------------------------- | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| 3.0  | Blueprint (this document)                | 4 ADRs, domain map, port contracts, event catalog draft, this spec                                | Explicit operator sign-off                                                                       |
| 3.1  | Bounded-context skeleton                 | `contexts/evidence/` tree, `EvidenceItem` aggregate, repository + specs, registered policies      | Unit tests for invariants                                                                        |
| 3.2  | Storage port + WORM adapters             | `StoragePort` Protocol; **LocalFsWORM** adapter (dev); **R2** adapter (production-ready)          | Pluggable behind port; WORM contract tests                                                       |
| 3.3  | Multipart streaming upload + server hash | Streaming SHA-256 during upload; client hashes accepted as **claims only**; verify-before-persist | Integration test: tampered client hash rejected                                                  |
| 3.4  | Encryption port + Software KMS           | `EncryptionPort`; per-tenant DEK wrapped by per-country master; envelope-encrypted at rest        | Round-trip + cross-tenant key isolation tests                                                    |
| 3.5  | Seal manifest aggregate + WORM lockdown  | `Seal` aggregate; immutability invariants; storage object-lock activated on seal                  | Invariant tests + WORM enforcement test                                                          |
| 3.6  | Append-only timeline + locks + custody   | `evidence_timeline`, `evidence_locks`, `evidence_integrity`, `evidence_custody` collections       | Append-only contract test                                                                        |
| 3.7  | Signed-URL adapter + audit               | Short-lived URLs only; every issuance audited                                                     | URL-audit test                                                                                   |
| 3.8  | Anchor saga (CT-log first, OTS second)   | Merkle batch builder + saga (request/confirm/retry/DLQ); inclusion proofs                         | Saga state-machine test + DLQ recovery test                                                      |
| 3.9  | Legal Hold + retention precedence        | `LegalHold` aggregate; **Hold overrides retention** invariant                                     | Retention-vs-hold precedence test                                                                |
| 3.10 | Remediation saga + orphan worker         | Verify-then-cutover saga (move → read back → re-hash → match → record → null source)              | Failure-injection tests prove zero data loss                                                     |
| 3.5* | **Court export + offline verifier + offline-first capture** | Export bundle + standalone CLI verifier + offline-first sync spec                            | Independent verifier confirms a sealed-and-anchored bundle                                       |

The phase passes the Acceptance Review (and unlocks Phase 4) only when **every gate** above is green.

---

## 1. Architectural constraints (re-stated, binding)

These are non-negotiable and were re-confirmed in the directive:

* **Bounded context**: lives under `backend/contexts/evidence/`. Imports from `kernel/*` and reads `contexts/registry/` events via the outbox. **Never** imports Registry application code; **never** writes Registry collections.
* **Aggregate ownership of events** — only the aggregate root raises domain events; repositories are persistence-only; the application service publishes via the transactional outbox in the same Mongo session as the write.
* **Immutable once sealed** — a sealed evidence item or seal manifest cannot be mutated. Modifications go through the remediation saga (§ 3.10).
* **Private objects via short-lived signed URLs only** — no public bucket reads; every URL issuance is audited (§ 3.7).
* **No binaries in documents** — Mongo holds metadata + hashes + provenance; binaries live in the object store behind the storage port.
* **Append-only** — timeline, integrity log, lock log, custody log are insert-only with cryptographic chaining (§ 3.6).
* **Provider interfaces** — `StoragePort`, `EncryptionPort`, `AnchorPort`. Adapters are swappable; tests run against in-memory + LocalFs implementations.
* **Execution Context** for identity & scope — every request derives `tenant_id`, `country`, roles from the ExecutionContext; client-supplied tenant/country values are ignored.
* **Centralized authorization** via the PEP/PDP; new PDP policies registered at startup.
* **Repositories with Specifications** — no business logic in adapters.
* **Versioned contracts** — bump to `1.2.0`; CHANGELOG + ADRs + regenerated SHA256 fingerprints + drift gate kept green.
* **Tenant + country scoping** — non-negotiable; enforced by repository defense-in-depth identical to Registry.

---

## 2. Step-by-step delivery

Each step ships in this order: **(a) blueprint snippet**, **(b) implementation**, **(c) tests**, **(d) regenerate contracts**, **(e) regression**.

### 3.1 — Bounded-context skeleton + `EvidenceItem` aggregate

* Directory:

  ```text
  backend/contexts/evidence/
  ├── domain/         {value_objects, invariants, events, evidence_item, seal, legal_hold, anchor_batch}
  ├── ports/          {repository, storage, encryption, anchor, signed_url, specifications}
  ├── adapters/       {mongo_evidence_repository, fs_worm_storage, r2_storage, software_kms,
  │                    ctlog_anchor, ots_anchor, signed_url_motor}
  ├── application/    {evidence_service, anchor_saga, remediation_saga, legal_hold_service,
  │                    orphan_reconciliation}
  ├── api/            {dtos, router}
  ├── jobs/           {anchor_batcher, anchor_confirmer, orphan_worker}
  └── authorization.py
  ```

* `EvidenceItem` aggregate fields (Mongo `evidence_items`):

  | Field                  | Type                                                   | Notes                                                                                |
  | ---------------------- | ------------------------------------------------------ | ------------------------------------------------------------------------------------ |
  | `evidence_id`          | str, immutable, `evd_<32hex>`                          | Aggregate identity                                                                   |
  | `registry_id`          | str, immutable                                         | Reference to LandVault; foreign — never written by Evidence                          |
  | `tenant_id`            | str, immutable                                         | From ExecutionContext                                                                |
  | `country_code`         | str, immutable                                         | From ExecutionContext                                                                |
  | `kind`                 | enum                                                   | `document` \| `photo` \| `video` \| `audio` \| `signed_doc` \| `field_capture_bundle` |
  | `media_type`           | str                                                    | RFC 2045                                                                             |
  | `size_bytes`           | int                                                    | ≥ 0                                                                                  |
  | `client_hash_claim`    | str?                                                   | Optional client-supplied SHA-256 — **claim only**                                    |
  | `server_hash`          | str?                                                   | SHA-256 computed during streaming upload                                              |
  | `hash_algorithm`       | str                                                    | Always `"SHA-256"` for v1                                                            |
  | `hash_verified`        | bool                                                   | Server-only field; true after server-side computation                                 |
  | `storage_locator`      | str                                                    | Opaque object key returned by `StoragePort`                                          |
  | `storage_provider`     | enum                                                   | `local_fs_worm` \| `r2`                                                              |
  | `encryption_envelope`  | object?                                                | `{kms: "software_kms_v1", tenant_dek_id, country_master_kid, nonce, wrap_alg}`      |
  | `status`               | enum                                                   | `pending_upload` → `pending_verification` → `verified` → `sealed` → `archived`        |
  | `seal_id`              | str?                                                   | Set when included in a Seal aggregate                                                |
  | `anchor_batch_id`      | str?                                                   | Set when included in an AnchorBatch                                                  |
  | `legal_hold_ids`       | list[str]                                              | Active holds suppressing retention                                                   |
  | `retention_expires_at` | str ISO8601?                                           | NULL means "no retention policy yet"                                                 |
  | `origin`               | object                                                 | `{source, source_id, import_batch}` — matches Registry pattern                       |
  | `created_at`           | str ISO8601, immutable                                 |                                                                                      |
  | `created_by`           | str, immutable                                         | Principal id                                                                         |
  | `updated_at`/`updated_by` | str?/str?                                           | Mutated by aggregate methods only                                                    |
  | `version`              | int                                                    | Monotonic                                                                            |
  | `schema_version`       | int                                                    | Starts at 1                                                                          |
  | `deleted_at`           | str?                                                   | One-way (archive only; sealed items can never be deleted, only legally remediated)   |

* **Invariants enforced inside the aggregate**:
  * `evidence_id`/`registry_id`/`tenant_id`/`country_code`/`created_at`/`origin.*` immutable.
  * `version`/`schema_version` monotonic.
  * `sealed` items: only `legal_hold_ids` and `retention_expires_at` may be touched, and only via dedicated `place_hold()` / `lift_hold()` / `remediate()` commands.
  * Transition graph: `pending_upload → pending_verification → verified → sealed` is one-way; the only way to leave `sealed` is the remediation saga's atomic cutover, which produces a *new* aggregate (the old one becomes `archived_replaced` and its `replaced_by` field is set).
  * `seal_id` and `anchor_batch_id` write-once.

* **Commands**: `upload_initiated`, `mark_uploaded`, `record_server_hash`, `verify_hash`, `attach_to_seal`, `attach_to_anchor_batch`, `place_hold`, `lift_hold`, `set_retention`, `mark_remediated`, `archive`.

### 3.2 — Storage port + WORM adapters

* `StoragePort` Protocol:

  ```python
  class StoragePort(Protocol):
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
      async def apply_object_lock(self, key: str, *,
                                  retention_until: datetime,
                                  mode: str = "compliance") -> None: ...
      async def extend_object_lock(self, key: str, *,
                                   retention_until: datetime) -> None: ...
      async def lock_status(self, key: str) -> ObjectLockStatus: ...
      # Move / cutover (remediation only)
      async def move(self, src_key: str, dst_key: str,
                      *, verify_callback) -> None: ...
  ```

* **LocalFsWORM adapter** (dev):
  * Files under `${EVIDENCE_FS_ROOT}/<tenant>/<yyyy>/<mm>/<dd>/<evidence_id>/<part_or_final>`.
  * "Object lock" = `chmod 0o400` + a sidecar `.lock.json` storing `retention_until`, `mode`, `applied_at`, `applied_by`. Deletions are blocked by the application even if the FS would allow them; the adapter refuses to unlink any file whose sidecar lock is unexpired.
  * Multipart = real file part streams concatenated on `complete_multipart`.

* **R2 adapter** (production): uses Cloudflare R2's S3-compatible API. Until R2 ships native Object Lock, the adapter emulates WORM via:
  * Versioning (R2 has it).
  * A delete-protection lifecycle rule keyed on the metadata header `x-amz-meta-worm-until=<RFC3339>`.
  * A pre-deletion middleware in the adapter that **refuses** to call delete on any object whose `worm-until` is in the future, regardless of caller role.
  * Signed URLs via R2's `s3` sigv4.

  When R2 ships native Object Lock, swap the middleware for the real S3 Object Lock call without changing callers.

### 3.3 — Multipart streaming upload + server-side hash

Endpoints (all under `/api/v1/evidence`):

| Method | Path                                          | Purpose                                                                                       |
| ------ | --------------------------------------------- | --------------------------------------------------------------------------------------------- |
| POST   | `/items`                                      | Initiate: returns `evidence_id`, upload session id, signed multipart URLs. Status `pending_upload`. |
| PUT    | `/items/{id}/parts/{part_no}`                 | Upload one part; server streams to storage AND updates a streaming SHA-256.                   |
| POST   | `/items/{id}/complete`                        | Finalize multipart; server compares **streamed hash** vs `client_hash_claim` (if present);  status `pending_verification`. |
| POST   | `/items/{id}/verify`                          | Read-back from storage (independent stream), re-hash, set `server_hash` + `hash_verified=true`; status `verified`. |

Rules:
* The **only** authoritative hash is the streamed-and-verified server hash. A mismatched `client_hash_claim` is recorded in the integrity log as `claim_mismatch` and the item is rejected (`status` rolls back to `pending_upload`; client gets `409 evidence.hash_mismatch`).
* The two-pass design (streamed-during-upload + read-back-and-rehash) is the binding §1 of the directive: nothing is **seal-eligible** until both pass.
* No request body for `verify` — the server pulls from storage to defeat any "trusted client" assumptions.

### 3.4 — Encryption port + Software KMS

* `EncryptionPort` Protocol:

  ```python
  class EncryptionPort(Protocol):
      async def issue_tenant_dek(self, *, tenant_id: str, country: str) -> Dek: ...
      async def wrap(self, *, dek: Dek, country_master_kid: str) -> WrappedDek: ...
      async def unwrap(self, *, wrapped: WrappedDek) -> Dek: ...
      async def encrypt_stream(self, *, dek: Dek, plaintext_iter) -> AsyncIterator[bytes]: ...
      async def decrypt_stream(self, *, dek: Dek, ciphertext_iter) -> AsyncIterator[bytes]: ...
  ```

* **Software KMS adapter** (initial impl):
  * Country master keys live in `evidence_country_masters` (Mongo) — `{country, key_id, key_b64, created_at}`. Generated at first boot per country via `nacl.utils.random(32)`.
  * Per-tenant DEKs are generated on first use (`evidence_tenant_deks`); each one is wrapped with its country master via `nacl.secret.SecretBox`. The wrapped DEK + nonce are stored; plaintext DEKs never persist.
  * Encryption envelope written into the `EvidenceItem`: `{kms: "software_kms_v1", tenant_dek_id, country_master_kid, nonce, wrap_alg: "xsalsa20-poly1305"}`.
  * **Residency**: country master keys never leave their country. The adapter rejects unwrap requests where the requesting ExecutionContext's `country` ≠ the master's country (super_admin bypass logged + audited).
  * Test seam: in dev, country masters are seeded from a deterministic env var so tests are reproducible; production reads from a different env path.

### 3.5 — Seal manifest aggregate

The `Seal` is its own aggregate root (the "immutable manifest" the directive recommends). It groups one or more verified `EvidenceItem`s into a single tamper-evident envelope.

* Fields (`evidence_seals`):

  | Field                | Type     | Notes                                                                |
  | -------------------- | -------- | -------------------------------------------------------------------- |
  | `seal_id`            | str, immutable, `sea_<32hex>` |                                                  |
  | `registry_id`        | str, immutable                |                                                  |
  | `tenant_id`/`country_code` | str, immutable          |                                                  |
  | `evidence_ids`       | list[str], immutable          | Items must all be `verified`                     |
  | `merkle_root`        | str, immutable                | sha256 of the sorted leaf hashes                 |
  | `manifest`           | object, immutable             | `{items: [{evidence_id, server_hash, size, kind}], schema, created_at, sealed_by, registry_id, tenant_id, country}` |
  | `manifest_hash`      | str, immutable                | sha256 of `canonical_json(manifest)`             |
  | `status`             | enum                          | `created` → `worm_applied` → `anchored` → `legally_held`/`archived` |
  | `anchor_batch_id`    | str?, write-once              |                                                  |
  | `created_at`/`created_by` | str/str immutable        |                                                  |
  | `version`/`schema_version` | int                     | Monotonic                                         |

* **Invariants**: every field above except `status`, `anchor_batch_id`, and the version counters is **frozen at construction**. Once `status = worm_applied` the storage-layer Object Lock is active for every referenced item; the seal can never be deleted.
* **Commands**: `Seal.create()` (factory), `apply_worm()`, `attach_anchor()`, `archive()` (only via remediation, only with `replaced_by` set).

### 3.6 — Append-only logs

Four insert-only collections, all carrying `tenant_id`, `country_code`, `evidence_id`/`seal_id`, monotonic per-aggregate `seq`, and `prev_hash`/`entry_hash` for tamper-evident chaining:

| Collection            | Records                                                                                          |
| --------------------- | ------------------------------------------------------------------------------------------------ |
| `evidence_timeline`   | Every state transition + every operator-visible event (upload, verify, seal, hold, anchor, etc.) |
| `evidence_locks`      | WORM lock events (apply, extend, status query)                                                   |
| `evidence_integrity`  | Hash claim/computation/mismatch events; read-back re-hash results                                |
| `evidence_custody`    | Chain-of-custody — who signed/uploaded/downloaded, when, from where, signed-URL audit linkage    |

Adapters refuse `update` / `delete` operations on these collections at the database-port level (defense in depth).

### 3.7 — Signed-URL adapter + audit

* All object reads happen through **short-lived signed URLs** (default TTL 5 minutes; bounded above by the user's role policy — e.g. super_admin can request up to 60 minutes; field_agent capped at 5).
* The `SignedUrlPort` issues the URL and **synchronously** writes a `evidence_signed_url_audit` record containing the principal, action (`read` \| `verify` \| `export`), target evidence id, TTL, IP, user-agent, and a SHA-256 hash of the URL itself (we never store the URL plaintext).
* PDP enforces: anonymous principals get no signed URLs except for explicitly published / certificate-style endpoints (Phase 4 territory; in Phase 3 every signed URL is authenticated).

### 3.8 — Anchor saga + Merkle batching

This is the load-bearing async workflow of Phase 3.

* `AnchorPort` Protocol:

  ```python
  class AnchorPort(Protocol):
      provider_id: str  # "ctlog_internal" | "ots_v1"
      async def request_anchor(self, *, batch_id: str, root: str) -> AnchorRequest: ...
      async def poll_confirmation(self, request: AnchorRequest) -> AnchorState: ...
      async def fetch_inclusion_proof(self, request: AnchorRequest,
                                       leaf_hash: str) -> InclusionProof: ...
  ```

* **Internal CT-log adapter (`ctlog_internal`)** — ships first. Mongo collection `evidence_ctlog_tree` stores append-only leaves; a daily checkpoint job publishes the tree head and signature to `evidence_ctlog_checkpoints` (and to S3/R2 read-public in production). Inclusion proofs are computed from the persisted leaves.
* **OpenTimestamps adapter (`ots_v1`)** — ships second. Submits the Merkle root to one or more OTS calendar servers and stores the `.ots` proof bytes on each `AnchorRequest`.

* **Saga (Mongo + worker)**:

  ```text
  pending_batch → submitted → confirming → confirmed
                        \↘
                         submission_failed → retry_pending  → submitted
                                                 ↘
                                                  dlq
  confirming → confirmation_failed → retry_pending → submitted
  ```

  * `pending_batch` is created by `anchor_batcher` (cron / per-N-minutes) which scoops up `Seal`s in status `worm_applied AND anchor_batch_id IS NULL`, builds the Merkle root, persists the batch, and emits `evidence.anchor.batched.v1`.
  * `submitted` is set by the saga after a successful `request_anchor()`. Each retry increments `attempt`.
  * `confirming` polls `poll_confirmation()` with exponential backoff (10s, 60s, 5min, 1h, 24h, capped at 24h). After `MAX_CONFIRM_ATTEMPTS` (default 12) the saga moves to `dlq`.
  * `confirmed` materializes `InclusionProof`s onto each seal and emits `evidence.anchor.confirmed.v1`. Saga state recorded in `evidence_anchor_batches` and `evidence_anchor_attempts`.
  * `dlq` records are reachable via `POST /api/v1/evidence/anchor-batches/{id}/replay` (super_admin only) and emit `evidence.anchor.failed.v1` for monitoring/alerting.

* **No legal-defensibility claim** is exposed by the API until at least the CT-log anchor is `confirmed` and the seal stores its inclusion proof.

### 3.9 — Legal Hold + retention precedence

* `LegalHold` aggregate (`evidence_holds`):

  | Field        | Type   | Notes                                                                 |
  | ------------ | ------ | --------------------------------------------------------------------- |
  | `hold_id`    | str, immutable, `hld_<32hex>` |                                                  |
  | `tenant_id`/`country_code` | str, immutable |                                              |
  | `scope`      | object | Either `{evidence_ids: [...]}` or `{registry_id, all_evidence: true}` |
  | `reason`     | str    | Mandatory                                                             |
  | `issued_by`  | str    | Principal id (compliance role)                                        |
  | `lifted_at`  | str?   | One-way to non-null                                                   |
  | `lifted_by`  | str?   |                                                                       |
  | `version`    | int    | Monotonic                                                             |

* **Binding precedence**: when ANY active hold matches an evidence item, the retention sweeper skips it. The aggregate guards: `place_hold()` is allowed regardless of retention; `set_retention()` cannot truncate the effective retention while a hold is active; `lift_hold()` requires the same role tier that issued or a higher one.

* Authorization: place/lift requires `super_admin` OR `compliance_officer`. Every place + lift writes to the timeline + custody log.

### 3.10 — Verify-then-cutover remediation saga + orphan reconciliation

The directive is explicit: **"move → read back → re-hash → match → create evidence item → only then null the inline source. Never delete a source before verification."**

* Saga state-machine:

  ```text
  requested → src_locked → moving → moved → reverified → cutover_committed
                                  ↘
                                   reverification_failed → src_unlocked → failed
  ```

  * **`requested`**: super_admin invokes `POST /api/v1/evidence/items/{id}/remediate` with a target `dst_storage` and reason.
  * **`src_locked`**: take a read-lock on the source (refuse any concurrent state mutations).
  * **`moving`**: copy bytes to the destination via `StoragePort.move` with a `verify_callback` that re-streams and re-hashes during the write.
  * **`moved`**: source still exists; dest is fully written.
  * **`reverified`**: independent read-back from `dst_storage`, recompute SHA-256, compare against the original `server_hash`. **If mismatch → abort, leave source intact, record `reverification_failed` in the integrity log, raise event `evidence.remediation.failed.v1`.**
  * **`cutover_committed`**: ONLY when reverified successfully — mark the original evidence item as `archived_replaced`, write `replaced_by` pointing to the new evidence item id, and only then null the inline source (which itself, if WORM-locked, is allowed to remain under lock indefinitely — we never delete WORM bytes, we *unlink the reference*).
  * On any non-cutover terminal state, the original item remains the authoritative record.

* **Orphan reconciliation worker** runs hourly: scans the storage backend for objects without a corresponding `evidence_items` row, emits `evidence.orphan.detected.v1`, and writes a quarantine record so a human can decide whether to ingest or destroy under retention.

### 3.5* — Court-admissible export + offline verifier + offline-first capture

(Numbered "3.5" intentionally in the directive — it's a sidecar to the main sequence and gates Phase 4 just like the others.)

* **Court export bundle** (`POST /api/v1/evidence/seals/{id}/export`): produces a downloadable archive containing:
  * The canonical seal manifest (`manifest.json`)
  * The Merkle root + inclusion proof(s) from every anchor provider
  * The CT-log signed checkpoint (or OTS `.ots` proof bytes)
  * Per-evidence-item: hash, kind, size, encryption envelope metadata (NOT keys), origin, custody log slice
  * Signed audit chain slice (custody + timeline + integrity entries for this seal)
  * `VERIFY.md` with instructions, and `verifier.pyz` (the offline verifier)
  * A detached signature over the bundle metadata, signed by the platform's existing JWKS private key (the same key clients can fetch from `/api/.well-known/jwks.json`)

* **Offline verifier (`tools/offline_verifier/`)** — pure Python ≥ 3.11, zero non-stdlib dependencies (we vendor `nacl` if needed). Given a bundle, it:
  1. Verifies the JWKS signature against a fetched copy of `jwks.json` (or a pinned snapshot inside the bundle).
  2. Recomputes the Merkle root from the manifest's leaf hashes.
  3. Verifies the inclusion proof against the CT-log checkpoint (and/or runs `ots verify` against the calendar servers).
  4. Walks the custody/timeline/integrity chain checking `entry_hash == sha256(prev_hash || canonical_json(entry))`.
  5. Reports PASS/FAIL with a per-step audit log.

* **Offline-first field-capture spec** — frontend Phase 3.5 deliverable, but the **server contract** is in this phase:
  * Client may pre-mint `evidence_id`s in batches of N from `POST /api/v1/evidence/items/reserve` (super_admin / field_agent only, server records the reservation).
  * Captures happen offline; on reconnect, the client posts to `POST /api/v1/evidence/items/{id}/sync` with the multipart parts + client claim hash. The server still performs the full §3.3 streamed hash + verify pass — the client hash remains a claim.
  * Sync is **idempotent**: retries with the same `evidence_id` + same content produce the same result; retries with the same id but DIFFERENT content are rejected with `409 evidence.idempotency_violation` and an integrity event.

---

## 3. Authorization (PDP) — registered actions

Registered at startup like Registry; the resource type is `evidence_item` or `evidence_seal` or `evidence_legal_hold` accordingly.

| Action                                       | Allowed roles                                                                       |
| -------------------------------------------- | ----------------------------------------------------------------------------------- |
| `evidence.item.upload.initiate`              | `super_admin`, `field_agent`, `surveyor`, `licensed_surveyor`, `surveyor_partner`   |
| `evidence.item.upload.complete`              | same as initiate                                                                    |
| `evidence.item.read.signed_url`              | privileged (governance), creator/owner, assigned field_agent — through projection   |
| `evidence.item.verify`                       | system (post-upload), super_admin (re-verify)                                       |
| `evidence.seal.create`                       | `super_admin`, `surveyor_general`, `compliance_officer`, `licensed_surveyor`        |
| `evidence.seal.apply_worm`                   | system after `create`; manual: `super_admin`                                        |
| `evidence.seal.read`                         | governance + creator + projection                                                   |
| `evidence.anchor.batch.run`                  | system (cron) / `super_admin`                                                       |
| `evidence.anchor.batch.replay_dlq`           | `super_admin`                                                                       |
| `evidence.legal_hold.place`                  | `super_admin`, `compliance_officer`                                                 |
| `evidence.legal_hold.lift`                   | `super_admin`, `compliance_officer` (same or higher tier than placer)               |
| `evidence.remediate`                         | `super_admin`                                                                       |
| `evidence.export`                            | `super_admin`, `compliance_officer`, `government_observer`                          |
| `evidence.item.reserve`                      | `super_admin`, `field_agent` (offline-first capture)                                |

Tenant + country scoping inside the repository is mandatory regardless of role (defense in depth).

---

## 4. Domain events (additive to the catalog at v1.2.0)

All published via the transactional outbox in the same Mongo session as the aggregate write.

| Event name                                  | Aggregate     | Producer | Notes                                                              |
| ------------------------------------------- | ------------- | -------- | ------------------------------------------------------------------ |
| `evidence.item.uploaded.v1`                 | EvidenceItem  | evidence | Emitted on `complete` (status enters `pending_verification`)       |
| `evidence.item.hash_verified.v1`            | EvidenceItem  | evidence | Server-verified hash recorded                                       |
| `evidence.item.hash_mismatch.v1`            | EvidenceItem  | evidence | Recorded in integrity; client claim ≠ server hash                  |
| `evidence.item.archived_replaced.v1`        | EvidenceItem  | evidence | Old aggregate after a successful remediation cutover               |
| `evidence.seal.created.v1`                  | Seal          | evidence | Manifest fully populated                                            |
| `evidence.seal.worm_applied.v1`             | Seal          | evidence | All referenced items are now Object-Locked                          |
| `evidence.legal_hold.placed.v1`             | LegalHold     | evidence |                                                                    |
| `evidence.legal_hold.lifted.v1`             | LegalHold     | evidence | Includes `lifted_by`, `reason`                                     |
| `evidence.anchor.batched.v1`                | AnchorBatch   | evidence | Merkle root computed                                                |
| `evidence.anchor.submitted.v1`              | AnchorBatch   | evidence | Saga state transition                                               |
| `evidence.anchor.confirmed.v1`              | AnchorBatch   | evidence | Inclusion proofs persisted                                          |
| `evidence.anchor.failed.v1`                 | AnchorBatch   | evidence | Saga moved to DLQ                                                   |
| `evidence.remediation.committed.v1`         | EvidenceItem  | evidence | Verify-then-cutover succeeded                                       |
| `evidence.remediation.failed.v1`            | EvidenceItem  | evidence | Verify failed — source intact                                       |
| `evidence.orphan.detected.v1`               | OrphanRecord  | evidence | Storage object without aggregate                                   |
| `evidence.signed_url.issued.v1`             | EvidenceItem  | evidence | Mirrors `evidence_signed_url_audit`                                |
| `evidence.exported.v1`                      | Seal          | evidence | A court-export bundle was produced                                 |

Every event MUST include `registry_id` in its payload so downstream consumers can fan-out per LandVault.

---

## 5. Phase Acceptance Review (gates Phase 4)

Acceptance is granted iff **all** of the following are demonstrated end-to-end:

1. **Server-side hash discipline**: tampered `client_hash_claim` → `409 evidence.hash_mismatch` + integrity entry; uploads with no claim are still server-hashed and verified.
2. **WORM contract**: a sealed item cannot be deleted, overwritten, or short-retained — via either WORM adapter (LocalFs or R2). Attempting it returns `409 evidence.worm_violation`.
3. **Merkle anchor saga**: end-to-end happy path AND DLQ recovery (forced failure → `dlq` → super_admin replay → `confirmed`).
4. **Legal Hold precedence**: a held item is not retention-swept even after `retention_expires_at` passes; the sweeper logs `skipped_due_to_legal_hold`.
5. **Remediation saga safety**: failure-injection test asserting source bytes are still readable after a forced `reverification_failed`.
6. **Court export bundle**: produced for a sealed-and-anchored seal; the standalone offline verifier (`tools/offline_verifier/verifier.pyz`) confirms PASS without network access (apart from the optional `ots verify`).
7. **Offline-first capture**: 100 captures pre-minted offline, posted in random order with shuffled retries; the server reaches steady state with exactly 100 verified items and zero duplicates.
8. **Contract drift gate green** at `1.2.0`; new ADRs + CHANGELOG entries; SHA256 fingerprints refreshed.
9. **Per-tenant key isolation**: cross-tenant decryption attempt is denied + audited.
10. **Signed-URL audit completeness**: every URL issuance produces an audit row before the URL leaves the server.

---

## 6. Out of scope (deferred to Phase 4 or later)

* AI-driven OCR / verification (handled in Phase 4 — Verification context).
* Public verifier endpoints (Phase 5 — Public Verification context).
* Certificate issuance & PDF artifacts (Phase 6 — Certificate context).
* Real S3 Object Lock once R2 ships it.

---

## 7. Risks & mitigations

| Risk                                             | Mitigation                                                                                       |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------ |
| Streaming hash drift across language stacks      | Lock SHA-256 to RFC 6234 only; tests use NIST test vectors                                       |
| R2 WORM emulation circumvented by direct access  | Adapter-only access via a service principal; bucket policy denies non-adapter callers            |
| OTS calendar outage stalls the saga              | Saga state machine with bounded retries + DLQ; CT-log adapter is the primary, OTS the secondary  |
| Software KMS key compromise                      | Per-country master + per-tenant DEK; production path swaps to AWS KMS or HSM via the port        |
| Offline-first id collisions                      | `evidence_id`s are server-reserved before going offline; sync compares hashes for idempotency    |
| Remediation midway crash                         | Saga commits atomically per state transition; source bytes never touched until cutover           |
| Court verifier dependency rot                    | Offline verifier is pure stdlib + pinned vendored `nacl`; verifier checksum stored in bundle     |

---

## 8. Sign-off section

> The undersigned approves the Phase 3 build sequence above, including:
>
> * Cloudflare R2 (production) and LocalFs-WORM (dev) storage adapters
> * Internal CT-log anchor provider (first) and OpenTimestamps (second), behind a single port
> * Software KMS with per-tenant DEK / per-country master, residency-enforcing
> * One-page architectural review packet as the Acceptance Review artifact

*Signed*: __________________________
*Date*:   __________________________
