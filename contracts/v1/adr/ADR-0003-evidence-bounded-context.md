# ADR-0003 — Evidence Bounded Context (Phase 3 / amends Phase 0 ADR-015)

* **Status:** Proposed (blocking on Phase 3.0 sign-off)
* **Date:** 2026-06-28
* **Contract version introduced:** `1.2.0` (additive minor)
* **Authors:** Platform team
* **Supersedes:** —
* **Amends:** Phase 0 Foundation Spec ADR-015 ("Evidence is a bounded context")
* **Related:** ADR-0001 (Contract Freeze), ADR-0002 (Registry), ADR-0004/0005/0006 (Phase 3 binding additions)

## Context

The Phase 0 Foundation Specification established Evidence as a bounded
context that references LandVault `registry_id` via events only. Phase 2A
shipped Registry as the canonical aggregate. Phase 3 must now realize
Evidence on top of the frozen Phase 1C platform contract and the Phase 2A
event stream, without coupling either way at the code level.

## Decision

Create a new bounded context at `backend/contexts/evidence/` with the
following invariant contract:

1. **Source of truth.** Evidence is the sole authority for its aggregates
   (`EvidenceItem`, `Seal`, `LegalHold`, `AnchorBatch`, `OrphanRecord`).
   No code outside this context may write these collections.
2. **Reference, never write.** Evidence references `registry_id` but
   never writes Registry collections. Where Evidence needs Registry
   facts, it subscribes to Registry events through the outbox.
3. **Immutable once sealed.** A `Seal` is constructed from already-
   verified `EvidenceItem`s. After `Seal.apply_worm()` the items and the
   manifest are jointly immutable. Modifications require the
   verify-then-cutover remediation saga (ADR-0006).
4. **No binaries in documents.** Mongo stores metadata + hashes +
   provenance. The bytes live behind `StoragePort` (LocalFs WORM in dev;
   Cloudflare R2 in production).
5. **Append-only logs.** Timeline, integrity, lock, custody collections
   are insert-only with cryptographic chaining (each entry's
   `entry_hash = sha256(prev_hash || canonical_json(entry))`).
6. **Aggregate ownership of events.** Only the aggregate root raises
   domain events. Repositories are persistence-only. The application
   service publishes via the existing transactional outbox in the same
   Mongo session as the write.
7. **Provider interfaces only.** `StoragePort`, `EncryptionPort`,
   `AnchorPort`, `SignedUrlPort`. Adapters can be swapped without
   touching the domain. The test suite exercises in-memory and LocalFs
   adapters; production exercises R2 + CT-log + OTS.
8. **Tenant + country scoping.** Identical defense-in-depth to Registry:
   `tenant_id` and `country_code` are derived from the ExecutionContext;
   the repository filters every query by both; super_admin bypass is
   audited.
9. **Centralized authorization.** Every endpoint goes through
   `enforce(action, resource)`. Owner / role / scope checks live in the
   centralized PDP (with `evidence.*` policies registered at startup);
   the aggregate enforces invariants as a second layer.
10. **Versioned contracts.** All new endpoints, schemas, events,
    security entries are appended to the frozen contract package; the
    drift gate stays green; the contract bumps to `1.2.0`.

## Consequences

### Positive

* Evidence can evolve independently of Registry. Adding a new evidence
  source (e.g. drone imagery) is a one-context change.
* The same kernel primitives (audit, outbox, PEP, observability) are
  reused — Phase 3 doesn't pay platform tax again.
* Court admissibility becomes a property of the contract package
  (manifest + Merkle root + inclusion proof + offline verifier are all
  versioned and SHA-pinned).

### Negative / Trade-offs

* Three additional ADRs (0004, 0005, 0006) are required to encode the
  binding behavioural rules; without them this ADR is incomplete.
* Subscribers to Registry events must be designed for at-least-once
  delivery and idempotent processing (the outbox already guarantees the
  former; consumers handle the latter).

## Compliance

* `tests/test_evidence_bounded_context.py` will assert structural
  isolation: no import from `contexts.evidence` references
  `contexts.registry.application` or writes Registry collections.
* The Phase Acceptance Review packet records the result.
