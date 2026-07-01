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

## Matrix (seeded 2026-07-01; will be finalized at Step 9)

| Artifact | Location | Required | Loaded | Hash | Version | Authority Level | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Governance Constitution | `/app/governance/GOVERNANCE_CONSTITUTION.md` | YES | NO | *(not yet created — Step 7 pending)* | *(pending)* | 1 (highest — supersedes CR-001's local hierarchy per Step 8) | **Not Present** |
| Foundation Specification | `/app/blueprints/foundation/FOUNDATION_SPECIFICATION.md` | YES | NO | *(Operator-supplied Phase 0 Foundation Specification content was NOT PROVIDED in this session; the directive explicitly forbids synthesis from a bullet list)* | *(pending)* | 1 (via Constitution) / 2 (per CR-001 §H current) | **Pending Content — Step 5 FAILED per directive §STEP 5. Steps 6–10 BLOCKED until Operator supplies the authoritative content.** |
| Product Requirements Document | `/app/memory/PRD.md` | YES | YES | *(recomputed at Step 9)* | 2026-06-30 rolling | 2 | Adopted |
| Master ADR Index | `/app/contracts/v1/adr/ADR_INDEX.md` | YES | YES | *(bumped in Step 3)* | v1.1 (post-Step 3) | 3 | Adopted |
| Constitutional Rules — CR-001 | `/app/governance/CR-001-GOVERNANCE-DRIFT-PREVENTION.md` | YES | YES | *(bumped in Step 8)* | v2 → v2.1 (post-Step 8) | 4 | Adopted |
| Phase 4 Specification | `/app/blueprints/phase4/PHASE4_SPEC.md` | YES | YES | *(recomputed at Step 9)* | Phase-4 rolling | 5 | Adopted |
| Phase 4 Roadmap Reconciliation | `/app/blueprints/phase4/PHASE4_ROADMAP_RECONCILIATION.md` | YES | YES | *(bumped in Step 6)* | v1 → v1.1 (post-Step 6) | 6 | Adopted |
| Phase 4 Blueprint | `/app/blueprints/phase4/PHASE4_BLUEPRINT.md` | YES | YES | *(recomputed at Step 9)* | Phase-4 rolling | 7 | Adopted |
| Phase 3 Acceptance Packet | `/app/audit/PHASE-3-ACCEPTANCE-PACKET.md` | YES | YES | *(recomputed at Step 9)* | 2026-06-29 | 8 | Adopted |
| Slice 4.0 Acceptance Packet | `/app/audit/PHASE-4-SLICE-4.0-ACCEPTANCE.md` | YES | YES | *(recomputed at Step 9)* | 2026-06-30 | 8 | Adopted |
| Production Readiness Review | `/app/audit/PRODUCTION-READINESS-REVIEW.md` | YES | YES | *(recomputed at Step 9)* | 2026-06-30 | 9 | Adopted |
| Slice State Ledger | `/app/governance/SLICE_STATE.md` | YES | YES | *(bumped in Step 4)* | v1 → v1.1 (post-Step 4) | 3 (authoritative dependency input) | Adopted |
| Governance Validation Log | `/app/governance/GOVERNANCE_VALIDATION_LOG.md` | YES | YES | *(recomputed at Step 9)* | append-only | n/a | Adopted |
| Governance Validation Report Template | `/app/governance/templates/GOVERNANCE_VALIDATION_REPORT.template.md` | YES | YES | *(recomputed at Step 9)* | v1 | n/a | Adopted |
| Ratification Log | `/app/governance/RATIFICATION_LOG.md` | YES | YES | *(recomputed at Step 9)* | v1 | n/a | Adopted |
| Constitutional Loadability Matrix (this file) | `/app/governance/CONSTITUTIONAL_LOADABILITY_MATRIX.md` | YES | YES | *(recomputed at Step 9)* | v1 | n/a | Adopted |
| Contract VERSION | `/app/contracts/VERSION` | YES | YES | *(recomputed at Step 9)* | 2.0.0 | 3 (informational) | Adopted |

## Finalization rule

The matrix is FINALIZED (per directive Step 9) only when EVERY row with
`Required = YES` has `Loaded = YES`, `Status = Adopted`, and a real
sha256 hash. Until then, CR-001 §F FAILS and no Key 2 pre-flight can
PASS.

## End of Matrix v1
