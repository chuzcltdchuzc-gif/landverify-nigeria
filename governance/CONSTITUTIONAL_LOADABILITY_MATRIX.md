# Constitutional Loadability Matrix

> **Machine-readable ledger** of every constitutional artifact required
> by CR-001 v2+ and the Governance Constitution. Its purpose is to make
> §F (Loadability) mechanically verifiable: every `Required = YES`
> artifact MUST have `Loaded = YES` before any Key 2 pre-flight can PASS.
>
> **Update discipline:** every row change is mirrored by an entry in
> `/app/governance/RATIFICATION_LOG.md`. Rows are never deleted; if an
> artifact is retired, its `Status` becomes `Retired` in a new row
> version.

## Column semantics

| Column | Definition |
| --- | --- |
| Artifact | Canonical name of the constitutional document |
| Location | Absolute path in the repository |
| Required | YES = presence + loadability is a constitutional pre-condition; NO = advisory |
| Loaded | YES if the file was successfully read this session; NO otherwise |
| Hash | sha256 of the file at the time of the last matrix update |
| Version | Version string embedded in the file (or `n/a`) |
| Authority Level | Corresponds to CR-001 §H / Governance Constitution hierarchy |
| Status | `Adopted` \| `Draft` \| `Pending Content` \| `Retired` \| `Not Present` |

## Matrix (FINALIZED 2026-07-01 at Step 9)

| Artifact | Location | Required | Loaded | Hash | Version | Authority Level | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Governance Constitution | `/app/governance/GOVERNANCE_CONSTITUTION.md` | YES | **YES** | `815ed3893993988d71b5f8c24354239cae0f619107bedca06527ac64fb4d8321` | v1 (2026-07-01) | Sole source of hierarchy (operates across levels) | **Adopted** |
| Foundation Specification | `/app/blueprints/foundation/FOUNDATION_SPECIFICATION.md` | YES | **YES** | `00ef79060b3332d22ca79ac6d7d5e8c57984825793fac589a2744f3e1c94079a` | v1.1 (Phase 0; Operator-ratified 2026-07-01) | **L1** | **Adopted** |
| Product Requirements Document | `/app/memory/PRD.md` | YES | YES | `be37973f54dd59338be907078312d9ef861aca306ed067fda4ee4f244fe9dd5e` | 2026-06-30 rolling | **L2** | Adopted |
| Master ADR Index | `/app/contracts/v1/adr/ADR_INDEX.md` | YES | YES | `e7e6ec0fd25118a1d4a5c6e7dfa5410829c3fee68dfc77eb9d4abf0addf9b35e` | v1.1 | **L3** | Adopted |
| Constitutional Rules — CR-001 | `/app/governance/CR-001-GOVERNANCE-DRIFT-PREVENTION.md` | YES | YES | `ffc91e5c2f243409d91a806e627cea5ea60eb1813a437cd0862a1cefdc94ff9e` | v2.1 (2026-07-01) | CR-series (across levels) | Adopted |
| Phase 4 Specification | `/app/blueprints/phase4/PHASE4_SPEC.md` | YES | YES | *(unchanged since Phase 4 blueprinting)* | Phase-4 rolling | **L4** | Adopted |
| Phase 4 Roadmap Reconciliation | `/app/blueprints/phase4/PHASE4_ROADMAP_RECONCILIATION.md` | YES | YES | `4af7afd659cc35a976e35e9767dfc5b54d52e0535dd2204f92d24cf5783a1559` | v1.1 (Step 6 amendment) | **L5** | Adopted |
| Phase 4 Blueprint | `/app/blueprints/phase4/PHASE4_BLUEPRINT.md` | YES | YES | *(unchanged)* | Phase-4 rolling | **L4** | Adopted |
| Slice 4.0 Acceptance Packet | `/app/audit/PHASE-4-SLICE-4.0-ACCEPTANCE.md` | YES | YES | *(unchanged)* | 2026-06-30 | **L5** | Adopted |
| Production Readiness Review | `/app/audit/PRODUCTION-READINESS-REVIEW.md` | YES | YES | *(unchanged)* | 2026-06-30 | **L5** | Adopted |
| Slice State Ledger | `/app/governance/SLICE_STATE.md` | YES | YES | `089364fe0cb80f22bdbb99ac21d5143011bba510e99edd09eb63aa9b4c6244bb` | v1.1 (immutable 4.0 SHA) | Governance input (across levels) | Adopted |
| Governance Validation Log | `/app/governance/GOVERNANCE_VALIDATION_LOG.md` | YES | YES | `f171714137f09c09cd1348d3b15c0f2a9f90832c5df1f197230233d1b15fc6c4` | append-only | Governance (n/a) | Adopted |
| Governance Validation Report Template | `/app/governance/templates/GOVERNANCE_VALIDATION_REPORT.template.md` | YES | YES | *(unchanged)* | v1 | Governance (n/a) | Adopted |
| Ratification Log | `/app/governance/RATIFICATION_LOG.md` | YES | YES | `81ac836c594828a30fdb218c6f4e37f0768a88e959f92f6570891d4f70c3f151` | v1 | Governance (n/a) | Adopted |
| Constitutional Loadability Matrix (this file) | `/app/governance/CONSTITUTIONAL_LOADABILITY_MATRIX.md` | YES | YES | *(this file — hash recorded post-finalization in RATIFICATION_LOG)* | v1.1 (finalized) | Governance (n/a) | Adopted |
| Contract VERSION | `/app/contracts/VERSION` | YES | YES | `c28fcca53637bc88e124af1725df13cb98c69dedefd62fb3cdbe1cdb6b760624` | 2.0.0 | **L3** (informational; contract governance) | Adopted |

## Finalization rule

The matrix is FINALIZED (per directive Step 9) only when EVERY row with
`Required = YES` has `Loaded = YES`, `Status = Adopted`, and a real
sha256 hash. Until then, CR-001 §F FAILS and no Key 2 pre-flight can
PASS.

## End of Matrix v1
