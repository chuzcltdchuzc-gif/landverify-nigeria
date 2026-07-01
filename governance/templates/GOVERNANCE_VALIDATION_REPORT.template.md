# Governance Validation Report — TEMPLATE

> **Template version:** v1 (2026-06-30)
> **Governed by:** `/app/governance/CR-001-GOVERNANCE-DRIFT-PREVENTION.md`
> **Instructions:**
> * Copy this file to `/app/governance/reports/<key2_id>-<slice>.md`
>   (e.g. `K2-P4-4.1-20260701-01-4.1.md`) BEFORE any implementation
>   begins.
> * Fill EVERY field. Missing fields = FAIL (CR-001 §B).
> * Every `Evidence` cell MUST include (i) an absolute path, and (ii)
>   a version identifier or content-hash (CR-001 §C).
> * The `Overall Result` is `PASS` if and only if EVERY §D.1 – §D.7
>   row has `Result = PASS`. Otherwise the Validator MUST refuse
>   implementation per CR-001 §G and log a FAIL entry in
>   `/app/governance/GOVERNANCE_VALIDATION_LOG.md`.
> * A completed PASS report becomes part of the slice's Acceptance
>   Review Packet.

---

## 0. Header — Key 2 Identification (CR-001 §E)

| Field | Value |
| --- | --- |
| Key 2 Id | `K2-<phase>-<slice>-<yyyymmdd>-<seq>` |
| Phase | e.g. `Phase 4` |
| Slice | e.g. `4.1 — Workflow Engine Completion` |
| Scope (IN) | Enumerated list of what IS authorised |
| Scope (OUT) | Enumerated list of what is explicitly PROHIBITED |
| Deliverables | Enumerated artifact list expected at Acceptance |
| Acceptance Gate | Measurable exit criteria |
| Constitutional References | ADR numbers (four-digit) + document versions/hashes |
| Expected Repository State | Freeze commit hash / annotated tag the Key 2 builds from |
| Operator | Human-readable identifier |
| Report Timestamp | ISO8601 UTC |

> **Refusal rule:** if any of the fields above is missing, contains a
> generic phrase (e.g. "Proceed", "Continue", "Approved"), or fails to
> pin a version/hash, the Validator MUST refuse per CR-001 §E and log a
> FAIL entry with corrective action = "Operator to re-issue a
> fully-qualified Key 2 per CR-001 §E".

---

## 1. Loadability Sweep (CR-001 §F)

For every document referenced by this Key 2, confirm it was LOADED
in-session and quote a fingerprint (path :: version-or-hash). Missing
document = FAIL.

| # | Document (absolute path) | Version / Hash | Loaded? |
| --- | --- | --- | --- |
| 1 |  |  | ☐ |
| 2 |  |  | ☐ |
| 3 |  |  | ☐ |
| ... |  |  | ☐ |

---

## 2. Validation Checklist (CR-001 §D)

Each row MUST cite EVIDENCE. `Result` is `PASS` only when Evidence is
present, cited, and confirmed against the authoritative artefacts.

### §D.1 — ADR Validation

| Check | Evidence (cited, with version/hash) | Result | Notes |
| --- | --- | --- | --- |
| Every referenced ADR exists in `ADR_INDEX.md` at its four-digit canonical number |  | ☐ PASS / ☐ FAIL |  |
| Every referenced ADR has Status = `ACCEPTED` |  | ☐ PASS / ☐ FAIL |  |
| No referenced ADR is in the `ADR_INDEX.md` §2 Out-of-Catalogue table |  | ☐ PASS / ☐ FAIL |  |
| Every referenced ADR matches the slice per `PHASE4_ROADMAP_RECONCILIATION.md` §2 |  | ☐ PASS / ☐ FAIL |  |

### §D.2 — Slice Validation

| Check | Evidence | Result | Notes |
| --- | --- | --- | --- |
| Slice appears in `PHASE4_ROADMAP_RECONCILIATION.md` §3 |  | ☐ PASS / ☐ FAIL |  |
| Acceptance Gate defined |  | ☐ PASS / ☐ FAIL |  |
| Deliverables enumerated |  | ☐ PASS / ☐ FAIL |  |
| Constitutional Owner named |  | ☐ PASS / ☐ FAIL |  |

### §D.3 — Dependency Validation

| Prerequisite Slice | `SLICE_STATE.md` Status | Freeze Commit/Tag | Acceptance Review Ref (path + PASS verdict) | Result |
| --- | --- | --- | --- | --- |
|  |  |  |  | ☐ PASS / ☐ FAIL |
|  |  |  |  | ☐ PASS / ☐ FAIL |

* Every prerequisite MUST be `Accepted+Frozen`.
* Every Acceptance Review Ref MUST resolve to a real document with a
  PASS verdict.
* ADR chains cited by each prerequisite MUST also satisfy §D.1.

### §D.4 — Acceptance Gate Validation

| Check | Evidence | Result | Notes |
| --- | --- | --- | --- |
| Explicit acceptance criteria enumerated |  | ☐ PASS / ☐ FAIL |  |
| Constitutional exit conditions declared |  | ☐ PASS / ☐ FAIL |  |
| Measurable success criteria (numeric or boolean) |  | ☐ PASS / ☐ FAIL |  |
| Replay-determinism verification (if applicable) |  | ☐ PASS / ☐ N/A / ☐ FAIL |  |
| Contract-drift verification (if applicable) |  | ☐ PASS / ☐ N/A / ☐ FAIL |  |
| Security verification (if applicable) |  | ☐ PASS / ☐ N/A / ☐ FAIL |  |

### §D.5 — Repository State Validation

| Check | Evidence | Result | Notes |
| --- | --- | --- | --- |
| Current HEAD == prior slice Freeze Commit/Tag |  | ☐ PASS / ☐ FAIL |  |
| Previous slice `Accepted → Frozen` transition recorded in log |  | ☐ PASS / ☐ FAIL |  |
| Zero unresolved constitutional exceptions / governance conflicts |  | ☐ PASS / ☐ FAIL |  |
| No past-due BREAK-GLASS follow-ups open |  | ☐ PASS / ☐ FAIL |  |

### §D.6 — Contract Validation

| Check | Evidence | Result | Notes |
| --- | --- | --- | --- |
| `/app/contracts/VERSION` matches Key 2 pin |  | ☐ PASS / ☐ FAIL |  |
| `compatibility.json` aggregate_sha256 matches `SDK_META.aggregateSha256` |  | ☐ PASS / ☐ FAIL |  |
| `python -m contracts.generate --check` = GREEN |  | ☐ PASS / ☐ FAIL |  |

### §D.7 — Architectural Validation (per §H Hierarchy)

| Level | Reference | No-Conflict Confirmed? | Result |
| --- | --- | --- | --- |
| 1. Foundation Specification |  | ☐ | ☐ PASS / ☐ FAIL |
| 2. PRD (`/app/memory/PRD.md`) |  | ☐ | ☐ PASS / ☐ FAIL |
| 3. `ADR_INDEX.md` |  | ☐ | ☐ PASS / ☐ FAIL |
| 4. Constitutional Rules (`CR-*.md`) |  | ☐ | ☐ PASS / ☐ FAIL |
| 5. Phase Specifications |  | ☐ | ☐ PASS / ☐ FAIL |
| 6. Phase Roadmap Reconciliation |  | ☐ | ☐ PASS / ☐ FAIL |
| 7. Phase Blueprints |  | ☐ | ☐ PASS / ☐ FAIL |
| 8. Acceptance Review Packets |  | ☐ | ☐ PASS / ☐ FAIL |
| 9. Production Readiness Review |  | ☐ | ☐ PASS / ☐ FAIL |
| 10. Slice-Level Key 2 Authorisations |  | ☐ | ☐ PASS / ☐ FAIL |

Any conflict is resolved in favour of the HIGHER-numbered level.

---

## 3. Constitutional Rules Re-Affirmed (CR-001 §M)

The Validator confirms these rules were considered and are respected
by the slice:

| # | Rule | Confirmed |
| --- | --- | --- |
| 1 | Independent Key 2 authorisation per slice | ☐ |
| 2 | Independent Acceptance Review per slice | ☐ |
| 3 | Repository freeze after every slice | ☐ |
| 4 | No automatic progression between slices | ☐ |
| 5 | Replay determinism | ☐ |
| 6 | Immutable evidence | ☐ |
| 7 | Registry remains System of Record | ☐ |
| 8 | Projections contain zero business logic | ☐ |
| 9 | SDK-first UI | ☐ |
| 10 | Contract-first development | ☐ |
| 11 | Zero contract drift | ☐ |
| 12 | Append-only audit | ☐ |

---

## 4. Overall Result

| Field | Value |
| --- | --- |
| Aggregate result | ☐ **PASS** (every §D row and every §3 rule confirmed) / ☐ **FAIL** |
| First failing check (if any) | e.g. `CR-001 §D.3` |
| Corrective action recommended | ... |
| Log entry appended? | ☐ yes — `/app/governance/GOVERNANCE_VALIDATION_LOG.md` |
| Report filed at | `/app/governance/reports/<key2_id>-<slice>.md` |

### 4.1 — On PASS
* Update `SLICE_STATE.md` mutable columns for the target slice
  (`Status: In-Progress`, `Last Updated`).
* Append a `PASS` line to `GOVERNANCE_VALIDATION_LOG.md`.
* Proceed to implementation under the exact Scope declared in §0.

### 4.2 — On FAIL
* Refuse implementation (CR-001 §G).
* Append a `FAIL` entry to `GOVERNANCE_VALIDATION_LOG.md` naming the
  exact check that failed and the corrective action.
* Return to constitutionally frozen state.

### 4.3 — On BREAK-GLASS
* Only permitted with an explicit operator break-glass Key 2 per
  CR-001 §K. Fill §0 with the emergency scope and time-box.
* Append a `BREAK-GLASS` entry to the log with
  `follow_up_review_due` ≤ 5 business days.
* File the mandatory post-hoc Acceptance Review at
  `/app/audit/BREAK-GLASS-<key2_id>-review.md` within the deadline.

---

## 5. End of Template
