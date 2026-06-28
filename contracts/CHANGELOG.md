# Aquasavannah LandVault — Contract Changelog

All notable changes to the **platform contract package** are recorded here.

The contract is governed by [Semantic Versioning](https://semver.org/):
* **MAJOR** — breaking changes to `/api/v1/*` (renames, removals, type changes).
* **MINOR** — additive, backwards-compatible (new endpoints, new optional fields, new events).
* **PATCH** — clarifications and bug fixes that do not change the wire format.

Every entry below MUST reference its ADR.

---

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
