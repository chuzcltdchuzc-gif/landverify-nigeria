# Aquasavannah LandVault — Legacy API Deprecation Policy

_Effective: contract version `1.0.0` (Phase 1C — Platform Contract Freeze)_

This document is binding. It governs every endpoint published under
`/api/*` that is **not** under `/api/v1/*` (the canonical platform contract).

---

## 1. Status of legacy endpoints

Every endpoint NOT prefixed with `/api/v1/` is **deprecated**:

* The frozen OpenAPI document (`v1/openapi.json`) marks each such operation
  with `deprecated: true` and tags it `legacy`.
* The Event Catalog and per-event schemas do **not** include events emitted
  by legacy routes — legacy producers are excluded from the canonical event
  stream and may be retired at any minor version bump of the contract.

## 2. Permitted changes to legacy endpoints

While deprecated, legacy endpoints receive **bug fixes only**:

| Change type                                | Allowed on `/api/*` (legacy) | Allowed on `/api/v1/*` |
| ------------------------------------------ | ---------------------------- | ---------------------- |
| Security or correctness bug fix            | **YES**                      | YES                    |
| Performance fix (no observable API change) | **YES**                      | YES                    |
| Adding a NEW endpoint                      | **NO**                       | YES (additive)         |
| Adding NEW required field                  | **NO**                       | **NO** (breaking)      |
| Adding NEW optional field                  | **NO**                       | YES (additive, minor)  |
| Removing/renaming a field                  | **NO**                       | **NO** (breaking)      |
| Changing response shape or status code     | **NO**                       | **NO** (breaking)      |
| Removing an endpoint                       | Major version bump only      | Major version bump only|

Any change that is forbidden above MUST be implemented on `/api/v1/*` and
the legacy route MUST remain byte-compatible.

## 3. Forward-compatibility guarantees

* Legacy routes will continue to function until the next **major** contract
  version (e.g. `2.0.0`).
* SDK consumers can rely on legacy routes for the lifetime of the current
  major version, subject only to security patches.
* No legacy route will silently change its contract — see §4.

## 4. Drift enforcement (CI)

The contract-drift gate compares both surfaces:

1. **`/api/v1/*` surface** — strict equality with the frozen artifacts.
   Any deviation MUST come with: semver bump, CHANGELOG entry, ADR
   reference, regenerated SDK metadata, and updated SHA256 fingerprints.
2. **`/api/*` legacy surface** — also strict equality (deprecated routes
   are frozen too). Adding/removing/changing a legacy operation fails CI
   the same way as a v1 change. The only legitimate path to alter a legacy
   route is via the bug-fix rule in §2, which still requires a CHANGELOG
   entry and a regenerated freeze.

## 5. Sunset procedure

A legacy endpoint may be removed only when ALL of the following are met:

1. The replacement `/api/v1/*` endpoint has been live for at least one
   minor version cycle.
2. An ADR documents the migration plan and consumer impact.
3. The change is shipped in a **major** contract version (e.g. `2.0.0`).
4. The CHANGELOG carries an explicit `BREAKING` section listing the
   sunset endpoint(s).

## 6. New development

**All new functionality MUST target `/api/v1/*`.**

No new feature, no new field, no new endpoint may be added to `/api/*`
legacy routes. Reviewers must reject any pull request that does so.
