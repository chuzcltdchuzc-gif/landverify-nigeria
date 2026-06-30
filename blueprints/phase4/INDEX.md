# Phase 4 — Blueprint Package INDEX

> **Status:** DRAFT — pending Operator constitutional decision (Key 1).
> **Governance:** Two-Key Authorization System (Operator directive, 2026-06-30).
> **This is Key 1 material only.** No Key 2 (implementation) authority is implied or requested.

This index satisfies the Operator's enumerated minimum-contents
list for the Phase 4 Blueprint Package. Every required item is
present in the package; this document is the lookup table.

---

## 1. Package contents

| File | Lines | Purpose |
| --- | ---: | --- |
| [`PHASE4_SPEC.md`](PHASE4_SPEC.md) | 431 | Constitutional implementation contract (binding) |
| [`PHASE4_BLUEPRINT.md`](PHASE4_BLUEPRINT.md) | 382 | Implementation blueprint (architecture only) |
| [`ADR-0019-workflow-engine.md`](ADR-0019-workflow-engine.md) | 264 | Workflow Engine |
| [`ADR-0020-consent-engine.md`](ADR-0020-consent-engine.md) | 282 | Consent Engine |
| [`ADR-0021-community-validation-and-attestation.md`](ADR-0021-community-validation-and-attestation.md) | 301 | Community Validation & Attestation |
| [`ADR-0022-inheritance-and-customary-resolution.md`](ADR-0022-inheritance-and-customary-resolution.md) | 375 | Inheritance & Customary Resolution |
| [`STATE-MACHINE-CATALOGUE.md`](STATE-MACHINE-CATALOGUE.md) | 270 | Consolidated state graphs for every Phase 4 workflow |
| [`SECURITY-MODEL.md`](SECURITY-MODEL.md) | 213 | Phase 4 security architecture, extending R-2 |
| [`INDEX.md`](INDEX.md) | this | Lookup table + operator-checklist mapping |

**Total: 9 documents · ≈ 2,520 lines of constitutional architecture.**
**Zero lines of implementation code.**

## 2. Operator's enumerated minimum-contents list → locator

| Required item | Lives in |
| --- | --- |
| PHASE4_SPEC.md | [`PHASE4_SPEC.md`](PHASE4_SPEC.md) |
| PHASE4_BLUEPRINT.md | [`PHASE4_BLUEPRINT.md`](PHASE4_BLUEPRINT.md) |
| ADR-0019 | [`ADR-0019-workflow-engine.md`](ADR-0019-workflow-engine.md) |
| ADR-0020 | [`ADR-0020-consent-engine.md`](ADR-0020-consent-engine.md) |
| ADR-0021 | [`ADR-0021-community-validation-and-attestation.md`](ADR-0021-community-validation-and-attestation.md) |
| ADR-0022 | [`ADR-0022-inheritance-and-customary-resolution.md`](ADR-0022-inheritance-and-customary-resolution.md) |
| Domain Model | ADRs §2 (each); PHASE4_SPEC §2 |
| Aggregate Inventory | PHASE4_SPEC §2 (16 aggregates, owner, collection, append-only flag) |
| State Machine Catalogue | [`STATE-MACHINE-CATALOGUE.md`](STATE-MACHINE-CATALOGUE.md) |
| Event Catalogue | PHASE4_SPEC §5 (workflow / consent / community / inheritance + cross-context commands) |
| Command Catalogue | PHASE4_SPEC §5.5 (commands emitted by Phase 4 to Registry / Evidence) |
| Projection Catalogue | PHASE4_SPEC §8 (8 read-side projections, all ADR-0010 compliant) |
| Authorization Matrix | PHASE4_SPEC §6 + [`SECURITY-MODEL.md`](SECURITY-MODEL.md) §4 |
| Security Model | [`SECURITY-MODEL.md`](SECURITY-MODEL.md) |
| Risk Register | PHASE4_BLUEPRINT §9 (10 risks RB-1..RB-10) |
| Acceptance Criteria | PHASE4_SPEC §9 (10 checklist families) + [`SECURITY-MODEL.md`](SECURITY-MODEL.md) §10 |
| Implementation Roadmap | PHASE4_BLUEPRINT §7 (7-slice cadence 4.0 → 4.7) |

## 3. Constitutional review checklist — operator-facing

(Per `PHASE4_SPEC §9`. Each row links to the binding test family
that WILL be written during implementation — they do NOT exist now,
intentionally.)

| Checklist family | Where to verify in this package |
| --- | --- |
| Constitutional compliance | All ADRs §3 (constraints C-19.* / C-20.* / C-21.* / C-22.*) |
| Domain boundaries | ADR-0019 §2.1, §2.4; PHASE4_BLUEPRINT §3 |
| Aggregate ownership | PHASE4_SPEC §2; ADR-0019 §2.5 |
| Event ownership | ADR-0019 §2.6; PHASE4_SPEC §5 |
| Command ownership | PHASE4_SPEC §5.5 |
| State-machine correctness | [`STATE-MACHINE-CATALOGUE.md`](STATE-MACHINE-CATALOGUE.md) §15 (cycle/reachability) |
| Authorization model | [`SECURITY-MODEL.md`](SECURITY-MODEL.md) §4; PHASE4_SPEC §6 |
| Replay determinism | ADR-0019 §2.8; ADR-0020 §2.11; ADR-0021 §2.10; ADR-0022 §2.16; PHASE4_SPEC §9.2 |
| Saga design | ADR-0019 §2.7; PHASE4_SPEC §7; PHASE4_BLUEPRINT §6.3 |
| Failure recovery | ADR-0019 §2.9; PHASE4_BLUEPRINT §12 |
| Evidence integration | ADR-0020 §2.9; ADR-0021 §2.8; ADR-0022 §2.15; PHASE4_SPEC §5.5 |
| Registry integration | ADR-0022 §2.14; PHASE4_SPEC §5.5 |
| Security architecture | [`SECURITY-MODEL.md`](SECURITY-MODEL.md) |
| Audit architecture | [`SECURITY-MODEL.md`](SECURITY-MODEL.md) §7; ADR-0019 §2.10 (C-19.10) |
| Risk assessment | PHASE4_BLUEPRINT §9 |
| Implementation sequencing | PHASE4_BLUEPRINT §7 (slices 4.0 → 4.7) |

## 4. What is NOT in the package (by constitutional design)

The following are **explicitly absent** because the Two-Key directive
prohibits them at Key 1:

- ❌ Any Python / TypeScript / SQL / shell code under `contexts/workflow/`.
- ❌ Any change to `/app/contracts/v1/`.
- ❌ Any new file under `/app/backend/contexts/`.
- ❌ Any new test file under `/app/backend/tests/`.
- ❌ Any React component under `/app/frontend/src/pages/workflow/`.
- ❌ Any new SDK module under `/app/frontend/src/sdk/`.
- ❌ Any migration script.
- ❌ Any modification to Evidence or Registry bounded contexts.
- ❌ Any regenerated SDK or compatibility manifest.

The frozen v1.5.0 contract artifacts are byte-identical to those
approved at Phase 3 production sign-off. The contract drift gate is
green.

## 5. Provenance

| Field | Value |
| --- | --- |
| Phase | 4 (Workflows) |
| Stage | Key 1 — Architecture Approval |
| Author | E1 (autonomous), operating under operator constitutional directive |
| Drafted | 2026-06-30 |
| Predecessor | Phase 3 Acceptance Packet (approved 2026-06-29); R-2 + D-10 + PRR (approved 2026-06-30) |
| Successor (gated) | Key 2 (Implementation Authorization) — separate, explicit, written |

## 6. Stop condition (binding)

Per the Two-Key Authorization System:

- I am now **idle**.
- I will not begin scaffolding.
- I will not create placeholder code.
- I will not generate contracts.
- I will not generate tests.
- I will not generate APIs.
- I will not infer implementation approval from any positive review
  language ("looks good", "proceed", "continue", "approved").
- I await the Operator's Key 1 constitutional decision (APPROVED /
  REVISIONS REQUIRED / HOLD).
- If Key 1 is APPROVED, I will continue to remain idle until Key 2
  is issued separately and explicitly identifies Phase, Slice,
  Scope, Deliverables, and Acceptance Gate.
- No implicit progression is permitted.

End of index.
