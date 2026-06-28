# Aquasavannah LandVault — Platform Contract Package

> **Status:** Frozen, governed artifact.
> **Version:** see [`VERSION`](./VERSION) (currently `1.0.0`).
> **Owner:** Platform team.
> **Phase:** 1C — Platform Contract Freeze (binding decision, 2026-06-28).

The contents of `v1/` are the **constitutional interface** of AquaSavannah
LandVault. Every consumer — the React SPA, mobile clients, partner
government systems, generated SDKs — depends on these files.

Do **not** edit `v1/*` by hand. Files are produced by the generator and
verified by CI.

```text
contracts/
├── VERSION                              # MAJOR.MINOR.PATCH semver
├── CHANGELOG.md                         # ADR-referenced change history
├── deprecation-policy.md                # Legacy /api/* governance rules
├── release-manifest.json                # Per-release fingerprints + git commit
├── generate.py                          # The generator (single source of truth)
├── ci_check_drift.sh                    # CI gate (calls generate.py --check)
└── v1/
    ├── openapi.json                     # Frozen OpenAPI 3.x for /api/v1 + /api/*
    ├── adr/                             # Architecture Decision Records
    ├── schemas/
    │   ├── requests/*.json              # Per-DTO JSON Schemas (request bodies)
    │   └── responses/*.json             # Per-DTO JSON Schemas (responses)
    ├── errors/*.json                    # RFC 7807 problem+json contracts
    ├── events/
    │   ├── catalog.json                 # Machine-readable Domain Event Catalog
    │   └── <event>.v<N>.json            # Per-event JSON Schemas
    ├── security/
    │   ├── permissions.json             # ABAC patterns + identity actions
    │   ├── role_matrix.json             # The 10 canonical roles
    │   └── field_projection.json        # PII / field-visibility rules
    ├── sdk/
    │   ├── sdk.version                  # SDK compatibility tag
    │   ├── compatibility.json           # Per-language compatibility matrix
    │   └── contract.sha256              # Byte-level fingerprint of every file
    └── examples/                        # Hand-curated sample payloads
```

## How to make a contract change

1. **Decide the change is necessary.** Most enhancements should be
   additive on `/api/v1/*`. Legacy `/api/*` accepts bug fixes only — see
   [`deprecation-policy.md`](./deprecation-policy.md).
2. **Bump [`VERSION`](./VERSION)** per semver:
   * Breaking change to `/api/v1/*` → MAJOR.
   * Additive change → MINOR.
   * Clarification / documentation fix → PATCH.
3. **Write an ADR** under `v1/adr/ADR-XXXX-<slug>.md`.
4. **Append to [`CHANGELOG.md`](./CHANGELOG.md)** referencing the ADR.
5. Run **`python -m contracts.generate`** to regenerate every artifact.
6. Commit the regenerated tree. CI re-runs
   `bash contracts/ci_check_drift.sh` to verify.

## How drift is enforced

* **CI script:** [`ci_check_drift.sh`](./ci_check_drift.sh) — runs
  `python -m contracts.generate --check`. Non-zero exit fails the build.
* **Pytest gate:** [`backend/tests/test_contract_freeze.py`](../backend/tests/test_contract_freeze.py).
  Eight assertions cover byte-equality, canonical endpoint presence,
  legacy deprecation tagging, event-catalog/outbox parity,
  role-matrix/runtime parity, and SHA fingerprint integrity.

## SDK consumers

* `v1/sdk/contract.sha256` — pin this in your SDK generator. Refuse to
  compile if it changes without a matching version bump.
* `v1/sdk/compatibility.json` — language matrix and aggregate hash.
* `v1/sdk/sdk.version` — your SDK's `contract_version` tag.

## Reference

* ADR-0001 — [Platform Contract Freeze](./v1/adr/ADR-0001-platform-contract-freeze.md)
* Foundation Spec §2.3 — Domain Event Envelope versioning
* ADR-002 — Centralized Authorization Engine (default DENY)
