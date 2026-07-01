# SLICE_STATE.md — Machine-Readable Slice Governance Ledger

* **Authority:** CR-001 §D.3 / §D.5 authoritative input
* **Seeded from:** `/app/blueprints/phase4/PHASE4_ROADMAP_RECONCILIATION.md` §3
  (Roadmap Validation Matrix) reflecting the reconciled slice order
  including the DEDICATED Survey slice (Operator Decision #1).
* **Update discipline:** This ledger is APPEND-ORIENTED. Rows are
  updated in place ONLY to record status transitions (`Authorized →
  In-Progress → Accepted → Frozen`), and every change is mirrored by an
  entry in `/app/governance/GOVERNANCE_VALIDATION_LOG.md`. Adding a new
  slice REQUIRES a superseding Roadmap Reconciliation document.
* **Immutable columns** (never rewritten once set): `Slice`, `Title`,
  `Constitutional Owner`, `Depends-On`.
* **Mutable columns** (updated via logged transitions only): `Status`,
  `Freeze Commit/Tag`, `Acceptance Review Ref`, `Last Updated`.

## 0. Status vocabulary

| Status | Meaning |
| --- | --- |
| `Authorized` | An operator Key 2 has been issued for this slice; work has not begun. |
| `In-Progress` | Implementation is underway under an active Key 2. |
| `Accepted` | The slice has passed its Acceptance Review. |
| `Frozen` | The slice is Accepted AND the repository is at the recorded Freeze Commit/Tag. Only `Accepted+Frozen` prerequisites satisfy CR-001 §D.3. |
| `Pending` | No Key 2 has been issued; the slice is a future item. |

## 1. Ledger

| Slice | Title | Status | Freeze Commit/Tag | Acceptance Review Ref | Depends-On | Constitutional Owner | Last Updated |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 4.0 | Workflow Engine Foundation | `Accepted+Frozen` | `<recorded-at-freeze>` (contract `VERSION=2.0.0`; slice tag `phase4-slice-4.0`) | `/app/audit/PHASE-4-SLICE-4.0-ACCEPTANCE.md` | — | ADR-0021 + ADR-0022 + ADR-0004 + ADR-0005 | 2026-06-30 |
| 4.1 | Workflow Engine Completion (real `emit_command`, real `spawn` fan-out, Policy Engine, SLA / Escalation, Notification delivery infrastructure) | `Pending` | — | — | 4.0 | ADR-0021 + ADR-0022 + ADR-0019 + ADR-0004 + ADR-0005 | 2026-06-30 |
| 4.2 | Consent | `Pending` | — | — | 4.1 | ADR-0020 + ADR-0009 + ADR-0015 + ADR-0016 | 2026-06-30 |
| 4.3 | Survey Assignment (DEDICATED per Operator Decision #1) | `Pending` | — | — | 4.1 | ADR-0001 + ADR-0014 + ADR-0009 + ADR-0015 (consumes engine + policy from 4.1) | 2026-06-30 |
| 4.4 | Community Validation | `Pending` | — | — | 4.1, 4.3 | ADR-0020 + ADR-0009 + ADR-0015 | 2026-06-30 |
| 4.5 | Inheritance | `Pending` | — | — | 4.1, 4.4 | ADR-0001 + ADR-0014 + ADR-0009 + ADR-0015 | 2026-06-30 |
| 4.6 | Infrastructure (Notification projections / inbox, cross-slice projections) | `Pending` | — | — | 4.1 | ADR-0019 + ADR-0004 + ADR-0005 | 2026-06-30 |
| 4.7 | SDK & React Workspace | `Pending` | — | — | 4.1 – 4.6 as features land | Contract-first (no new ADRs; pinned to contract v2.x) | 2026-06-30 |
| 4.8 | Phase 4 Acceptance Review | `Pending` | — | — | 4.0 – 4.7 | Composes all Phase 4 ADRs | 2026-06-30 |

## 2. Freeze Commit / Tag conventions

* `<recorded-at-freeze>` MUST be replaced by an operator or CI at the
  moment the slice enters `Frozen` status. Acceptable formats:
  * Full git SHA-1 (40 hex chars).
  * Annotated tag (e.g. `phase4-slice-4.0`) — must be immutable per
    Foundation Spec §11.
* If the freeze commit / tag is not yet recorded, CR-001 §D.5
  (Repository State Validation) MUST FAIL until it is.

## 3. Depends-On evaluation rules

For any target slice `S`, CR-001 §D.3 requires:

1. Every slice listed in `S.Depends-On` MUST have `Status =
   Accepted+Frozen`.
2. Every dependency's `Acceptance Review Ref` MUST resolve to a
   real document at that path.
3. Transitive dependencies are NOT auto-resolved — the Key 2 MUST list
   the full transitive chain if it intends to build on it.

## 4. Constitutional Owner column

The `Constitutional Owner` column is the AUTHORITATIVE mapping of the
slice to its governing ADRs. Values here MUST be identical (four-digit
form) to the mapping in `PHASE4_ROADMAP_RECONCILIATION.md` §2. Any
divergence is a governance violation that fails CR-001 §D.1 and §D.2.

## 5. Update Protocol

To transition a row's `Status`:

1. Produce a passing Governance Validation Report (per
   `/app/governance/templates/GOVERNANCE_VALIDATION_REPORT.template.md`).
2. Append a `PASS` entry to `GOVERNANCE_VALIDATION_LOG.md`.
3. Update the mutable columns of the affected row in this file
   (`Status`, `Freeze Commit/Tag`, `Acceptance Review Ref`,
   `Last Updated`).
4. Never update immutable columns.
5. Never delete a row. Slices removed from the roadmap are marked
   `Withdrawn` in a superseding row; the original row remains.

## 6. Consistency with the ADR Catalogue

Every ADR referenced in the `Constitutional Owner` column MUST:

* Exist in `/app/contracts/v1/adr/ADR_INDEX.md`.
* Have `Status = ACCEPTED` there.
* NOT be in the Out-of-Catalogue table (§ADR_INDEX.md §2).

Automated validators (CR-001 §D.1) MUST cross-check this file against
`ADR_INDEX.md` on every run.

## 7. End of Ledger
