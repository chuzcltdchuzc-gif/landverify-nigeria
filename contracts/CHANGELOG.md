# Aquasavannah LandVault — Contract Changelog

All notable changes to the **platform contract package** are recorded here.

The contract is governed by [Semantic Versioning](https://semver.org/):
* **MAJOR** — breaking changes to `/api/v1/*` (renames, removals, type changes).
* **MINOR** — additive, backwards-compatible (new endpoints, new optional fields, new events).
* **PATCH** — clarifications and bug fixes that do not change the wire format.

Every entry below MUST reference its ADR.

---

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
