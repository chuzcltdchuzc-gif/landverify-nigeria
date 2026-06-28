# ADR-0001 — Platform Contract Freeze (Phase 1C)

* **Status:** Accepted
* **Date:** 2026-06-28
* **Contract version introduced:** `1.0.0`
* **Authors:** Platform team
* **Supersedes:** —

## Context

Phase 1 (Identity & Authorization) and Phase 1A (Constitutional Completion)
established the Platform Kernel and the Identity bounded context. Before
exposing this surface to the React SPA (Phase 1D) and external consumers,
the platform requires a **frozen, machine-readable, governed contract**.

Without an immutable baseline, the API could drift silently under
maintenance, breaking SDK clients, partner government integrations, and
future bounded contexts that consume identity events. A generated OpenAPI
HTML page is **not** a contract — it is documentation that mutates with
every commit.

## Decision

Establish a versioned **Platform Contract Package** at `/app/contracts/`
that contains independently-frozen artifacts for:

1. OpenAPI 3 (`v1/openapi.json`)
2. Request/Response DTO JSON Schemas (`v1/schemas/requests`, `v1/schemas/responses`)
3. RFC 7807 error contracts (`v1/errors/`)
4. Domain Event Catalog + per-event schemas (`v1/events/`)
5. Authorization specifications (`v1/security/permissions.json`,
   `role_matrix.json`, `field_projection.json`)
6. SDK compatibility metadata (`v1/sdk/`)

The package is governed by:

* **Strict drift detection** — `tests/test_contract_freeze.py` compares the
  live FastAPI surface to the frozen artifacts; any unauthorized deviation
  fails CI.
* **Semantic versioning** — MAJOR for breaking, MINOR for additive, PATCH
  for clarification.
* **Mandatory ADR references** for every contract evolution.
* **SHA256 fingerprints** — `v1/sdk/contract.sha256` pins the exact bytes
  of every artifact, enabling SDK generators to refuse compilation against
  an incompatible contract.
* **Deprecation policy** — see `deprecation-policy.md`. Legacy `/api/*`
  endpoints (everything not under `/api/v1/*`) are marked
  `deprecated: true`, receive bug fixes only, and accept no new
  functionality.

## Consequences

### Positive

* SDK generators, partner systems and the React SPA build against a stable
  source of truth.
* No silent API evolution: every change is reviewable, signed by an ADR,
  and traceable in the changelog.
* Domain events become first-class platform contracts, opening the door
  to event-sourced read models and external subscribers without further
  governance work.
* Authorization rules are reflected in machine-readable form, so the
  frontend can hide unauthorized affordances without copying backend
  logic.

### Negative / Trade-offs

* Every contract change now requires deliberate paperwork (ADR + version
  bump + CHANGELOG + regenerate).
* CI failures will occur if developers forget to regenerate the freeze
  after a legitimate change. This is by design.

## Generator and CI

Artifacts are produced by `python -m contracts.generate` (writes the entire
`contracts/v1/` tree from the live FastAPI app). The frozen tree is
committed verbatim. CI re-runs the generator, compares SHA256 fingerprints,
and fails the build if anything differs from the committed tree.
