# Aquasavannah LandVault — Contract Changelog

All notable changes to the **platform contract package** are recorded here.

The contract is governed by [Semantic Versioning](https://semver.org/):
* **MAJOR** — breaking changes to `/api/v1/*` (renames, removals, type changes).
* **MINOR** — additive, backwards-compatible (new endpoints, new optional fields, new events).
* **PATCH** — clarifications and bug fixes that do not change the wire format.

Every entry below MUST reference its ADR.

---

## [1.4.0] — 2026-06-29 — Phase 3.7: Timeline + Custody + Legal Hold + Supersession

* **ADR-0009 — Timeline, Custody, Legal Hold, Supersession**:
  introduces three append-only chained aggregates
  (`TimelineEntry`, `CustodyEntry`, `LegalHold`) and the supersession
  graph navigation API over the existing `EvidenceItem.replaced_by`
  chain. Timeline is auto-projected from the outbox event stream; the
  `TimelineProjector` subscriber is registered against `evidence.*`.
* **Additive (`/api/v1/*`)** — 8 new endpoints under `/api/v1/evidence`:
  * `GET /items/{id}/timeline`
  * `GET /items/{id}/custody` + `POST /items/{id}/custody`
  * `GET /items/{id}/supersession-chain`
  * `GET /items/{id}/legal-holds` + `POST /items/{id}/legal-holds`
  * `GET /legal-holds/{id}` + `POST /legal-holds/{id}/release`
* **Additive (events)** — 5 new domain events:
  `evidence.timeline.appended`, `evidence.custody.appended`,
  `evidence.legal_hold.applied`, `evidence.legal_hold.released`,
  `evidence.supersession.recorded` (all v1).
* **Additive (security)** — 6 new actions in `evidence_actions`
  (`evidence.timeline.read`, `evidence.custody.read`,
  `evidence.custody.record`, `evidence.legal_hold.read`,
  `evidence.legal_hold.apply`, `evidence.legal_hold.release`).
  Hold apply/release restricted to `super_admin` + `compliance_officer`.
* **Invariants**: timeline + custody chains are append-only (adapter
  refuses update/delete); LegalHold `active → released` is a one-way
  transition (release-twice → 409); supersession graph is forever
  navigable; chain-link verification primitive shared with Phase 3.6
  integrity (offline verifier can replay independently).
* **Drift gate** updated — 96 frozen artifacts at 1.4.0 (up from 91).
  Backward-compatible with 1.3.0 / 1.2.0 / 1.1.0 / 1.0.0 consumers.

## [1.3.0] — 2026-06-29 — Phase 3.6: Anchoring, Integrity & Locking

* **ADR-0008 — Evidence Anchoring & Integrity Saga**: introduces three
  new aggregates under `backend/contexts/evidence/`:
  * `EvidenceLock` — first-class WORM lock aggregate, forward-only
    retention extensions, append-only `extensions[]` history.
  * `EvidenceIntegrityCheck` — immutable, chained (`prev_hash` /
    `entry_hash`) hash re-verification log. Ten-value `triggered_by`
    enum per §15 Decision 4: scheduled (30d baseline) + 7 mandatory
    triggers (pre_certificate, pre_public_verification,
    pre_ownership_transfer, pre_subdivision, post_storage_migration,
    on_demand, security_incident) + pre_seal + post_remediation.
  * `AnchorBatch` — saga aggregate with the eight-state FSM from
    ADR-0008 §6: `pending_batch → sealed → submitted → confirming →
    confirmed | failed → dead_letter → replay`. Replay produces a NEW
    batch row; the original DLQ row stays frozen forever.
* **Two new ports**: `AnchorPort` (`ctlog_internal` primary +
  `ots_v1` secondary, sharing zero domain code) and
  `CheckpointPublisherPort` (local-FS dev default; R2/IPFS/both via
  fan-out in production, operator-configured via
  `EVIDENCE_CHECKPOINT_PUBLISHERS`).
* **Anchoring saga**: batcher (60s, auto-split at 256 seals),
  confirmer (CAS-claim, exponential backoff
  `[10s, 60s, 5min, 1h, 6h, 24h]`, max 12 attempts → DLQ),
  super_admin replay endpoint, idempotent over `(batch_id,
  merkle_root)`, resumable across worker restarts.
* **CT-log internal adapter**: append-only `evidence_ctlog_tree` of
  leaves with monotonic `leaf_seq`, daily signed-tree-head publisher
  to `evidence_ctlog_checkpoints` + the external
  `CheckpointPublisherPort`. Inclusion proofs computed deterministically
  via bitcoin-style audit paths.
* **OpenTimestamps adapter**: configurable calendar list, **2-of-N
  quorum**, single-calendar failure does NOT fail the saga. Stub
  fetcher for dev; real network calls land under `OTS_NETWORK_TESTS=1`.
* **Additive (`/api/v1/*`)** — 10 new endpoints under
  `/api/v1/evidence`:
  * `GET /anchor-batches/{batch_id}`
  * `GET /anchor-batches/by-seal/{seal_id}`
  * `GET /anchor-batches?state=…`
  * `POST /anchor-batches/{batch_id}/replay` (super_admin only)
  * `GET /locks/{lock_id}`
  * `GET /locks/by-evidence/{evidence_id}`
  * `POST /locks/{lock_id}/extend` (super_admin + compliance_officer)
  * `POST /integrity-checks` (on-demand or mandatory-trigger)
  * `GET /integrity-checks/{check_id}`
  * `GET /integrity-checks/by-evidence/{evidence_id}`
  * `GET /ctlog/checkpoints/latest`
* **Additive (events)** — 12 new domain events: `evidence.lock.applied`,
  `evidence.lock.extended`, `evidence.integrity.check_started`,
  `evidence.integrity.passed`, `evidence.integrity.failed`,
  `evidence.integrity.check_errored`, `evidence.anchor.batched`,
  `evidence.anchor.submitted`, `evidence.anchor.confirmed`,
  `evidence.anchor.failed`, `evidence.anchor.replayed`,
  `evidence.ctlog.checkpoint_published` (all v1).
* **Additive (schemas)** — 3 new request DTOs + 7 new response DTOs
  frozen as independent JSON Schemas.
* **Additive (security)** — 7 new actions in the `evidence_actions`
  block of `v1/security/permissions.json` and 3 new aggregate
  projections (`evidence.lock`, `evidence.integrity_check`,
  `evidence.anchor_batch`) in `v1/security/field_projection.json`.
* **Constitutional invariants** (ADR-0008 §15): twelve binding rules
  with named tests. Evidence remains immutable after sealing;
  Registry is never mutated by Evidence; cross-context communication
  via events only; anchor records append-only; Merkle roots
  deterministic; CT-log primary; OTS secondary independent;
  replay idempotent; DLQ resumable; complete audit coverage; no
  binaries in MongoDB; no PII in checkpoints/anchor metadata.
* **Drift gate** updated — contract package fingerprints refreshed
  for 1.3.0. Existing Phase 1/2/3.4/3.5 artifacts remain backward
  compatible; consumers on 1.0.0/1.1.0/1.2.0 continue to work
  unchanged.

## [1.2.0] — 2026-06-29 — Phase 3.4 + 3.5: Canonical Evidence Aggregate + Sealing

* **ADR-0007 — Canonical Evidence Aggregate + Sealing**: introduces the
  `EvidenceItem` and `Seal` aggregate roots under
  `backend/contexts/evidence/`. Binaries never live in MongoDB; the
  aggregate references storage objects via `StoragePort` (`local_fs_worm`
  in dev, `r2` in production). Server hashes are authoritative; client
  hashes are recorded as **claims only**. Once a Seal applies WORM, the
  StoragePort Object-Lock is active for every referenced item; the seal
  can never be deleted.
* **Additive (`/api/v1/*`)** — 10 new endpoints under
  `/api/v1/evidence`:
  * `POST /items` — initiate multipart upload (returns `evidence_id` +
    `upload_id`).
  * `PUT /items/{id}/parts/{part_no}` — stream a part (server computes
    a running SHA-256).
  * `POST /items/{id}/complete` — finalize multipart; status moves to
    `pending_verification`.
  * `POST /items/{id}/verify` — independent server-side read-back +
    SHA-256 verification; status moves to `verified`.
  * `GET /items/{id}` — read EvidenceItem metadata (role-projected).
  * `GET /items` — list scoped by ExecutionContext.
  * `POST /items/{id}/signed-url` — issue a short-lived signed URL;
    audit row persists BEFORE the URL leaves the server.
  * `POST /seals` — create immutable Seal manifest over verified items
    (computes `merkle_root` + `manifest_hash`).
  * `POST /seals/{id}/apply-worm` — flip the WORM gate; fans out
    `apply_object_lock` to every referenced item.
  * `GET /seals/{id}` — read Seal manifest (role-projected).
* **Additive (events)** — 8 new domain events:
  * `evidence.item.uploaded.v1`
  * `evidence.item.hash_verified.v1`
  * `evidence.item.hash_mismatch.v1`
  * `evidence.item.archived_replaced.v1`
  * `evidence.seal.created.v1`
  * `evidence.seal.worm_applied.v1`
  * `evidence.seal.archived.v1`
  * `evidence.signed_url.issued.v1`
* **Additive (schemas)** — 5 new request DTOs + 5 new response DTOs
  frozen as independent JSON Schemas under `v1/schemas/`. The
  generator now inlines nested `$ref` components so every DTO is
  self-contained.
* **Additive (security)** — new `evidence_actions` block in
  `v1/security/permissions.json`; new `evidence.item` and
  `evidence.seal` projections in `v1/security/field_projection.json`.
* **Drift gate** updated — 70 artifacts pinned by SHA256 (up from 52
  at 1.1.0). Existing Phase 1 + Phase 2A artifacts remain
  backward-compatible; consumers on `1.0.0` / `1.1.0` continue to work
  without changes.

## [1.1.0] — 2026-06-28 — Phase 2A: Canonical LandVault Registry

* **ADR-0002 — Canonical LandVault Registry**: introduces the first
  business bounded context (`backend/contexts/registry/`) on top of the
  frozen Phase 1C platform. LandVault is the single authoritative
  aggregate root for land records (per ADR-001 / ADR-014). Legacy
  identifiers remain as `legacy_aliases[]` lookups only — never
  authoritative.
* **Additive (`/api/v1/*`)** — 9 new endpoints under
  `/api/v1/registry/landvaults`:
  * `POST /` — create LandVault (allocates `parcel_number` atomically)
  * `GET /` — list (scoped by ExecutionContext)
  * `GET /{registry_id}` — read (role-projected)
  * `PATCH /{registry_id}/location` — UpdateLocation
  * `PATCH /{registry_id}/geometry` — UpdateGeometry (GeoJSON Polygon, WGS84)
  * `PATCH /{registry_id}/ownership-contact` — UpdateOwnershipContact
  * `POST /{registry_id}/ownership-transfer` — RecordOwnershipTransfer
  * `PATCH /{registry_id}/survey` — UpdateSurvey
  * `PATCH /{registry_id}/community-data` — UpdateCommunityData
  * `POST /{registry_id}/archive` — ArchiveLandVault (super_admin only)
* **Additive (events)** — 5 new domain events in the Event Catalog,
  emitted via the existing transactional outbox:
  * `registry.landvault.created.v1`
  * `registry.landvault.updated.v1`
  * `registry.parcel_reference.allocated.v1`
  * `registry.ownership.recorded.v1` (emitted ONLY on legal ownership
    changes — not on phone/email edits, per architectural directive §3)
  * `registry.landvault.archived.v1`
* **Additive (schemas)** — 8 new request DTOs + 2 new response DTOs
  frozen as independent JSON Schemas under `v1/schemas/`.
* **Additive (security)** — new `registry_actions` entries in
  `v1/security/permissions.json`; new `registry.land_vault` projection
  in `v1/security/field_projection.json`.
* **Drift gate** updated — every new artifact pinned by SHA256 in
  `v1/sdk/contract.sha256`. The frozen `v1/openapi.json` and existing
  Phase 1 artifacts remain backward-compatible; consumers on `1.0.0`
  continue to work without changes.

## [1.0.0] — 2026-06-28 — Platform Contract Freeze

* **ADR-0001 — Platform Contract Freeze**: First publication of the
  constitutional interface for AquaSavannah LandVault. From this point
  on, all consumers (web SPA, future mobile, SDK clients, partner
  government systems) build against this frozen package.
* Snapshot of `/api/v1/*` (canonical) and `/api/*` (legacy) surfaces.
* `/api/v1/*` endpoints declared **canonical, supported, and additive-only**
  until the next minor version bump.
* All `/api/*` non-v1 endpoints marked `deprecated: true` in the frozen
  OpenAPI document and governed by `deprecation-policy.md`.
* Freezes the following independently-versioned artifacts:
    * `v1/openapi.json` (canonical OpenAPI 3.x)
    * `v1/schemas/requests/*.json` (per-DTO JSON Schemas — request bodies)
    * `v1/schemas/responses/*.json` (per-DTO JSON Schemas — responses)
    * `v1/errors/*.json` (RFC 7807 problem+json contracts)
    * `v1/events/catalog.json` and `v1/events/*.v1.json` (Domain Event Catalog)
    * `v1/security/permissions.json`, `role_matrix.json`, `field_projection.json`
    * `v1/sdk/sdk.version`, `compatibility.json`, `contract.sha256`
* Adds **strict contract-drift CI gate** (`tests/test_contract_freeze.py`
  + `contracts/ci_check_drift.sh`). Any deviation from the frozen
  artifacts fails CI until the change is accompanied by an explicit
  version bump and a CHANGELOG entry that references its ADR.
