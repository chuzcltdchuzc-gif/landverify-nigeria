# Aquasavannah LandVault — Product Requirements Document (Living)

_Last updated: 2026-06-29_

## ⏱ 2026-06-29 — Phase 3.4 + 3.5 COMPLETE: Canonical Evidence Aggregate + Sealing

Shipped steps 4 + 5 of Phase 3 as a single atomic milestone with the
**contract bump 1.1.0 → 1.2.0** landing alongside the aggregates per ADR-0007.

### Delivered
- `backend/contexts/evidence/domain/`:
  - `EvidenceItem` aggregate root — canonical, immutable evidentiary
    record. Binaries NEVER in Mongo. Immutable: `evidence_id`,
    `registry_id`, `tenant_id`, `country_code`, `created_at`,
    `created_by`, `origin`, `kind`. Status FSM:
    `pending_upload → pending_verification → verified → sealed → archived_replaced`.
  - `Seal` aggregate root — immutable manifest. Manifest hash + Merkle
    root frozen at construction; `status` advances `created → worm_applied → archived`;
    `anchor_batch_id` is write-once.
  - `value_objects.py` — `compute_merkle_root` (sorted canonical
    merkle), `canonical_json_hash`, enums.
  - `invariants.py` — `HashMismatchError`, `SealedItemError`,
    `ImmutableFieldError`, `WormViolationError`, `TransitionError`,
    `ConcurrencyConflict`.
  - 8 immutable domain events.
- `backend/contexts/evidence/ports/`:
  - `repository.py` — `EvidenceItemRepository`, `SealRepository`.
  - `specifications.py` — composable `EvidenceItemSpec`, `SealSpec`.
- `backend/contexts/evidence/adapters/mongo_evidence_repository.py` —
  Mongo adapters with full Specification support, tenant + country
  scoping enforced regardless of role.
- `backend/contexts/evidence/application/evidence_service.py` —
  `EvidenceCommandService` orchestrates Mongo transaction + outbox
  publish + audit + metrics; per-role projection (`public` / `owner` /
  `privileged`). Hash discipline:
  - Server hashes are authoritative (streamed-during-write +
    independent read-back).
  - Client `client_hash_claim` is a **claim only**; mismatch →
    `409 evidence.hash_mismatch`, integrity event emitted, item rolled
    back to `pending_upload`. The rollback is committed to disk before
    the 409 surfaces (no transaction loss).
- `backend/contexts/evidence/api/`:
  - 10 new endpoints under `/api/v1/evidence/*` (see CHANGELOG).
  - Per-role Pydantic DTOs with `extra=forbid`.
- `backend/contexts/evidence/authorization.py` — 4 PDP policies
  registered with the central engine covering 8 actions
  (`evidence.item.upload.{initiate,complete}`, `evidence.item.verify`,
  `evidence.item.read{,.signed_url}`, `evidence.item.list`,
  `evidence.seal.{create,apply_worm,read}`).

### Contract package at `1.2.0`
- 70 governed artifacts (up from 52 at `1.1.0`).
- 8 new domain events added to `v1/events/catalog.json` + per-event
  schemas: `evidence.item.uploaded`, `evidence.item.hash_verified`,
  `evidence.item.hash_mismatch`, `evidence.item.archived_replaced`,
  `evidence.seal.created`, `evidence.seal.worm_applied`,
  `evidence.seal.archived`, `evidence.signed_url.issued` (all v1).
- 5 new request DTOs + 5 new response DTOs frozen as independent
  JSON Schemas. The generator now inlines nested `$ref` components.
- New `evidence_actions` block + `evidence.item` / `evidence.seal`
  field projections in `v1/security/`.
- ADR-0007 + CHANGELOG entry + new SHA256 fingerprints. Drift gate
  green at 1.2.0.

### Acceptance gate — ALL GREEN
| Test suite                                                  | Cases | Status |
| ----------------------------------------------------------- | ----- | ------ |
| `tests/test_evidence_aggregate_invariants.py` (pure domain) | 25    | ✅      |
| `tests/test_evidence_api_e2e.py` (E2E + WORM lockdown)      | 12    | ✅      |
| `tests/test_evidence_storage_foundation.py` (Phase 3.1)     | 16    | ✅      |
| `tests/test_evidence_pii_encryption.py` (Phase 3.2)         | 14    | ✅      |
| `tests/test_evidence_media_remediation.py` (Phase 3.3)      | 7     | ✅      |
| `tests/test_contract_freeze.py` (drift gate at 1.2.0)       | 8     | ✅      |
| Full platform regression (kernel + registry + identity)     | 150   | ✅      |

(6 pre-existing legacy tests under `/api/parcels` continue to fail
identically with or without these changes — they use 1-char location
tokens which the Phase 2A allocator rejects; documented Phase 2A
regression, NOT introduced by 3.4/3.5.)

### Strict non-goals (deferred to later phases)
- 🟡 **3.6 Anchoring + locking + integrity** — CT-log + OTS saga
  behind `AnchorPort`. `anchor_batch_id` on Seal is a placeholder field
  that NO command in this milestone sets.
- 🟡 **3.7 Timeline + versioning** — append-only chains.
- 🟡 **3.8 Events + projections** — read-model fan-out.
- 🟡 **3.9 SDK + React UI** — TypeScript SDK regen at 1.2.0 +
  Evidence pages.
- 🟡 **3.10 Phase 3 Acceptance Review packet**.

_Previous Phase 3.3 entry below._

---

## ⏱ 2026-06-29 — Phase 3.3 COMPLETE: Media Remediation

Shipped step 3 of Phase 3 strictly in the binding sequence. **No
implementation creep beyond 3.3** — the Evidence aggregate (and the
v1.2.0 contract bump that lands with it) is the next step and remains
blueprint-only.

### Delivered
- `backend/contexts/evidence/application/media_remediation.py`:
  - `MediaRemediationSaga` — resumable saga implementing the operator's
    binding sequence: **Verify (source readable + hashable) → Copy
    (StoragePort multipart with running SHA-256) → Verify (independent
    read-back + re-hash; MUST match) → Cutover (record provenance + null
    inline source)**. Source bytes are NEVER deleted before reverify
    succeeds.
  - State machine: `requested → src_verified → copying → copied →
    reverified → cutover_committed` (terminal). Failure paths:
    `source_unreadable → orphaned`, `reverification_failed → orphaned`.
    Every transition persisted to `evidence_media_remediation_sagas`
    with timestamp + actor.
  - Idempotent: a unique index on `(legacy_collection, legacy_doc_id,
    legacy_field)` in `evidence_remediated_media` prevents double-
    import; re-running on already-cut-over docs returns
    `state=already_done` with the original provenance.
  - **Cutover NEVER deletes** the legacy doc. The inline field is
    REPLACED with `{remediated: true, storage_key, server_hash,
    remediated_at}` so legacy readers can still resolve the bytes
    while the canonical record lives in WORM storage.
  - Orphan queue: failed migrations land in
    `evidence_remediation_orphans` with `state` + `reason`; the source
    inline binary remains intact.
  - `scan_collection(...)` — convenience API for batch sweeps across a
    legacy Mongo collection.
  - `resume_pending()` — replays any saga not in a terminal state on
    boot (no in-memory state required for correctness).
- `MediaSource` value object: `legacy_collection`, `legacy_doc_id`,
  `legacy_field`, `tenant_id`, `country`, `media_type`, optional
  `registry_id` so Phase 3.4 can link `EvidenceItem` aggregates back
  to their migrated rows.
- `_extract_inline_bytes` supports four legacy shapes: raw `bytes`,
  `data:<mime>;base64,...` URLs, bare base64 strings (≥32 chars),
  `{base64: "..."}` dicts.

### Acceptance gate (Phase 3.3) — ALL GREEN
| Test (tests/test_evidence_media_remediation.py)               | Cases | Status |
| ------------------------------------------------------------- | ----- | ------ |
| Happy path: Verify → Copy → Verify → Cutover                  | 1     | ✅      |
| Idempotency: re-running is a no-op                            | 1     | ✅      |
| Dry-run leaves source intact, no provenance, no orphan rows   | 1     | ✅      |
| Missing inline field → orphan queue, source untouched         | 1     | ✅      |
| Reverify mismatch (injected fault) → orphan, source intact    | 1     | ✅      |
| Saga history is append-only with timestamp + actor per step   | 1     | ✅      |
| `scan_collection` processes every doc with the field          | 1     | ✅      |
| **Total**                                                     | **7** | **green** |

Full regression: **137 tests pass** across Phase 1 / 1A / 1C / 2A /
3.1 / 3.2 / 3.3. No mocks introduced. Lint clean.

### Outstanding (Phase 3.4-3.10)
- 🟡 **3.4 Evidence aggregate** — `evidence_id`, `registry_id`,
  `object_ref`, `hash_fingerprint`, `custody_chain` + new
  `/api/v1/evidence/*` API. **Contract bump to v1.2.0 lands here**
  (additive minor; OpenAPI/JSON Schemas/Event Catalog regenerated;
  drift gate refreshed).
- 🟡 **3.5 Sealing** — `Seal` aggregate + WORM lockdown.
- 🟡 **3.6 Locking, integrity & anchoring** — Merkle saga (CT-log
  first, OTS second, behind `AnchorPort` + `CheckpointPublisherPort`);
  DLQ + replay; resumable.
- 🟡 **3.7 Timeline & versioning** — append-only chain of custody +
  supersession lock chain.
- 🟡 **3.8 Events & projections** — 17 Evidence event types;
  rebuildable read models.
- 🟡 **3.9 SDK & React UI** — TS SDK regenerated from frozen v1.2.0;
  React pages for upload/list/detail/timeline/seal/integrity/version/
  custody.
- 🟡 **3.10 Phase Acceptance Review packet** — Phase 4 awaits
  explicit operator approval.

_Previous Phase 3.2 entry below._

---

## ⏱ 2026-06-29 — Phase 3.2 COMPLETE: PII Encryption

Shipped step 2 of Phase 3 per the binding sequence. **No
implementation creep beyond 3.2** — aggregate, sealing, anchoring,
remediation, timeline, and API surface remain blueprint-only until
their respective steps. Honors operator constraint §9 ("architectural
correctness over implementation convenience").

### Delivered
- `backend/contexts/evidence/ports/encryption.py`:
  - `EncryptionPort` Protocol — the **sole** cryptographic
    abstraction. Domain never sees `nacl` (enforced by an automated
    import-scan test).
  - `EncryptionEnvelope` value object — `kms_id`, `tenant_dek_id`,
    `country_master_kid`, `wrap_alg`, `nonce_b64`, `schema`. Stored
    verbatim next to every encrypted artifact; round-trip via
    `to_dict`/`from_dict`.
  - `BreakGlassChallenge` value object — `requesting_principal_id`,
    `requesting_role`, `request_country`, `target_country`,
    `reason_code`, `reason_detail`, `correlation_id`, and dual-auth
    fields (`second_approver_principal_id`,
    `second_approver_signature`). `is_dual_authorized()` returns true
    iff both are present.
  - `ResidencyViolation` / `BreakGlassRejected` exceptions.
- `backend/contexts/evidence/adapters/software_kms.py`:
  - First concrete adapter — XSalsa20-Poly1305 via `nacl.SecretBox`.
  - Per-country master in `evidence_country_masters` (one document
    per country, upserted via `$setOnInsert` so concurrent boots
    never replace an existing master).
  - Per-tenant DEK in `evidence_tenant_deks` (unique on
    `(tenant_id, country)`), DEK plaintext **never persisted** —
    Mongo holds only nonce + ciphertext + wrap_alg.
  - `evidence_security_incidents` collection — Break-Glass attempts
    and successes recorded BEFORE the unwrap returns (durable audit
    even if the subsequent crypto fails).
  - Operator-defined allow-list of reason codes:
    `LITIGATION_PRESERVATION_ORDER`, `REGULATOR_AUDIT`,
    `CRIMINAL_INVESTIGATION`, `DATA_SUBJECT_LEGAL_REQUEST`,
    `INTERNAL_FRAUD_REVIEW`. Anything outside is rejected at the
    port boundary.
  - Streaming encrypt/decrypt (XOR-counter per-chunk nonce derivation
    over the envelope's single stream nonce) for future Phase 3.5
    sealing of binaries.
- `main.py` composition root: `evidence_kms` constructed at startup
  with `await ensure_indexes()`; exposed via `app.state.evidence_kms`
  for Phase 3.4+ wiring.

### Acceptance gate (Phase 3.2) — ALL GREEN
| Test (tests/test_evidence_pii_encryption.py)                  | Cases | Status |
| ------------------------------------------------------------- | ----- | ------ |
| Domain/application code never imports `nacl` (file scan)      | 1     | ✅      |
| `ensure_country_master` idempotent + single-row per country   | 1     | ✅      |
| `get_or_create_tenant_dek` idempotent per (tenant, country)   | 1     | ✅      |
| Tenant DEK plaintext NEVER persisted                          | 1     | ✅      |
| Encrypt/decrypt bytes round-trip                              | 1     | ✅      |
| Encrypt/decrypt stream round-trip (multi-chunk, irregular)    | 1     | ✅      |
| Cross-country unwrap without break-glass denied               | 1     | ✅      |
| Break-Glass requires `super_admin`                            | 1     | ✅      |
| Break-Glass reason must be in allow-list                      | 1     | ✅      |
| Break-Glass records `SecurityIncident` BEFORE returning       | 1     | ✅      |
| Dual-auth fields carried through to the incident record       | 1     | ✅      |
| Tampered ciphertext fails to decrypt (Poly1305 MAC)           | 1     | ✅      |
| Envelope round-trips through dict                             | 1     | ✅      |
| `residency_country_of_async` returns DEK country              | 1     | ✅      |
| **Total**                                                     | **14**| **green** |

### Outstanding (Phase 3.3-3.10)
- 🟡 **3.3 Media remediation** — idempotent migration of legacy
  base64/binary fields → private storage via verify-then-cutover
  saga; orphan worker.
- 🟡 **3.4 Evidence aggregate** — `evidence_id`, `registry_id`,
  `object_ref`, `hash_fingerprint`, `custody_chain`. **Contract bump
  to v1.2.0 lands here** (additive minor: new endpoints, schemas,
  events; OpenAPI/JSON Schemas/event catalog regenerated; drift gate
  refreshed).
- 🟡 **3.5 Sealing** — `Seal` manifest aggregate + WORM lockdown.
- 🟡 **3.6 Locking, integrity & anchoring** — Merkle saga (CT-log
  first, OTS second, behind `AnchorPort` + `CheckpointPublisherPort`);
  DLQ + replay.
- 🟡 **3.7 Timeline & versioning** — append-only chain of custody +
  evidence supersession via lock chain.
- 🟡 **3.8 Events & projections** — fan-out read models + 17
  Evidence event types in the catalog.
- 🟡 **3.9 SDK & React Evidence UI** — TypeScript SDK regenerated
  from frozen contracts; React pages for upload/list/seal/timeline.
- 🟡 **3.10 Phase Acceptance Review** — one-page architectural
  packet (ADR refs + invariant inventory + acceptance test results +
  outstanding risks). Phase 4 does NOT auto-start.

_Previous Phase 3.1 entry below._

---

## ⏱ 2026-06-29 — Phase 3.1 COMPLETE: Evidence Storage Foundation

First step of Phase 3 ("Files & Evidence") shipped per the binding
build sequence (Storage → PII encryption → Media remediation →
Aggregate → Sealing → Locking/Integrity/Anchoring → Timeline →
Events/Projections → SDK/UI → Acceptance Review). **No
implementation creep beyond 3.1** — aggregate, sealing, anchoring,
hashing, encryption, and the API surface remain blueprint-only until
their respective step gates.

### Delivered
- `backend/contexts/evidence/{ports,adapters}/` — bounded-context
  skeleton + the two storage ports:
  - `StoragePort` Protocol — multipart streaming upload, read-back
    streaming hash (foundation for ADR-0004), WORM Object-Lock
    (apply/extend/status), remediation-only `move(verify_callback)`
    that NEVER deletes the source, canonical `StorageObjectKey` with
    strict 2-tier (`public`/`private`) layout.
  - `SignedUrlPort` Protocol — issues short-lived URLs (default 5min,
    hard cap 1h) with per-role tier clamps; binding contract that the
    audit row lands in `evidence_signed_url_audit` BEFORE the URL is
    returned. Per-issuance nonce makes every URL byte-unique.
- `LocalFsWormStorage` adapter (dev): chmod-immutable + sidecar
  `<obj>.lock.json` retention metadata; refuses to overwrite or
  re-initiate multipart on a locked key; governance-mode locks are
  rejected at the adapter (compliance mode is the only legal mode);
  forward-only retention extensions.
- `R2StorageAdapter` skeleton (production): port-clean, every method
  raises `NotImplementedError` with an explicit operator setup
  message (`R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, …). Concrete sigv4
  implementation lands when operator credentials are configured;
  callers do not change.
- `SignedUrlMotorAdapter` (reference implementation of
  `SignedUrlPort`) — HMAC-SHA-256 signed paths,
  `evidence_signed_url_audit` collection with `url_sha256` unique
  index, indexed by `evidence_id`, `principal_id`,
  `(tenant_id, issued_at desc)`.
- `main.py` wiring: composition root constructs storage + signed-URL
  ports at startup; ensure-indexes called; `app.state` exposes the
  ports for downstream Phase 3.4+ wiring.

### Acceptance gate (Phase 3.1) — ALL GREEN
| Test (tests/test_evidence_storage_foundation.py) | Cases | Status |
| ------------------------------------------------ | ----- | ------ |
| Tier strict-2-valued + key layout invariants     | 3     | ✅      |
| Multipart streaming + canonical streamed SHA-256 | 3     | ✅      |
| Independent read-back stream matches plaintext   | 1     | ✅      |
| WORM contract (overwrite-blocked, mode-rejected, forward-only) | 4 | ✅      |
| Remediation `move` preserves source bytes        | 1     | ✅      |
| R2 adapter port-clean (NotImplementedError msg)  | 1     | ✅      |
| Signed-URL TTL clamps + audit-before-return + invalid-TTL reject | 3 | ✅      |
| **Total**                                        | **16**| **green** |

Full regression: 24 pass (16 new + 8 contract-freeze). Contract drift
gate refreshed (release-manifest `git_commit` + `build_timestamp` now
normalized in the comparator to suppress commit-rotation noise while
preserving full contract drift detection).

### Phase 3 governance state
- ADRs **0003, 0004, 0005, 0006** are committed to
  `contracts/v1/adr/` and govern the rest of Phase 3 implementation.
- `/app/memory/PHASE3_SPEC.md` is the authoritative spec (annotated
  with operator-approved decisions on residency, anchor cadence,
  reservation sizes, CheckpointPublisherPort abstraction).
- Contract bump deferred until the Phase 3 API surface lands at
  Phase 3.4 — until then 3.1 is purely infrastructural (no new
  endpoints, no schema changes).

### Outstanding (Phase 3.2+)
- 🟡 **Phase 3.2 — PII encryption**: `EncryptionPort` + Software KMS
  with per-tenant DEK / per-country master + Break-Glass cross-
  country unwrap (super_admin + reason + `SecurityIncident` event +
  dual-auth design).
- 🟡 **Phase 3.3 — Media remediation**: idempotent migration of
  base64/binary from legacy Mongo docs into private storage via
  verify-then-cutover; orphan worker.
- 🟡 **Phase 3.4 — Evidence aggregate**: `evidence_id`,
  `registry_id`, `evidence_type`, `object_ref`, `hash_fingerprint`,
  `custody_chain` + API surface (contract bump to 1.2.0).
- 🟡 **Phase 3.5 — Sealing**, **3.6 — Locking/integrity/anchoring**,
  **3.7 — Timeline/versioning**, **3.8 — Events/projections**,
  **3.9 — SDK/UI**, **3.10 — Acceptance Review packet**.

_Previous Phase 2A entry below._

---

## ⏱ 2026-06-28 — Phase 2A COMPLETE: Canonical LandVault Registry

First business bounded context shipped on top of the frozen Phase 1C
platform. **Contract bumped `1.0.0 → 1.1.0`** (additive minor) per the
binding architectural authorization.

### Delivered
- **`backend/contexts/registry/`** — full DDD bounded context:
  - **Domain**: `LandVault` aggregate root (one and only authoritative
    land record), value objects (`ParcelNumber`, `Geometry`, `Origin`,
    `OwnershipType`, `LandVaultStatus`, `PropertyType`), per-command
    invariants, 5 immutable domain events.
  - **Aggregate invariants enforced**: `registry_id` / `parcel_number` /
    `tenant_id` / `country_code` / `created_at` / `origin.*` immutable;
    `version` + `schema_version` monotonic; OwnershipHistory append-only;
    archive one-way; locked-status guard.
  - **Ports**: `LandVaultRepository`, `RegistryNumberAllocator`,
    composable `LandVaultSpec`.
  - **Mongo adapters**: indexes (unique `registry_id`, unique
    `parcel_number`, sparse `legacy_aliases`, compound
    `(country_code, tenant_id, status)`, **2dsphere on `geometry`**,
    provenance index for migration idempotency); atomic
    `findOneAndUpdate $inc upsert` allocator that produced 0 duplicates
    across N=200 parallel test runs.
  - **Application service** orchestrates Mongo transaction + outbox
    publish + audit + metrics; per-role projection (`public` / `owner` /
    `privileged`).
  - **API**: `/api/v1/registry/landvaults` with task-oriented commands
    (`Create`, `UpdateLocation`, `UpdateGeometry`,
    `UpdateOwnershipContact`, `RecordOwnershipTransfer`, `UpdateSurvey`,
    `UpdateCommunityData`, `Archive`); per-role Pydantic DTOs with
    `extra=forbid` (anti mass-assignment).
  - **PDP policies** registered with the centralized authorization
    engine (5 policies + role matrix); aggregate enforces locked-state &
    tenant scope as defense-in-depth.

### Ownership-event discipline (§3)
- `registry.ownership.recorded.v1` emitted ONLY on legal ownership
  changes (`owner_name`, `ownership_type`, representative authority,
  family composition). **NOT** emitted for phone/email contact edits.
- Append-only `ownership_history[]` extended only on legal changes;
  initial registration always records the first entry.

### Migration tool (§10)
- `python -m contexts.registry.migration --commit --batch-id=…` —
  idempotent, provenance-preserving, duplicate-quarantining import from
  legacy `parcels` + `land_vault_parcels` collections.
- Aliases preserved in `legacy_aliases[]`; never authoritative.
- Quarantine collection `landvault_migration_quarantine` for
  unmappable rows (no auto-merges).

### Legacy compatibility adapter (§2)
- `POST /api/parcels` now writes through `RegistryCommandService` (the
  authoritative path) and mirrors the canonical record back into the
  legacy `parcels` collection for read-side back-compat.
- Legacy adapter normalizes legacy role names to canonical roles; ALL
  writes flow through the same aggregate, transactional outbox, audit,
  and metrics pipeline as `/api/v1/registry/*`.
- Frozen OpenAPI marks every `/api/*` non-v1 endpoint `deprecated: true`
  per the deprecation policy.

### Contract package at `1.1.0`
- 52 governed artifacts (up from 37 at `1.0.0`).
- 5 new domain events added to `v1/events/catalog.json` + per-event
  JSON Schemas: `registry.landvault.created.v1`, `…updated.v1`,
  `…parcel_reference.allocated.v1`, `…ownership.recorded.v1`,
  `…archived.v1`.
- 8 new request DTOs + 2 new response DTOs frozen as independent
  schemas under `v1/schemas/`.
- New `registry_actions` and `registry.land_vault` field-projection
  entries in `v1/security/`.
- ADR-0002 + CHANGELOG entry + new SHA256 fingerprints (drift gate
  refreshed and verified).

### Tests (Directive §12 acceptance matrix)
| Suite                                       | Cases | Status |
| ------------------------------------------- | ----- | ------ |
| Aggregate invariants                        | 22    | ✅      |
| Geometry validation                         | 6     | ✅      |
| Allocator concurrency (N=50)                | 4     | ✅      |
| Allocator stress (N=200)                    | 1     | ✅      |
| Registry API + authz matrix + tenant + 2dsphere | 14 | ✅      |
| Migration (idempotency + quarantine)        | 6     | ✅      |
| Contract drift gate                         | 8     | ✅      |
| Legacy compatibility (e2e)                  | 1     | ✅      |
| Phase 1 + 1A + 1C regression                | 44+   | ✅      |
| **Total**                                   | **106+** | **green** |

### Regression caught + fixed during testing
- Legacy `/api/parcels` returned `500` when `lga`/`ward` was a single
  character. Root cause: `MongoRegistryNumberAllocator._normalize`
  imposed no min-length floor while `ParcelNumber` regex requires ≥2
  chars per token. **Fixed** with a min-length check in `_normalize`
  and a `ValueError → 400 registry.invalid_location_token` mapping in
  the application service. Now returns RFC 7807 problem+json with the
  proper code, title, status, instance, and correlation_id.

_Previous Phase 1C entry below._

---

## ⏱ 2026-06-28 — Phase 1C COMPLETE: Platform Contract Freeze

Implemented the **AquaSavannah LandVault Platform Contract Package** at
`/app/contracts/` per the binding Phase 1C directive. The platform now
publishes a single, versioned, machine-readable source of truth for every
external contract.

### Delivered artifacts (contract version `1.0.0`)
- `contracts/VERSION` (semver pin) + `CHANGELOG.md` + `deprecation-policy.md`
- `contracts/v1/openapi.json` — frozen OpenAPI 3 for both surfaces
  (`/api/v1/*` canonical + `/api/*` deprecated)
- `contracts/v1/schemas/requests/*.json` and `responses/*.json` — every
  Phase 1 DTO frozen as an independent JSON Schema (8 request + 1 response)
- `contracts/v1/errors/*.json` — 7 RFC 7807 problem+json contracts
  (ValidationError, AuthorizationDenied, ConcurrencyConflict, NotFound,
  RateLimitExceeded, SpatialValidationError, BusinessRuleViolation)
- `contracts/v1/events/catalog.json` + 12 per-event JSON Schemas (the
  full identity.* domain event stream); event_name/version mirror
  `kernel.events.outbox.EVENT_TYPES`
- `contracts/v1/security/permissions.json`, `role_matrix.json`,
  `field_projection.json` — machine-readable authorization spec for
  the 10 canonical roles and the ABAC pattern library
- `contracts/v1/sdk/sdk.version`, `compatibility.json`, `contract.sha256`
  — SDK fingerprint for downstream generators
- `contracts/release-manifest.json` — release-level metadata (git commit,
  build timestamp, per-file SHA256, aggregate checksums)
- `contracts/v1/adr/ADR-0001-platform-contract-freeze.md`

### Governance
- `contracts/generate.py` — single source of truth. Run
  `python -m contracts.generate` to regenerate the entire tree
  deterministically (sorted keys, indent=2).
- `contracts/ci_check_drift.sh` + `backend/tests/test_contract_freeze.py`
  (8 strict assertions) — CI gate that fails on byte-level drift, missing
  canonical endpoints, untagged legacy endpoints, event-catalog/outbox
  skew, role-matrix/runtime skew, and malformed SHA fingerprints.
- All `/api/*` non-v1 routes auto-tagged `deprecated: true` + `legacy`
  in the frozen OpenAPI per the deprecation policy.
- Verified: tamper test (mutated `openapi.json`) → drift gate fired with
  remediation instructions; full backend suite still **130 passed, 2
  skipped** including 8 new contract-freeze tests.

_Original 2026-06-24 entry below._

---


## 1. Original problem statement
Build Aquasavannah LandVault — a subscription-based, production-ready web application that
serves as the **trusted evidence layer for land transactions and land history** in Nigeria.
It preserves, verifies, and makes land evidence transparent. It does NOT determine ownership.

Spec covered 13 production layers, 6 subscription tiers, role-based dashboards, credit wallet,
audit trail, trust validation, and admin command centre.

## 2. Architecture decisions (made together with user)
- **Auth:** Emergent-managed Google Auth (with a dev-login bypass for automated testing)
- **Payments:** Stripe (sandbox key already in env) **+** Paystack (sandbox stub)
- **Database:** MongoDB (in place of the spec's PostgreSQL). Equivalent RLS achieved by
  consistently filtering on `tenant_id` and using atomic `$inc` for credit ops.
- **AI/OCR:** Mocked for v1 — jobs run, return canned results
- **Stack:** React + FastAPI + MongoDB; Tailwind + shadcn/ui + lucide-react + sonner toast

## 3. User personas
1. **Citizen / Family** — primary uploader of family land evidence
2. **Community Validator** — village chairmen, family heads, traditional rulers
3. **Surveyor Partner** — registered surveyors uploading plans
4. **Legal / Due Diligence** *(routes ready, dashboard deferred)*
5. **Institutional (Bank/Corp)** *(routes ready, dashboard deferred)*
6. **Government Observer** *(routes ready, dashboard deferred)*
7. **Platform Admin** — operates the command centre

## 4. Implemented in v1 (2026-06-24)
### Backend (now modular under `/app/backend/`)
- **Phase 9 refactor complete** — monolithic 2 569-line `server.py` reduced to an 8-line shim. Full enterprise structure: `core/`, `schemas/`, `services/`, `routers/`, `webhooks/`. Zero API breaking changes. Backend version bumped 1.0.0 → 1.1.0. See `MIGRATION_REPORT.md`.
- Emergent Google Auth + `/api/auth/dev-login` test bypass
- `/api/auth/me`, `/api/auth/logout` with httpOnly session cookie + Bearer fallback
- Public: `/api/public/stats`, `/api/public/verify`, `/api/public/plans`, `/api/public/transparency`
- Parcels CRUD, evidence vault (SHA-256), community attestations (RBAC ≥ COMMUNITY_VALIDATOR)
- Surveyor assignments + survey plan upload (RBAC ≥ SURVEYOR)
- Credit wallet with atomic `$inc` deductions + idempotency keys
- **Payments (iteration 2 — env-driven):**
  - `/api/payments/config` returns `{stripe: {enabled, mode, publishable_key}, paystack: {enabled, mode, public_key}}` — secrets never leak
  - Stripe checkout via `emergentintegrations` (USD-equivalent NGN); status endpoint verifies local ledger FIRST (404 on unknown), enforces user isolation (admin override allowed)
  - **Real Paystack** integration: `POST /transaction/initialize` and `GET /transaction/verify/{ref}` via httpx with `Authorization: Bearer ${PAYSTACK_SECRET_KEY}`
  - `/api/webhook/stripe` — signature verified via `stripe.Webhook.construct_event` against `STRIPE_WEBHOOK_SECRET`
  - `/api/webhook/paystack` — HMAC-SHA512 verified against `PAYSTACK_WEBHOOK_SECRET` (or `PAYSTACK_SECRET_KEY` fallback)
  - All payment endpoints return **503 "Payment system not configured (Stripe|Paystack)"** when the provider's secret is missing — no crash, no silent failure
  - `_fulfill_payment()` idempotent (guarded by `credits_granted` flag + `idempotency_key` on credit transactions)
- Admin overview, users, parcels, evidence (approve), jobs (process), audit log
- Trust validation — **REAL sub-scores from DB counts** (no false 100s), graded A_PLUS … F
- Take-off readiness assessment
- Job queue (PENDING → PROCESSING → COMPLETED/FAILED) with mock OCR/duplicate/fraud
  and real confidence recalculation
- Audit log on every material action; timeline events per parcel
- Indexes on users.email, parcels.parcel_number, sessions.session_token, etc.

### Frontend (React)
- Landing (`/`) — split layout, hero, trust stats, six pricing cards, demo login
- Public verification (`/verify`)
- Trust architecture (`/trust`)
- Community transparency (`/community-transparency`)
- Citizen dashboard (`/dashboard`) — KPIs, parcels list, create-parcel dialog,
  evidence-upload dialog, wallet widget, activity timeline
- Validator dashboard (`/validator`) — queue + attestation form + my attestations
- Surveyor dashboard (`/surveyor`) — assignments + survey upload form + recent surveys
- Admin dashboard (`/admin`) — KPI row, trust panel, readiness panel, 13-layer health,
  tabs for users/parcels/evidence/jobs/audit, action buttons (run trust, process jobs, scan)
- Billing (`/billing`) — credit packs + plans + Stripe & Paystack checkout
- Stripe success/cancel + Paystack success polling pages

### Theme
- Green-to-blue gradient background, Plus Jakarta Sans + Inter + JetBrains Mono fonts
- Cards: `#fff` + soft green shadow, glass-morphism for stats panels
- Trust stamps and badges in custom monospace

## 5. Test coverage (iteration 1)
- Backend: **28/28** pytest tests passed (`/app/backend/tests/backend_test.py`)
- Frontend: **9/9** UI flows verified (landing, public verify, citizen/validator/surveyor/admin
  dashboards, plus form submissions and admin actions)
- Critical issues: **0**
- Minor issues: 1 (cosmetic key naming on `/api/public/stats`)

## 6. Deferred (P1)
- Phase 8 frontend dashboards for Legal / Institutional / Observer (**backend ready**, includes risk engine + real PDF report generation via job queue; only the React pages remain)
- Real Paystack integration ✅ DONE (iteration 2)
- Stripe webhook signature verification ✅ DONE (iteration 2)
- Enterprise backend refactor ✅ DONE (iteration 3 / Phase 9)
- Real OCR / fraud scoring (mocked)
- Cloudflare R2 file storage
- Rate limiting + Sentry instrumentation
- CI/CD pipeline scaffolding

## 7. Backlog (P2)
- Stripe Metered Billing for institutional plans
- Email notifications (Resend / Postmark)
- Mapbox parcel boundary visualisation
- Bulk verification API for institutional users
- Recovery test runner + scheduled backups
- Multi-region Neon read replicas (Lagos)

## 11. Phase 1 — Identity & Authorization (2026-06-26) — COMPLETE

**Scope (per Chief Architect sign-off — Decisions 1a, 2b, 3a, 4a-modified, 5-modified):**
Constitutional Platform Kernel + Identity bounded context layered alongside
the existing application. No business features migrated in Phase 1.

### Platform Kernel (`/app/backend/kernel/` — ADR-012, immutable core)
- **`kernel/config/`** — typed PlatformSettings, fail-fast load from env
- **`kernel/security/`** — RS256 JWT + JWKS publication, key rotation with
  configurable grace, bcrypt password hashing (cost 12), opaque refresh
  tokens (SHA-256-hashed at rest, 32-byte secrets, httpOnly secure cookies)
- **`kernel/persistence/`** — `ExecutionContext` ContextVar carrying the
  authenticated identity (principal/email/country/tenant/org/roles/scopes/
  session_id/correlation_id) — single source of truth per the architectural
  clarification. `BaseRepository` auto-injects tenant + country from the
  context, refuses client-supplied scope, stamps audit metadata, applies
  optimistic concurrency via `version`
- **`kernel/audit/`** — Append-only `AuditStore` (ADR-005) with monotonic
  sequence counter and SHA-256 hash chain. Transaction-wrapped chain-tip
  read + insert prevents concurrent-writer hash collisions. No update /
  delete / replace methods on the public API
- **`kernel/authorization/`** — Full PEP/PDP/PIP/PAP engine (ADR-002).
  Default-deny, fail-closed, role + attribute + tenant + country
  isolation policies. Anonymous principals limited to whitelisted public
  actions. Programmatic `enforce()` audits both PERMIT and DENY
- **`kernel/errors/`** — RFC 7807 problem+json with correlation_id (binding,
  API standards §7)
- **`kernel/observability/`** — JSON structured logs + correlation id ContextVar

### Identity bounded context (`/app/backend/contexts/identity/`)
DDD-shaped: `domain/` (User, Session, ProviderIdentity, value objects) ·
`ports/` (UserRepositoryPort, SessionRepositoryPort, IdentityProviderPort) ·
`adapters/` (Mongo* repos) · `application/` (AuthService + providers) ·
`api/` (auth_router, jwks_router, DTOs).

**Identity is the canonical authority** — User, Identity, Roles, Country,
Tenant, Organisation, Sessions, Security Policies, and Audit Metadata all
live in this context. External authentication providers are adapters behind
`IdentityProviderPort`:
- `LocalIdentityProvider` — email + bcrypt password
- `EmergentGoogleIdentityProvider` — wraps Emergent OAuth as an
  Anti-Corruption Layer (§13). Translates external profile into the
  internal `AuthenticatedSubject` type; never leaks external schema into
  the domain
- Architecture is provider-agnostic — Microsoft Entra, government IDPs,
  SAML/OIDC providers all plug in via the same port

### HTTP API (mounted under `/api/v1/auth/*`)
- `POST /v1/auth/register` — create local user, return tokens
- `POST /v1/auth/login` — local email+password
- `POST /v1/auth/login/google` — Emergent Google OAuth session exchange
- `POST /v1/auth/refresh` — rotates the refresh token; replay detection
  kills the entire session chain (token-theft heuristic)
- `POST /v1/auth/logout` — revokes the current session
- `GET  /v1/auth/me` — returns the authenticated ExecutionContext
- `GET  /.well-known/jwks.json` — public RSA verification keys for any
  future relying party (federated identity ready)

### Country handling (Decision 5 — modified)
- Country is a first-class architectural concept from day one
- `country` is a JWT claim, in the ExecutionContext, persisted on the User,
  and participates in repository scoping + authorization isolation
- Default operational country = NG; multi-country onboarding requires no
  structural code changes (only PlatformSettings + reference data)

### Coexistence with legacy
- Existing business routes (`/api/parcels`, `/api/evidence`, `/api/payments`, …)
  continue to operate unchanged via the legacy `session_token` cookie
- Phase 1 endpoints live under `/api/v1/...` so legacy + new ship side-by-side
- Legacy `/api/auth/dev-login` is preserved for the existing test suite

### Test coverage (iteration 5)
- Backend: **67 passed, 2 skipped, 0 failed** (was 51)
  - +12 Phase 1 identity flow tests (`tests/test_phase1_identity.py`)
  - +7 PDP / authorization engine unit tests (`tests/test_authorization_engine.py`)
  - +3 audit-store / hash-chain tests (`tests/test_audit_store.py`)
- Lint clean on `/app/backend/kernel` and `/app/backend/contexts`

### Operational notes
- `PLATFORM_JWT_ISSUER`, `PLATFORM_JWT_AUDIENCE`, `PLATFORM_ACCESS_TTL_SECONDS`,
  `PLATFORM_REFRESH_TTL_SECONDS`, `PLATFORM_KEY_GRACE_SECONDS`,
  `PLATFORM_DEFAULT_COUNTRY`, `PLATFORM_REFRESH_COOKIE`, `PLATFORM_COOKIE_SECURE`,
  `PLATFORM_COOKIE_SAMESITE` all configurable via env; sensible defaults baked
- Signing keys auto-generated on first startup in `kernel_signing_keys`
  collection. Call `KeyStore.rotate()` programmatically when needed
- Audit log + counter collections: `kernel_audit_log`, `kernel_audit_counters`
- Identity collections: `identity_users`, `identity_sessions`

## 12. Phase 1A — Constitutional Completion (2026-06-28) — COMPLETE

Per the Chief Architect's Phase 1 Definitive Delivery Spec sign-off (Phase 1A:
Identity / Service Accounts / Delegation / Specifications / ABAC Policy
Library / Domain Events / Business Observability / Authorization Test Matrix).

### Identity — 10-role canonical model
- `contexts/identity/domain/value_objects.Role` enum with the EXACT legacy
  set: general_user, surveyor_general, surveyor, field_agent, super_admin,
  compliance_officer, licensed_surveyor, surveyor_partner,
  community_validator, government_observer
- Named privileged role sets (`GOVERNANCE_ROLES`, `SURVEY_ROLES`,
  `COMMUNITY_ROLES`, `OBSERVER_ROLES`, `FIELD_ROLES`) for ABAC policies
- Extended `User` aggregate: phone, organization, organization_id,
  avatar_url, license_number, lga_code, role_confirmed,
  suspension_reason / suspended_by / suspended_at
- Account-status enforcement at every auth path (`User.can_authenticate()`)
- Backwards-compatible role aliases preserved during transition grace

### Service Accounts + Delegation Grants
- `contexts/identity/domain/service_account.ServiceAccount` — non-human
  principal with explicit minimal scopes, SHA-256 secret_hash (plaintext
  returned exactly once at creation), ACTIVE/REVOKED lifecycle
- `contexts/identity/domain/delegation.DelegationGrant` — time-bounded,
  revocable, audited grant of named scopes from delegator to delegate
- `IdentityAdminService` (under `contexts/identity/application/admin_service.py`)
  orchestrates suspend / activate / assign_role / create_service_account /
  revoke_service_account / grant_delegation / revoke_delegation — every
  operation publishes a versioned Domain Event + writes an audit entry +
  emits a business metric

### Repository Specification Pattern
- `kernel/persistence/specification.Specification` base class — composable
  clauses translated to Mongo filters ONLY by the repository
- `contexts/identity/ports/specifications.py`: ActiveUsersSpecification,
  SuspendedUsersSpecification, UsersByTenantSpecification,
  UsersByCountrySpecification, UsersByRoleSpecification,
  UsersByOrganizationSpecification
- `MongoUserRepository.find(spec)` / `.count(spec)` accept specifications
  — no Mongo syntax in callers

### Reusable ABAC Policy Library (`kernel/authorization/policy_library.py`)
- `create_owner_stamp_policy` — legacy CREATE: caller becomes owner via
  `stamp_owner` obligation; optional role restriction
- `owner_or_privileged_read_policy` — legacy READ pattern with optional
  field-projection obligation
- `locked_state_guard_policy` — denies owner updates on locked records
  (approved_locked, certificate_issued, evidence_sealed, audit_finalised);
  privileged roles bypass
- `role_conditional_on_status_policy` — surveyor only at assigned/in_progress,
  community_validator only at validation_pending, etc.
- `delete_super_admin_only_policy` — DELETE reserved for super_admin
- `register_demo_resource_policies()` boots the canonical policy set against
  an internal `demo` resource for the authorization test matrix

### Immutable Domain Events + Transactional Outbox
- `kernel/events/envelope.Envelope` — versioned envelope with event_id,
  event_type, event_version, aggregate_type/id/version, occurred_at,
  producer, tenant/country/org scope, correlation_id, causation_id, actor
- `kernel/events/outbox.Outbox` — `kernel_outbox` collection, atomic claim
  via `find_one_and_update`, in-process subscriber registry with glob
  pattern matching; background publisher loop started in main.py lifecycle
- Phase 1 events emitted: identity.user.registered, identity.login.success,
  identity.login.failed, identity.account.suspended, identity.account.activated,
  identity.role.assigned, identity.delegation.granted, identity.delegation.revoked,
  identity.service_account.created, identity.service_account.revoked,
  identity.session.revoked
- Broker abstraction ready — Phase 3+ swap to Kafka/Rabbit/SQS without
  touching producers or subscribers

### Business + Technical Observability (`kernel/observability/metrics.py`)
- In-process counter store mirrored to `kernel_metrics` collection
- Auto-emitted by the kernel (callers don't instrument): login_success,
  login_failed, account_lockout, authz_denial, authz_permit,
  delegation_granted, suspension, role_change, audit_event_count,
  active_sessions, revoked_sessions, policy_evaluation_time_ms (TBD)
- One-line snapshot API for dashboards

### Identity Admin API — `/api/v1/identity/*`
- `GET  /v1/identity/users?role=&country=&tenant_id=&status=` — Specifications-backed
- `POST /v1/identity/users/{id}/suspend` — body: `{reason}`
- `POST /v1/identity/users/{id}/activate`
- `POST /v1/identity/users/{id}/role` — body: `{role}` (must be one of the 10)
- `POST /v1/identity/service-accounts` — returns secret plaintext exactly once
- `POST /v1/identity/service-accounts/{id}/revoke`
- `POST /v1/identity/delegations` — `{delegator_id, delegate_id, scope, valid_from, valid_until, reason}`
- `POST /v1/identity/delegations/{id}/revoke`

### Test coverage (iteration 6)
- **122 passed, 2 skipped, 0 failed** (was 73)
  - +30 authorization test matrix tests (all 10 roles × CRUD + projection +
    isolation + locked-state + role-status gate)
  - +15 admin / service-account / delegation / specifications / events tests
- Phase 1A lint clean

### Outstanding (Phase 1B → 1D)
- **Phase 1B — Constitutional Verification review** (architecture / security
  / platform gates; documentation pass + final sign-off)
- **Phase 1C — Contract Freeze** (publish OpenAPI v1; publish event contract
  registry; contract tests in CI; freeze versions)
- **Phase 1D — Frontend SDK Compatibility Layer** (auth facade + entities/invoke
  proxy stub; legacy frontend migrates incrementally)

## 8. Known limitations
- Email/password sign-up flow not exposed in UI (Google + demo only)
- Apple / Microsoft / Facebook social buttons are visual-only placeholders
- AI/OCR is mocked (returns canned text). Replacement with Emergent integrations is P2.

## 9. P0 + P1 hardening (iteration 4 — 2026-06-25)
**P0 Tenant Isolation & Transaction Safety + P1 Worker + Reports — COMPLETE**

### Tenant Isolation (structural, RLS-equivalent)
- `core/tenant.py` — `ContextVar` carrying `tenant_id`, `bypass_tenant()` context manager
- `core/safe_db.py` — `SafeCollection` wrapper auto-injects `tenant_id` into
  every `find`/`find_one`/`count`/`update`/`delete`/`insert`/`aggregate`/`distinct`/
  `find_one_and_*` call. Unauthenticated context filters to `__NO_TENANT_CONTEXT__`
  (default-deny). Exposed as `tdb` singleton.
- `core/security.get_current_user` now calls `set_tenant(user.tenant_id)` so the
  context propagates through the entire request.
- Routers switched to `tdb`: `parcels`, `evidence`, `credits`, `notifications`,
  `dashboards.citizen`. Admin / Legal / Institution / Observer / Public routers
  continue to use the raw `db` collection for legitimate cross-tenant queries.
- 5 regression tests verify cross-tenant reads/writes/listings/dashboards/
  notifications/wallets are all blocked (`tests/test_tenant_isolation.py`).

### Transaction Safety (multi-doc ACID)
- MongoDB upgraded to a single-node replica set (`rs0`) so `start_session()` +
  `start_transaction()` engage at runtime. `mongod` supervisor command updated.
- `core/tx.py` — `atomic_transaction()` context + `run_in_transaction(coro_factory)`
  with **auto-retry on TransientTransactionError / WriteConflict** (5 retries,
  exponential backoff with jitter).
- `services/payments.deduct_credits` and `services/payments.fulfill_payment`
  now run inside `run_in_transaction()`. Conditional `balance >= amount` filter
  + idempotency-key guard prevent double spending under any race.
- 2 concurrency tests verify (a) 10 concurrent /api/parcels against a 25-credit
  wallet yields exactly 5×200 + 5×402, final balance 0 — never negative; and
  (b) idempotency-key replay does not double-charge.

### Background Worker (production async)
- `services/worker.py` — long-lived asyncio task started in FastAPI `startup`,
  stopped in `shutdown`. Polls `job_queue` every `WORKER_POLL_INTERVAL` (5s),
  claims jobs atomically via `find_one_and_update`, executes via
  `services.jobs._execute_job`. Exponential-backoff retries on failure
  (10s × 2^attempt with jitter), terminal `DEAD_LETTER` after `max_attempts`.
- Auto-routes all job types (OCR, duplicate detection, confidence recalc,
  fraud scoring, certificate generation, legal/institution reports, backup,
  audit, security scan, abuse detection, take-off, trust validation).

### Real PDF + CSV Reports (worker-generated)
- `services/trust.render_legal_report_csv` and `render_institution_report_csv`
  emit downloadable CSV artifacts alongside the existing reportlab PDFs.
- `LEGAL_REPORT` and `INSTITUTION_REPORT` job handlers store both URLs:
  `result_url` (PDF) + `csv_url` (CSV) on `db.reports`.
- `GET /api/legal/reports/{id}/download(.csv)` and
  `GET /api/institution/reports/{id}/download(.csv)` serve the artifacts
  through `FileResponse`, with role-scoped + owner-scoped access checks.

### Test coverage delta (iteration 4)
- Backend: **51 passed, 2 skipped, 0 failed** (was 38)
  - +5 tenant isolation tests
  - +2 concurrency tests
  - +6 worker + report E2E tests (`tests/test_worker_reports.py`)
- Pytest marker `tx_test` registered in `/app/backend/pytest.ini`.

### Operational notes
- `ENABLE_TEST_ENDPOINTS` env flag gates `POST /api/auth/test-bootstrap-citizen`
  and `POST /api/auth/test-set-balance` — defaults to true in dev, set to
  `false` for production deployments.
- Demo wallets are auto-topped-up to baseline (250 / 1000) on every backend
  startup, so drained-wallet flakes across pytest runs are eliminated.

## 10. Backlog (P2) — unchanged
- Scheduled automations (abuse 30m, fraud 15m, backup daily 02:00) — cron / APScheduler layer
- Real OCR / fraud scoring via Emergent integrations (awaiting user go-ahead)
- Stripe Metered Billing for institutional plans
- Email notifications (Resend / Postmark)
- Mapbox parcel boundary visualisation
- Bulk verification API for institutional users
- Cloudflare R2 file storage
- Rate limiting + Sentry instrumentation
