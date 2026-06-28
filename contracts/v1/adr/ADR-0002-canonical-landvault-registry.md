# ADR-0002 — Canonical LandVault Registry (Phase 2A)

* **Status:** Accepted
* **Date:** 2026-06-28
* **Contract version introduced:** `1.1.0` (additive minor — see CHANGELOG.md)
* **Authors:** Platform team
* **Supersedes:** —
* **Related:** ADR-0001 (Platform Contract Freeze), ADR-001 / ADR-014 of the
  Phase 0 Foundation Specification.

## Context

Phase 1 established the Platform Kernel and the Identity bounded context.
Phase 1C froze the public contract at `v1.0.0`. Phase 2A introduces the
**first business bounded context** — the canonical land-record Registry —
built strictly on top of the frozen platform contract.

Legacy code maintained two parallel land-record collections (`parcels` and
`land_vault_parcels`) with overlapping fields, divergent identifiers, and
implicit cross-context coupling. This violates ADR-001 ("Registry is the
authoritative aggregate") and ADR-014 ("`registry_id` is the internal
identity; `parcel_number` is the public reference; legacy identifiers are
aliases only").

## Decision

Introduce a single Registry bounded context at `backend/contexts/registry/`
with the following structure (mirrors the Identity context):

```text
contexts/registry/
├── domain/
│   ├── value_objects.py     # ParcelNumber, OwnershipType, Geometry, Origin, …
│   ├── events.py            # 5 immutable, versioned domain events
│   ├── invariants.py        # ImmutableFieldError, LockedStateError, …
│   └── land_vault.py        # The aggregate root
├── ports/
│   ├── repository.py        # LandVaultRepository, RegistryNumberAllocator
│   └── specifications.py    # Composable LandVaultSpec
├── adapters/
│   ├── mongo_repository.py  # 2dsphere, unique indexes, scope filter
│   └── mongo_allocator.py   # Atomic findOneAndUpdate $inc + upsert
├── application/             # RegistryCommandService + RegistryQueryService
├── api/                     # Per-role Pydantic DTOs + FastAPI router
└── authorization.py         # 5 PDP policies
```

Surfaced at `/api/v1/registry/landvaults` with **task-oriented commands**:

* `POST /` — create
* `PATCH /{id}/location` — UpdateLocation
* `PATCH /{id}/geometry` — UpdateGeometry (validated GeoJSON Polygon WGS84)
* `PATCH /{id}/ownership-contact` — UpdateOwnershipContact (NO OwnershipRecorded)
* `POST /{id}/ownership-transfer` — RecordOwnershipTransfer (legal change → OwnershipRecorded)
* `PATCH /{id}/survey` — UpdateSurvey
* `PATCH /{id}/community-data` — UpdateCommunityData
* `POST /{id}/archive` — ArchiveLandVault (super_admin only, one-way)

### Binding invariants (enforced inside the aggregate)

| Invariant                          | Mechanism                                   |
| ---------------------------------- | ------------------------------------------- |
| `registry_id` immutable            | `_apply_patch` raises `ImmutableFieldError` |
| `parcel_number` immutable          | same                                        |
| `tenant_id` / `country_code` immutable | same                                    |
| `created_at` / `origin.*` immutable    | same                                    |
| `version` monotonic                | `_bump()` is the only mutator               |
| `schema_version` non-decreasing    | no setter exposed                           |
| `deleted_at` / `archived` one-way  | `archive()` rejects second call             |
| OwnershipHistory append-only       | no remove/replace API                       |

### Domain events (additive to the catalog at v1.1.0)

* `registry.landvault.created.v1`
* `registry.landvault.updated.v1`
* `registry.parcel_reference.allocated.v1`
* `registry.ownership.recorded.v1` — emitted ONLY on legal ownership
  changes (not on phone/email edits — Phase 2A architectural §3).
* `registry.landvault.archived.v1`

All five published via the existing transactional outbox inside the same
Mongo session as the aggregate write.

### Parcel-number allocation (§6)

Atomic `find_one_and_update` with `$inc` and `upsert` on
`landvault_sequence_counters`, keyed by `STATE-LGA-WARD-PROPTYPE`. Zero-
padded 6-digit sequence. **Concurrency test:** 50 parallel allocations on
the same key → 50 unique numbers, 0 duplicates, contiguous `1..50` range.

### Authorization (§9)

Five new PDP policies registered at startup. Decisions are role-based at
the edge; ownership / locked-state / tenant isolation are enforced by the
aggregate and the repository (defense in depth).

### Indexes (§3.4)

`landvault_landvaults` collection ships with:
* unique `registry_id`, unique `parcel_number`
* sparse `legacy_aliases`
* compound `(country_code, tenant_id)` and `(country_code, tenant_id, status)`
* `2dsphere` on `geometry`
* `(origin.source_system, origin.source_id)` for migration idempotency
* operational indexes on `status`, `created_at`, `owner_email`,
  `field_agent_email`, `surveyor_id`, `created_by`

## Consequences

### Positive

* A single authoritative aggregate replaces two divergent legacy
  collections. New domains (Evidence, Verification, Community, Economics,
  Certificates, GIS) consume immutable events instead of cross-coupling.
* Concurrency-safe parcel-number allocation with zero risk of duplicates.
* PII / projection rules are machine-readable
  (`contracts/v1/security/field_projection.json:registry.land_vault`) and
  shared between backend and frontend.
* Contract bumped to `1.1.0` (additive minor) — every consumer using the
  frozen `1.0.0` baseline continues to work.

### Negative

* The legacy `/api/parcels` endpoints remain operational during the
  migration period and need a compatibility adapter that delegates writes
  to the Registry (separate change, tracked under Phase 2B).
* Migration of existing legacy rows requires a separate, idempotent tool
  that quarantines duplicates instead of auto-merging — also tracked
  under Phase 2B.

## CI enforcement

* `tests/test_contract_freeze.py` — strict drift gate. Refreshed for
  `1.1.0`; every registry artifact has a SHA256 fingerprint pinned in
  `v1/sdk/contract.sha256`.
* `tests/test_registry_aggregate_invariants.py` — pure-Python invariant
  tests (22 cases).
* `tests/test_registry_geometry_validation.py` — 6 cases.
* `tests/test_registry_allocator_concurrency.py` — 4 cases, including a
  50-way parallel allocation race.
* `tests/test_registry_api.py` — 14 cases covering the full
  authorization matrix, tenant isolation, locked-state guard,
  ownership-event discipline, event publication, audit, 2dsphere query,
  mass-assignment, and alias non-authoritativeness.
