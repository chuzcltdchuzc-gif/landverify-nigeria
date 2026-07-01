# CR-001 v2 — Governance Drift Prevention (Hardened)

* **Series:** Constitutional Rules (CR-series)
* **Number:** CR-001
* **Version:** v2 (hardened; supersedes any prior CR-001 draft)
* **Status:** ADOPTED — permanent, immutable
* **Adopted:** 2026-06-30
* **Applies to:** All remaining Phase 4 slices, all future phases, and
  every future Key 2 authorization on Aquasavannah LandVault
* **Scope note:** Governance-only. This rule creates no implementation
  artifact, no repository change, no contract change, no code, and no
  test. It defines a MECHANICAL, EVIDENCE-PRODUCING validation gate
  that MUST pass before any Key 2 implementation authority is
  exercised.

---

## A. Purpose

CR-001 exists to prevent nine specific failure modes observed in
long-running constitutional systems:

1. **Governance drift** — silent divergence between the repository and
   the authoritative governance record.
2. **ADR reference errors** — citing an ADR number that does not exist,
   has been superseded, or does not belong to the intended slice.
3. **Roadmap inconsistencies** — the slice a Key 2 authorises does not
   match the reconciled Roadmap ordering or dependencies.
4. **Unauthorised implementation** — code lands without a matching Key
   2 authorisation.
5. **Skipped acceptance gates** — a slice closes without its Acceptance
   Review Packet.
6. **Invalid dependency ordering** — a slice starts before its
   prerequisites are Accepted and Frozen.
7. **Accidental progression** — automatic movement to the next slice
   without an explicit Operator Key 2.
8. **Unverified assertions** — a validator marks a check "PASS" without
   citing evidence.
9. **Version confusion** — a Key 2 references a governance document
   without pinning the version/content-hash actually in force.

---

## B. Evidence-First Principle (core hardening)

**Every** check in the Governance Validation Checklist (§D) MUST be
answered with CITED EVIDENCE. Acceptable evidence includes:

* The exact ADR number resolved against `/app/contracts/v1/adr/ADR_INDEX.md`
  (§H item 3) and its current status;
* The exact slice row from
  `/app/blueprints/phase4/PHASE4_ROADMAP_RECONCILIATION.md`;
* The exact `SLICE_STATE.md` row (including Freeze Commit/Tag and
  Depends-On column) for the target slice and every prerequisite;
* The exact freeze commit hash (or annotated tag) of the previous
  slice;
* The exact contract VERSION string and the current SDK
  compatibility manifest hash;
* The document version / content-hash of every governance document
  the Key 2 relies on.

A check with no cited evidence is a **FAIL**. Marking a check "PASS"
without evidence is itself a **governance violation** and MUST be
appended to `GOVERNANCE_VALIDATION_LOG.md` as a `FAIL` entry with the
corrective action "produce evidence or refuse".

---

## C. Version / Hash Pinning

Existence of a referenced document is insufficient. Every governance /
architecture document a Key 2 relies on MUST be cited by:

1. **Absolute path** on disk (e.g. `/app/contracts/v1/adr/ADR_INDEX.md`),
   **AND**
2. **Version identifier or content-hash** (e.g. contract `VERSION =
   2.0.0`, `SLICE_STATE.md` row version `2026-06-30`, or a SHA-256 of
   the file content at the time of validation).

The validator MUST confirm the referenced version is the CURRENT one
recorded in `ADR_INDEX.md` / `SLICE_STATE.md`. Citing a version that
has been superseded, deprecated, or reclassified out-of-catalogue is a
FAIL, even if the document still exists on disk.

---

## D. Governance Validation Checklist

The Validator (main agent, on receipt of a Key 2) MUST execute every
check below and record the outcome in a
`GOVERNANCE_VALIDATION_REPORT.md` filled from
`/app/governance/templates/GOVERNANCE_VALIDATION_REPORT.template.md`.

**All seven checks MUST PASS with cited evidence.** ANY failure
triggers §G Failure Behaviour.

### D.1 — ADR Validation
Every ADR referenced by the Key 2:

* MUST exist in `/app/contracts/v1/adr/ADR_INDEX.md` at its four-digit
  canonical number.
* MUST have status `ACCEPTED` (not `PROPOSED`, `DEPRECATED`, or
  `SUPERSEDED`).
* MUST NOT be reclassified as an "Out-of-Catalogue Artifact" per
  `ADR_INDEX.md` §2.
* MUST belong to the intended slice per the Reconciliation matrix
  (`PHASE4_ROADMAP_RECONCILIATION.md` §2).

**Evidence:** ADR number, catalogue path + version, status, phase,
supersedes-chain, matched slice.

### D.2 — Slice Validation
The requested slice:

* MUST appear as a row in `PHASE4_ROADMAP_RECONCILIATION.md` §3 (or
  the successor Roadmap Validation Matrix).
* MUST have a defined Acceptance Gate, Deliverables list, and named
  Constitutional Owner.

**Evidence:** exact slice row (with §3 reference), Acceptance Gate
statement, Deliverables enumeration, Constitutional Owner.

### D.3 — Dependency Validation
For every prerequisite listed in `SLICE_STATE.md` `Depends-On`:

* The prerequisite slice's `Status` MUST be `Accepted` AND `Frozen`.
* The prerequisite's `Acceptance Review Ref` MUST resolve to a real
  Acceptance Review document that has PASSED.
* Every constitutional dependency (ADR references cited by the
  prerequisite) MUST also satisfy §D.1.

**Evidence:** prerequisite slice rows, Acceptance Review paths + PASS
verdict, ADR chain validated.

### D.4 — Acceptance Gate Validation
The slice's Acceptance Gate:

* MUST enumerate explicit acceptance criteria.
* MUST declare constitutional exit conditions (what "done" looks like
  against the ADR set).
* MUST declare measurable success criteria (numeric or boolean).
* MUST include, where applicable, replay-determinism verification,
  contract drift verification, and security verification.

**Evidence:** enumerated criteria, exit conditions, measurable
success statements, applicable verification hooks.

### D.5 — Repository State Validation
* The repository MUST be constitutionally FROZEN at the
  Freeze Commit/Tag recorded in `SLICE_STATE.md` for the most recent
  Accepted slice.
* The previous slice MUST have closed correctly (Accepted → Frozen
  transition recorded in the log).
* There MUST be no unresolved constitutional exceptions or governance
  conflicts open in `GOVERNANCE_VALIDATION_LOG.md`.

**Evidence:** current HEAD commit vs. Freeze Commit/Tag,
prior-slice acceptance entry, open-conflict count = 0.

### D.6 — Contract Validation
* The correct contract VERSION MUST be referenced (`/app/contracts/VERSION`
  matches the version pinned in the Key 2).
* The SDK compatibility manifest MUST be current
  (`/app/contracts/v1/sdk/compatibility.json` aggregate_sha256 matches
  the SDK `SDK_META.aggregateSha256`).
* The contract drift gate (`python -m contracts.generate --check`)
  MUST be GREEN.

**Evidence:** VERSION string, compatibility manifest hash + SDK hash
match, drift-gate output.

### D.7 — Architectural Validation
The slice MUST align with, in this order (§H hierarchy):

1. Foundation Specification;
2. PRD (`/app/memory/PRD.md`);
3. `ADR_INDEX.md`;
4. Constitutional Rules (this rule and any successors);
5. Phase Specifications;
6. Phase Roadmap Reconciliation;
7. Phase Blueprints;
8. Acceptance Review Packets;
9. Production Readiness Review;
10. Slice-Level Key 2 Authorisations.

Any conflict is resolved in favour of the HIGHER-numbered level.

**Evidence:** each level's reference and confirmation of no conflict.

---

## E. Key 2 Authorisation Requirements

A Key 2 authorisation is VALID only if the operator explicitly
identifies **all** of the following:

| Field | Description |
| --- | --- |
| Phase | e.g. `Phase 4` |
| Slice | e.g. `4.1 — Workflow Engine Completion` |
| Scope | what IS and IS NOT authorised |
| Deliverables | enumerated artifact list |
| Acceptance Gate | measurable exit criteria |
| Constitutional References | ADR numbers (four-digit) + document versions/hashes |
| Expected Repository State | commit hash or annotated tag of the freeze the Key 2 builds from |
| Key 2 Id | opaque identifier used for logging (`K2-<phase>-<slice>-<yyyymmdd>-<seq>`) |

**Generic approvals** (`"Proceed"`, `"Continue"`, `"Looks good"`,
`"Approved"`, `"You may begin"`, `"Ship it"`) NEVER constitute
implementation authority. The Validator MUST refuse them and log a FAIL
with corrective action = "Operator to re-issue a fully-qualified Key 2
per CR-001 §E".

---

## F. Loadability Requirement

The Validator MUST load and quote (in-session) the referenced
governance / architecture documents. If any referenced document is not
available or not loadable in the current session (missing file,
inaccessible path, corrupted content), validation FAILS. Documents are
NEVER assumed — they are read.

---

## G. Failure Behaviour

On ANY failed check, the Validator MUST perform ALL of the following
in order:

1. **Refuse implementation.** No file may be created / modified until
   re-validation passes.
2. **Name the exact rule / check that failed** (`CR-001 §D.<n>`).
3. **Identify the conflicting document(s) and version(s)** with
   absolute paths and content-hashes.
4. **Recommend corrective action** — either an Operator step (re-issue
   Key 2, ratify an amended ADR) or a document step (regenerate
   manifest, run drift gate).
5. **Append a FAILED entry** to `/app/governance/GOVERNANCE_VALIDATION_LOG.md`
   in the format defined by that document's header.
6. **Return to idle, constitutionally frozen state.** No implementation
   may begin until the issue is resolved and re-validation PASSES.

---

## H. Constitutional Hierarchy

Highest to lowest. Higher levels prevail on conflict.

| # | Level | Authoritative artifact |
| --- | --- | --- |
| 1 | Foundation Specification | Foundation Spec document |
| 2 | Product Requirements Document | `/app/memory/PRD.md` |
| 3 | Master ADR Index | `/app/contracts/v1/adr/ADR_INDEX.md` |
| 4 | Constitutional Rules (CR-series) | `/app/governance/CR-*.md` including this rule |
| 5 | Phase Specifications | `/app/blueprints/phase*/PHASE*_SPEC.md` |
| 6 | Phase Roadmap Reconciliation | `/app/blueprints/phase4/PHASE4_ROADMAP_RECONCILIATION.md` |
| 7 | Phase Blueprints | `/app/blueprints/phase*/PHASE*_BLUEPRINT.md` |
| 8 | Acceptance Review Packets | `/app/audit/PHASE-*-*.md` and slice acceptance packets |
| 9 | Production Readiness Review | `/app/audit/PRODUCTION-READINESS-REVIEW.md` |
| 10 | Slice-Level Key 2 Authorisations | operator directive of record |

### H-note-1 — ADR Index governs numbering
Level 3 (`ADR_INDEX.md`) is the **sole** authority for ADR numbering.
No slice, blueprint, phase spec, or Key 2 may introduce or reassign an
ADR number without a formal amendment to Level 3.

### H-note-2 — CR and ADR series are non-colliding
Constitutional Rules use the `CR-NNN` namespace. Architectural
Decisions use the `ADR-NNNN` namespace. The two series are
independent: `CR-001` and `ADR-0001` are distinct artefacts with
distinct amendment paths.

---

## I. Audited Validations (dogfooding ADR-0005)

Every validation run — **PASS**, **FAIL**, or **BREAK-GLASS** — MUST
be appended to `/app/governance/GOVERNANCE_VALIDATION_LOG.md` as an
immutable, append-only entry.

* Fields: `timestamp` (ISO8601 UTC), `key2_id`, `phase`, `slice`,
  `result`, `evidence_summary` (concise list of doc paths + versions),
  `operator`, `corrective_action_if_any`.
* No edit or delete path exists. Amendments happen exclusively via
  **new** entries that reference the prior entry's timestamp.
* This mirrors ADR-0005 (Append-only Audit) applied to governance
  itself.

---

## J. Amendment Process (CR immutability)

CR-001 is **immutable** once adopted. It may only be changed by a
superseding rule (e.g. `CR-002`) approved by an Operator Key 2 that
explicitly names CR-001 in its Supersedes field. Under NO circumstance
may CR-001 be edited in place after adoption.

* Every amendment MUST include a `Supersedes: CR-001 v<n>` line and
  the current file's header MUST be updated with a corresponding
  `Superseded-by: CR-<successor>` note **only when superseded** —
  never before.
* The successor CR is itself subject to CR-001 §D validation before
  taking effect.

This mirrors ADR immutability per Foundation Spec §11.

---

## K. Break-Glass Procedure (constrained; never a bypass)

Emergencies (production incident, data-integrity breach, security
vulnerability under active exploit) MAY require action faster than a
full Key 2 cycle. Break-glass is **narrowed scope, never skipped
audit**.

Break-glass requires ALL of the following:

1. **Explicit Operator break-glass Key 2** naming:
   * the emergency in one sentence,
   * the exact scope (files, endpoints, or aggregates permitted),
   * the exact time-box (wall-clock deadline, ≤ 24 h),
   * the ADRs / CRs that are TEMPORARILY relaxed (each cited with
     four-digit ADR number or `CR-NNN`).
2. **Dual acknowledgement** — the Validator MUST echo back the
   emergency, scope, and time-box in a single message before any file
   is touched.
3. **Strict time / scope box** — any change outside the declared scope
   or after the time-box is a fresh governance violation.
4. **Mandatory post-hoc Acceptance Review** — within 5 business days
   of the break-glass, a full Acceptance Review Packet MUST be
   produced and appended to the slice folder, and a `BREAK-GLASS`
   log entry MUST record what was done, why, and what corrective
   normalisation is planned.
5. **Follow-up review trigger** — the log entry MUST include a
   `follow_up_review_due` timestamp; the next Validator run refuses to
   start if any past-due break-glass follow-up is open.

Break-glass NARROWS scope; it never removes the audit trail.

---

## L. Constitutional Adoption

CR-001 v2 is hereby ADOPTED as a **permanent constitutional governance
rule**. It applies to:

* all remaining Phase 4 slices (4.1 through 4.8 per
  `PHASE4_ROADMAP_RECONCILIATION.md` §3),
* every future phase (Phase 5, Phase 6, and beyond),
* every future Key 2 authorisation across the entire platform.

CR-001 v2 changes NO implementation artifact, NO repository content,
NO contract, NO SDK, NO API, NO test, and NO application code.

---

## M. Constitutional Rules to Confirm as Binding

The following rules — already binding — are re-affirmed as
non-negotiable pre-conditions of any Key 2 validation:

1. Independent Key 2 authorisation per slice.
2. Independent Acceptance Review per slice.
3. Repository freeze after every slice.
4. No automatic progression between slices.
5. Replay determinism.
6. Immutable evidence.
7. Registry remains System of Record.
8. Projections contain zero business logic.
9. SDK-first UI.
10. Contract-first development.
11. Zero contract drift.
12. Append-only audit.

---

## N. Constitutional Verdict

CR-001 v2 is ADOPTED as permanent constitutional governance. Validation
is now MECHANICAL and EVIDENCE-PRODUCING — no unverified `PASS` is
permitted. `SLICE_STATE.md` and `ADR_INDEX.md` are the AUTHORITATIVE
inputs to Checklist items §D.3 and §D.5. Future Key 2 authorisations
may proceed ONLY after a completed, passing Governance Validation
Report is filed in `/app/governance/reports/` and a `PASS` line is
appended to `/app/governance/GOVERNANCE_VALIDATION_LOG.md`.

The repository remains constitutionally frozen pending the next
compliant Key 2.

## End of CR-001 v2
