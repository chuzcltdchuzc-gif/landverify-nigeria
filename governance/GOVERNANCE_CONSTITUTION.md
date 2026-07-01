# AquaSavannah LandVault — Governance Constitution v1

* **Status:** OPERATOR-RATIFIED
* **Adopted:** 2026-07-01
* **Authority:** Operator Constitutional Remediation directive §STEP 7
* **Scope:** This document is the **highest governance authority** for the AquaSavannah LandVault platform. It consolidates all pre-existing governance instruments (CR-001, ADR_INDEX, Foundation Specification, SLICE_STATE, Ratification Log, Loadability Matrix, Governance Validation Report/Log, Phase Acceptance Reviews, Production Readiness Reviews) and supersedes any informal governance instructions. **This document is the SOLE source of the Constitutional Hierarchy.**
* **Amendment:** Immutable in place. Amendments happen only via a superseding version whose adoption is recorded in `/app/governance/RATIFICATION_LOG.md`.

---

## 1. Purpose

The Governance Constitution exists to guarantee that:

1. Every architectural decision has a numbered constitutional citation.
2. Every implementation authorisation (Key 2) passes a mechanical, evidence-producing validation gate.
3. Every constitutional artifact is loadable, versioned, and hashed.
4. Every amendment is Operator-authorised and logged; no silent edits.
5. The repository can, at any moment, be verified as constitutionally consistent — or the exact non-compliance can be produced with evidence.

## 2. Constitutional Hierarchy (SINGLE canonical hierarchy)

This §2 supersedes every prior hierarchy statement (including CR-001 v2 §H, which is now amended via CR-001 v2.1 to reference this section). Higher levels prevail on conflict; the same level requires explicit amendment.

| Level | Artifact | Authoritative path |
| --- | --- | --- |
| **L1** | **Foundation Specification** | `/app/blueprints/foundation/FOUNDATION_SPECIFICATION.md` |
| **L2** | **Product Requirements Document (PRD)** | `/app/memory/PRD.md` |
| **L3** | **Master ADR Index & Individual ADRs** | `/app/contracts/v1/adr/ADR_INDEX.md` + `/app/contracts/v1/adr/ADR-NNNN-*.md` |
| **L4** | **Phase Specifications & Blueprint Packages** | `/app/blueprints/phase*/PHASE*_SPEC.md`, `/app/blueprints/phase*/PHASE*_BLUEPRINT.md` |
| **L5** | **Slice Roadmaps, Acceptance Reviews, Governance Reports** | `/app/blueprints/phase*/PHASE*_ROADMAP_RECONCILIATION.md`, `/app/audit/PHASE-*-*.md`, `/app/governance/reports/*.md` |

### 2.1 Conflict resolution rule
Where conflicts exist, the higher constitutional level prevails **unless explicitly amended through constitutional procedure** (Operator-authored amendment + Ratification Log entry). No agent may silently choose between conflicting levels.

### 2.2 Foundation-vs-PRD precedence (RESOLVED)
The formerly-open Foundation-vs-PRD precedence question is resolved: **Foundation Specification prevails over PRD.md** on architectural matters. PRD prevails only where the Foundation is silent (typical case: product-level requirements, timelines, user-experience specifics).

### 2.3 Constitutional Rules (CR-series) placement
Constitutional Rules (CR-001, CR-002, …) are governance operating procedures. They are NOT part of the hierarchy in §2 — they operate ACROSS all levels to enforce the hierarchy. CR-001 v2.1 references THIS Constitution as the sole source of the hierarchy.

## 3. Immutable Design Principles (summarized)

* Domain-Driven Design; bounded contexts (Foundation §2).
* Canonical LandVault aggregate root (Foundation §3; ADR-0001).
* Repository pattern with automatic tenant scoping (Foundation §4; ADR-0003).
* Centralized Authorization Engine (Foundation §5; ADR-0002).
* Event-Driven with transactional outbox (Foundation §6; ADR-0004).
* Append-only Audit (Foundation §11 ADR-0005).
* API-First (Foundation §7; ADR-0006).
* Evidence immutability (Foundation §11 ADR-0009; extended by ADR-0015/0016).
* Platform Kernel is immutable (Foundation ADR-012 / canonical ADR-0012).
* Internal services communicate through stable contracts (Foundation ADR-013 / canonical ADR-0013).
* Anti-Corruption Layer for all external integration (Foundation §13).
* AI is advisory only, never authoritative (Foundation §14).
* Legal Record Classification: Operational / Legal / Evidence / Audit (Foundation §15).

## 4. Evidence-First Philosophy

Every governance assertion MUST be answered with cited evidence. Marking a check "PASS" without cited evidence is a governance violation. Details in CR-001 §B.

## 5. Two-Key Authorisation Model

* **Key 1 — Architecture Approval.** Blueprint / ADR / Phase Spec approval. Grants planning authority only. No code may land under Key 1 alone.
* **Key 2 — Implementation Authority.** A scope-limited authorisation to write code for a specific slice. Requires a passing Governance Validation Report per CR-001 §D before implementation begins.
* Generic approvals ("Proceed", "Approved", "Continue") NEVER constitute Key 2.

## 6. Repository Freeze Model

* After every slice's Acceptance Review passes, the Operator records an immutable freeze SHA / annotated tag in `/app/governance/SLICE_STATE.md`.
* A frozen slice's freeze anchor is immutable once set (SLICE_STATE.md v1.1 §Immutable columns).
* No slice may automatically progress to the next; each new slice requires its own Key 2.

## 7. Blueprint Approval / Implementation Authorisation

| Artifact | Requires |
| --- | --- |
| New Blueprint (Phase spec) | Operator ratification + Ratification Log entry |
| New ADR | Operator ratification + `ADR_INDEX.md` amendment (four-digit form) + Ratification Log entry |
| New Slice | Operator Key 1 (blueprint) then Key 2 (implementation) |
| Amendment to any L1–L3 artifact | Version bump + Ratification Log entry — never silent |

## 8. Constitutional Gate Definitions

Constitutional Gates are the seven CR-001 §D checks — ADR / Slice / Dependency / Acceptance Gate / Repository State / Contract / Architectural. All must PASS with evidence before implementation. See CR-001 v2.1 §D.

## 9. Loadability

Every artifact required by CR-001 §F is enumerated in `/app/governance/CONSTITUTIONAL_LOADABILITY_MATRIX.md` with `Required` and `Loaded` columns. A `Required=YES` artifact with `Loaded=NO` is an automatic FAIL for any Key 2 pre-flight.

## 10. Governance Validation Process

Defined by CR-001 v2.1. Summary: for each Key 2, produce a completed Governance Validation Report per `/app/governance/templates/GOVERNANCE_VALIDATION_REPORT.template.md`, append a PASS/FAIL/BREAK-GLASS entry to `/app/governance/GOVERNANCE_VALIDATION_LOG.md`, and act per outcome.

## 11. Amendment Process (Governance Amendment Procedure — GAP)

Governance artifacts are amended only through the GAP.

| GAP class | Trigger | Version bump | Requires |
| --- | --- | --- | --- |
| **MAJOR** | Change to hierarchy or precedence (this §2) | Constitution vX.0 | Explicit Operator directive + Ratification Log entry + amendment of CR-001 to reference the new hierarchy |
| **MINOR** | Add a new required artifact, add a level, add a new CR-series rule | Constitution v1.x | Explicit Operator directive + Ratification Log entry + Loadability Matrix update |
| **EDITORIAL** | Fix a typo or add a citation with no substantive change | Same version | Ratification Log entry noting "editorial" |

No silent edits are permitted at any class.

## 12. Break-Glass Process

Defined by CR-001 §K. Narrowed scope; time-boxed; mandatory post-hoc Acceptance Review within 5 business days; logged in `GOVERNANCE_VALIDATION_LOG.md`; never a bypass of the audit trail.

## 13. Operator Authority

The Operator is the sole authority for:
* Issuing / revoking Key 1 and Key 2.
* Ratifying amendments to L1–L3 artifacts.
* Declaring break-glass.
* Approving new bounded contexts and new ADRs.
* Resolving open questions surfaced by the Reconciliation matrix or by governance reports.

## 14. Agent Authority

The main agent's authority is delegated and constrained:
* MAY produce governance documents on Operator directive.
* MAY execute implementation ONLY under a valid, evidence-passing Key 2.
* MUST refuse any request that would violate CR-001 §D, §E, §F, or §G.
* MUST log every validation run (PASS / FAIL / BREAK-GLASS) in `GOVERNANCE_VALIDATION_LOG.md`.
* MUST NOT invent, synthesize, or paraphrase content that requires Operator authorship.

## 15. Failure Behaviour

Any Constitutional Gate FAIL requires: refuse implementation; name the failed check; identify conflicting artifacts + versions; recommend corrective action; append FAIL to `GOVERNANCE_VALIDATION_LOG.md`; return to frozen state. See CR-001 §G.

## 16. Audit Requirements

* Every access decision is logged via ADR-0005 (append-only audit).
* Every governance validation is logged via CR-001 §I.
* Every constitutional amendment is logged via `RATIFICATION_LOG.md`.
* No log has an edit or delete path.

## 17. Cross-References (canonical set)

| Reference | Path |
| --- | --- |
| Foundation Specification (L1) | `/app/blueprints/foundation/FOUNDATION_SPECIFICATION.md` |
| PRD (L2) | `/app/memory/PRD.md` |
| ADR Index (L3) | `/app/contracts/v1/adr/ADR_INDEX.md` |
| CR-001 v2.1 | `/app/governance/CR-001-GOVERNANCE-DRIFT-PREVENTION.md` |
| Phase 4 Spec / Blueprint (L4) | `/app/blueprints/phase4/PHASE4_SPEC.md`, `/app/blueprints/phase4/PHASE4_BLUEPRINT.md` |
| Phase 4 Roadmap Reconciliation (L5) | `/app/blueprints/phase4/PHASE4_ROADMAP_RECONCILIATION.md` |
| Slice 4.0 Acceptance (L5) | `/app/audit/PHASE-4-SLICE-4.0-ACCEPTANCE.md` |
| Production Readiness Review (L5) | `/app/audit/PRODUCTION-READINESS-REVIEW.md` |
| SLICE_STATE ledger | `/app/governance/SLICE_STATE.md` |
| Governance Validation Report template | `/app/governance/templates/GOVERNANCE_VALIDATION_REPORT.template.md` |
| Governance Validation Log | `/app/governance/GOVERNANCE_VALIDATION_LOG.md` |
| Ratification Log | `/app/governance/RATIFICATION_LOG.md` |
| Constitutional Loadability Matrix | `/app/governance/CONSTITUTIONAL_LOADABILITY_MATRIX.md` |

## 18. Internal Consistency Assertion

As of adoption (2026-07-01):
* Steps 3–6 of the Constitutional Remediation directive are COMPLETE (ADR_INDEX §2 vocabulary compliant; SLICE_STATE row 4.0 freeze SHA immutable; Foundation Specification published verbatim; PHASE4_ROADMAP_RECONCILIATION §8 permanent statements ratified).
* The single canonical hierarchy (§2) is published here and referenced by CR-001 v2.1.
* All Required artifacts in the Loadability Matrix are Loaded=YES with real SHA-256 hashes.

**This Constitution is internally consistent and frozen.**

## 19. End of Constitution
