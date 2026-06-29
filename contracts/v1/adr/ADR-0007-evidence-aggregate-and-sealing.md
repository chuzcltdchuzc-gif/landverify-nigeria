# ADR-0007 — Canonical Evidence Aggregate + Sealing (Phase 3.4 + 3.5)

*Status*: Accepted. Lands with contract package version **1.2.0** (additive minor).
*Context*: Aquasavannah LandVault — Phase 3 Definitive Delivery Spec, steps 3.4 + 3.5.
*Depends on*: ADR-0003 (Evidence bounded context), ADR-0004 (server-side hashing), ADR-0005 (Merkle anchor saga — strictly future-dated), ADR-0006 (legal hold + remediation).

---

## 1. Decision

Combine Phase 3.4 (Canonical EvidenceItem aggregate) and Phase 3.5 (Seal manifest aggregate + WORM lockdown) into a single, atomic milestone, shipped as **contract bump 1.1.0 → 1.2.0**.

### 1.1 EvidenceItem aggregate

* Aggregate root for one evidentiary binary's metadata. Binaries themselves NEVER live in MongoDB.
* Immutable fields: `evidence_id`, `registry_id`, `tenant_id`, `country_code`, `created_at`, `created_by`, `origin`, `kind`.
* Lifecycle is a strict one-way FSM:

  ```text
  pending_upload → pending_verification → verified → sealed → archived_replaced
  ```
* Commands: `attach_upload_session`, `mark_uploaded`, `verify_hash`, `attach_to_seal`, `archive_replaced`, `record_signed_url_issuance`.
* Hash discipline (binding):
  * Server hashes are authoritative (streamed-during-write `server_hash_streamed` and independent read-back `server_hash`).
  * Client hashes are recorded as **claims only** — mismatch is a hard `409 evidence.hash_mismatch` and rolls the aggregate back to `pending_upload`.
  * Both mismatches emit an `evidence.item.hash_mismatch.v1` integrity event regardless of the rollback.

### 1.2 Seal aggregate

* The Seal is the **immutable manifest** the directive recommends. One Seal groups N verified EvidenceItems.
* Manifest fields are FROZEN at construction. Only `status`, `anchor_batch_id` (write-once), `worm_applied_at`, `archived_at`, and the version counters may advance.
* Status FSM:

  ```text
  created → worm_applied → archived
  ```
* `merkle_root` = canonical merkle tree over the sorted server hashes (bitcoin-style duplication for odd levels).
* `manifest_hash` = sha256 of the canonical JSON (sorted keys, no whitespace) manifest doc.
* `apply_worm()` is the **single WORM gate**: the Application Service invokes `StoragePort.apply_object_lock` on every referenced item BEFORE flipping the status; the per-item lock outcome is recorded in the `evidence.seal.worm_applied.v1` event.

### 1.3 API surface (`/api/v1/evidence/*`)

| Method | Path                                           | Purpose                                  |
| ------ | ---------------------------------------------- | ---------------------------------------- |
| POST   | `/items`                                       | Initiate multipart upload                |
| PUT    | `/items/{id}/parts/{part_no}`                  | Stream a part                            |
| POST   | `/items/{id}/complete`                         | Finalize multipart                       |
| POST   | `/items/{id}/verify`                           | Read-back + hash verification            |
| GET    | `/items/{id}`                                  | Read metadata (role-projected)           |
| GET    | `/items`                                       | List scoped by ExecutionContext          |
| POST   | `/items/{id}/signed-url`                       | Issue short-lived signed URL             |
| POST   | `/seals`                                       | Create immutable seal                    |
| POST   | `/seals/{id}/apply-worm`                       | Flip the WORM gate                       |
| GET    | `/seals/{id}`                                  | Read manifest (role-projected)           |

### 1.4 Authorization (PDP policies)

Eight new actions wired through the centralized PDP, default-DENY, per-role gates aligned with ADR-0003 §3:

* `evidence.item.upload.initiate` / `.complete` — UPLOAD_ROLES
* `evidence.item.verify` — UPLOAD_ROLES ∪ READ_PRIVILEGED_ROLES
* `evidence.item.read`, `.list`, `.read.signed_url` — privileged + operational + creator-of-resource
* `evidence.seal.create` — SEAL_CREATE_ROLES
* `evidence.seal.apply_worm` — SEAL_WORM_ROLES (super_admin, compliance_officer)
* `evidence.seal.read` — privileged + operational

Tenant + country scoping is enforced inside the repository regardless of role (defense-in-depth identical to Registry).

### 1.5 Domain events (8 new)

Published via the transactional outbox in the SAME Mongo session as the aggregate write:

* `evidence.item.uploaded.v1`
* `evidence.item.hash_verified.v1`
* `evidence.item.hash_mismatch.v1`
* `evidence.item.archived_replaced.v1`
* `evidence.seal.created.v1`
* `evidence.seal.worm_applied.v1`
* `evidence.seal.archived.v1`
* `evidence.signed_url.issued.v1`

Every payload carries `registry_id` so consumers can fan out per LandVault.

### 1.6 Contract bump 1.1.0 → 1.2.0

Additive minor only. New artifacts:

* 5 new request DTOs frozen as independent JSON Schemas
* 5 new response DTOs frozen
* 8 new domain events with full envelope JSON Schemas
* `evidence_actions` block in `security/permissions.json`
* `evidence.item` + `evidence.seal` field projections in `security/field_projection.json`
* SHA256 fingerprints refreshed, drift gate re-greened

70 contract artifacts (up from 52 at 1.1.0).

## 2. Strict non-goals (Phase 3.4 + 3.5)

* **No anchoring.** `anchor_batch_id` is a placeholder field that no command in this milestone may set. Phase 3.6 ships the CT-log saga + OTS adapter behind a separate ADR.
* **No legal hold.** Phase 3.9 territory.
* **No retention sweeper.** Retention timestamps are recorded for future-Phase-3.6 consumption; nothing in this milestone deletes WORM-locked bytes.
* **No remediation cutover endpoint.** `archive_replaced` lives on the aggregate (so Phase 3.3 saga can call it programmatically) but no HTTP endpoint exposes it in this milestone.
* **No timeline collection.** Timeline + custody + integrity append-only logs land at Phase 3.7.

## 3. Consequences

### 3.1 Positives

* Evidentiary records become first-class, immutable aggregates with WORM lockdown.
* Server-side hash discipline is invariant-protected from end to end; no surface lets a client claim a hash without server verification.
* Seal creation is atomic with item status transition — either all referenced items move from `verified` → `sealed` and the seal lands, or none do.
* The transactional outbox guarantees at-least-once delivery of the 8 new event types to downstream consumers (verification, certificate, audit-log, metrics).

### 3.2 Negatives / costs

* The `apply_worm` operation is fan-out work (N storage adapter calls per seal). For N > ~500 items per seal we'll need a sub-saga; we cap seal size at 500 items in the DTO for v1.
* The streaming upload path runs entirely inside FastAPI workers; we'll need to revisit when we move R2 to production sigv4.

## 4. Acceptance gates (all green)

1. EvidenceItem immutables cannot be mutated post-construction (`ImmutableFieldError`).
2. Status FSM is one-way; out-of-order transitions raise `TransitionError → 409`.
3. Tampered `client_hash_claim` is recorded as `hash_mismatch` event and returns `409 evidence.hash_mismatch`.
4. Sealing requires all referenced items in `verified`; mixed status → `409 evidence.seal.unverified_item`.
5. `merkle_root` and `manifest_hash` are deterministic regardless of input order.
6. After `apply_worm`, the LocalFs WORM adapter refuses overwrite/re-initiate on every referenced storage object.
7. Once `status == sealed`, every command on the EvidenceItem raises `SealedItemError → 409 evidence.sealed_immutable`.
8. Contract drift gate green at 1.2.0; SHA256 fingerprints refreshed; full backend regression passes.

## 5. References

* `/app/memory/PHASE3_SPEC.md` §3.4 + §3.5
* `/app/memory/PHASE3_BLUEPRINT.md` §1, §2, §3
* ADR-0003 (Evidence bounded context)
* ADR-0004 (server-side hashing)
* ADR-0006 (legal hold + remediation — provides the supersession contract used by `archive_replaced`)

---

*Signed*: Phase 3.4 + 3.5 milestone — 2026-06-29
