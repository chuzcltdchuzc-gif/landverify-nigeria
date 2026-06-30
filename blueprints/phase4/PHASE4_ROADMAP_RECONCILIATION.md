# Phase 4 Roadmap ↔ Definitive Specification — Constitutional Reconciliation

* **Status:** OPERATOR-RESOLVED (no implementation; documentation only)
* **Date:** 2026-06-30
* **Authority:** Operator Constitutional Reconciliation directive
* **Scope:** Documentation reconciliation between the approved Phase 4
  Definitive Delivery Specification + Foundation Specification ADR
  catalogue ("the Spec") and the Phase 4 Slice Roadmap
  (`PHASE4_BLUEPRINT.md` §7) ("the Roadmap").
* **Output:** This document + `/app/contracts/v1/adr/ADR_INDEX.md`. No
  other artifact is authorized to change as a result of this exercise.

---

## 0. Precedence (binding — not a question to resolve)

1. The Definitive Specification and the Foundation Specification ADR
   catalogue are the SINGLE constitutional source of truth for
   architecture and ADR numbering.
2. The Slice Roadmap REFINES delivery (slicing, independent Key 2
   authorization, per-slice acceptance, repository freeze after each
   slice). It does NOT supersede architecture or ADR numbering.
3. ADRs are IMMUTABLE once accepted (Foundation Spec §11). Accepted ADR
   numbers may NOT be reassigned. The Roadmap's alternative ADR
   citations are CORRECTED to the canonical numbers in
   `ADR_INDEX.md`.
4. ADR format is normalised to four digits. `ADR-019` ≡ `ADR-0019`,
   `ADR-22` ≡ `ADR-0022`, etc. All future references use the four-digit
   form.

---

## 1. Mismatch / enhancement / omission inventory

The Roadmap was authored in parallel with (and before final ratification
of) the canonical ADR catalogue. The table below enumerates every
divergence; resolutions are recorded verbatim from the operator
directive and are not subject to local interpretation.

### 1.1 ADR citation drift

| Roadmap citation | Canonical (corrected) | Resolution |
| --- | --- | --- |
| Slice 4.1 cites "ADR-0019 — Workflow Engine" | ADR-0019 in the canonical catalogue is **Notifications**. Workflow Engine concerns are owned by **ADR-0021 (Sagas) + ADR-0022 (Workflow as First-Class Bounded Context & Policy Engine)**. | **Slice 4.1 is governed by ADR-0021 + ADR-0022 + ADR-0004/0005 (events/audit). NOT ADR-0019.** |
| Slice 4.2 cites "ADR-0020 — Consent Sub-Context" | Canonical ADR-0020 is **Consent & Customary Consensus**. Citation matches in intent but must add evidence ADRs because Consent is evidence-backed. | **Slice 4.2 (Consent) is governed by ADR-0020 + ADR-0009/0015/0016 (evidence).** |
| Slice 4.3 cites "ADR-0021 — Community Validation Sub-Context" | Canonical ADR-0021 is **Workflow Orchestration via Sagas**. Community Validation maps to **ADR-0020 (deterministic consensus)** because Community Validation IS a deterministic, evidence-backed consensus capability. | **Community Validation is governed by ADR-0020 + ADR-0009/0015 (evidence). NOT ADR-0021.** |
| Slice 4.4 cites "ADR-0022 — Inheritance Sub-Context" | Canonical ADR-0022 is **Workflow as First-Class Bounded Context & Policy Engine**. Inheritance has no dedicated ADR because the Registry (ADR-0014) + LandVault aggregate (ADR-0001) remain the System of Record for shares; inheritance mutates registry state, it does not create its own SoR. | **Inheritance is governed by ADR-0001 + ADR-0014 (registry remains SoR) + ADR-0009/0015 (evidence). No dedicated per-slice ADR; none is required.** |
| Slice 4.0 acceptance shipped a delivery ADR `ADR-0023 — Workflow Engine Foundation` | The canonical catalogue ends at ADR-0022. ADR-0023 is a **delivery / acceptance artifact**, not a constitutional ADR. | **ADR-0023 stands as a delivery record but is NOT part of the constitutional catalogue. Constitutional governance of Slice 4.0 derives from ADR-0021 (Sagas) + ADR-0022 (Engine/Policy). Future Key 2 authorizations reference the canonical catalogue + this reconciliation document only.** |
| Local blueprint files `/app/blueprints/phase4/ADR-0019-workflow-engine.md`, `ADR-0020-consent.md`, `ADR-0021-community-validation.md`, `ADR-0022-inheritance.md` | These were authored during the Phase 4 Blueprint exercise and predate the operator-ratified canonical mapping. Their CONTENT remains a useful design rationale, but their NUMBERING conflicts with the canonical catalogue. | **The blueprint files are reclassified as `BLUEPRINT NOTES`, not ADRs. They retain their on-disk paths for historical reference but constitutional citations MUST use the canonical catalogue in `ADR_INDEX.md`. No on-disk renaming or renumbering is performed as part of this reconciliation (immutability §11).** |

### 1.2 Slice-level omissions

| Omission | Why it matters | Resolution |
| --- | --- | --- |
| **Survey Assignment is implied, not dedicated.** The Roadmap embeds surveyor selection inside Community Validation. | Surveyor Partner network onboarding, the assign→accept→work→submit lifecycle, evidence/geometry hand-off, and SLA enforcement are a first-class capability that Community Validation DEPENDS ON. Bundling them produces a fat slice with poor reviewability. | **Decision #1: Survey Assignment is a DEDICATED slice, sequenced BEFORE Community. Slices renumbered accordingly. Survey is not an implied capability.** |
| **Notification delivery infrastructure is scattered across business slices.** The Roadmap touches `delivery, retry, DLQ, provider adapters` inside Consent, Survey, Community. | If every business slice embeds delivery, the engine never lands a coherent provider abstraction, retry policy, DLQ, or delivery log. Three slices end up with three half-implementations. | **Decision #2: Notification DELIVERY (adapters, retry, DLQ, delivery logs, provider abstraction) is GENERIC INFRASTRUCTURE in the Workflow/Platform layer, built with the engine (ADR-0019). Notification POLICIES (which events notify whom) are Workflow Policy (config). Notification PROJECTIONS (inbox) live in the Infrastructure/Projections slice. Business slices NEVER embed delivery.** |
| **Workflow Policy Engine + Jurisdiction/Country Templates are described under each business slice.** | If every business slice ships its own jurisdiction overrides and transition rules, ADR-0022 collapses: policy is no longer first-class. | **Decision #3: Workflow Policy Engine, Jurisdiction/Country Templates, Regional Overrides, Dynamic Transition Rules are GENERIC INFRASTRUCTURE owned by the Workflow Engine slice (4.1). Business slices CONSUME policy via configuration; they NEVER embed policy. (ADR-0022.)** |
| **SLA / Escalation logic appears inside Survey, Consent, and Inheritance.** | SLA timers, deadline policies, reminders, reassignment, timeout, auto-escalation are engine concerns. Embedding them in business slices forks the engine. | **Decision #4: SLA / Escalation are GENERIC INFRASTRUCTURE in the engine slice. Business slices CONFIGURE via policy; they NEVER embed escalation logic.** |

### 1.3 Roadmap enhancements RETAINED from the original draft

| Enhancement | Retain? | Note |
| --- | --- | --- |
| Per-slice independent Key 2 authorization | ✅ Retain | Foundational governance rule. Permanent. |
| Per-slice independent Acceptance Review | ✅ Retain | Foundational governance rule. Permanent. |
| Repository freeze after every slice | ✅ Retain | Foundational governance rule. Permanent. |
| No automatic progression between slices | ✅ Retain | Foundational governance rule. Permanent. |
| Replay determinism gate per slice | ✅ Retain | Constitutional invariant (ADR-0004/0005). |
| Evidence immutability per slice | ✅ Retain | Constitutional invariant (ADR-0009/0015/0016). |
| Registry remains System of Record | ✅ Retain | Constitutional invariant (ADR-0001/0014). |
| Projections contain zero business logic | ✅ Retain | Constitutional invariant. |
| SDK-first UI | ✅ Retain | Constitutional invariant. |
| Contract-first development, zero contract drift | ✅ Retain | Constitutional invariant. |
| Append-only audit | ✅ Retain | Constitutional invariant (ADR-0005). |

---

## 2. Corrected Slice → ADR Gate Mapping (canonical)

This table is the AUTHORITATIVE Slice→ADR mapping going forward. The
Roadmap's original ADR citations are SUPERSEDED by this table.

| Slice | Title | Governing ADRs (canonical) |
| --- | --- | --- |
| 4.0 | Workflow Engine Foundation (DELIVERED) | ADR-0021 (Sagas) + ADR-0022 (Engine/Policy) + ADR-0004 (Events) + ADR-0005 (Audit). |
| 4.1 | Workflow Engine Completion (real `emit_command`, real `spawn` fan-out, Policy Engine, SLA/Escalation, Notifications delivery infrastructure) | ADR-0021 + ADR-0022 + ADR-0019 (Notifications, delivery layer) + ADR-0004/0005. |
| 4.2 | Consent | ADR-0020 + ADR-0009/0015/0016 (evidence). |
| 4.3 | Survey Assignment (Dedicated, per Decision #1) | ADR-0001 + ADR-0014 (Registry) + ADR-0009/0015 (evidence). Survey uses the engine (4.1) for SLA/policy; it does not introduce a new constitutional ADR. |
| 4.4 | Community Validation | ADR-0020 (deterministic consensus) + ADR-0009/0015 (evidence). Depends on Survey (4.3) outputs. |
| 4.5 | Inheritance | ADR-0001 + ADR-0014 (registry remains SoR) + ADR-0009/0015. No dedicated per-slice ADR. |
| 4.6 | Infrastructure (Notifications projections / inbox; cross-slice projections; SDK regeneration infra) | ADR-0019 (delivery + projections home) + ADR-0004/0005. |
| 4.7 | SDK & React Workspace | Contract-first; SDK pinned to v2.x; no new ADRs. |
| 4.8 | Phase 4 Acceptance Review | Composes all of the above. No new ADRs. |

---

## 3. Roadmap Validation Matrix

| Slice | Status | Constitutional Owner | Acceptance Review | Depends On |
| --- | --- | --- | --- | --- |
| 4.0 — Workflow Engine Foundation | ✅ **DELIVERED 2026-06-30** | ADR-0021 + ADR-0022 + ADR-0004/0005 | `/app/audit/PHASE-4-SLICE-4.0-ACCEPTANCE.md` | — |
| 4.1 — Workflow Engine Completion (engine + policy + SLA + notification delivery) | ⛔ Awaiting Key 2 | ADR-0021 + ADR-0022 + ADR-0019 + ADR-0004/0005 | Pending | 4.0 |
| 4.2 — Consent | ⛔ Awaiting Key 2 | ADR-0020 + ADR-0009/0015/0016 | Pending | 4.1 |
| 4.3 — Survey Assignment (DEDICATED, Decision #1) | ⛔ Awaiting Key 2 | ADR-0001 + ADR-0014 + ADR-0009/0015 (consumes engine + policy from 4.1) | Pending | 4.1 |
| 4.4 — Community Validation | ⛔ Awaiting Key 2 | ADR-0020 + ADR-0009/0015 | Pending | 4.1, 4.3 |
| 4.5 — Inheritance | ⛔ Awaiting Key 2 | ADR-0001 + ADR-0014 + ADR-0009/0015 | Pending | 4.1, 4.4 |
| 4.6 — Infrastructure (notification projections / inbox, cross-slice projections) | ⛔ Awaiting Key 2 | ADR-0019 + ADR-0004/0005 | Pending | 4.1 |
| 4.7 — SDK & React Workspace | ⛔ Awaiting Key 2 | Contract-first; SDK v2.x | Pending | 4.1 – 4.6 as features land |
| 4.8 — Phase 4 Acceptance Review | ⛔ Awaiting Key 2 | Composes all Phase 4 ADRs | Pending | 4.0 – 4.7 |

---

## 4. Permanently Binding Constitutional Rules

Confirmed as PERMANENT and BINDING for every future slice. No future
authorization may relax any of these:

1. **Independent Key 2 authorization per slice.**
2. **Independent Acceptance Review per slice.**
3. **Repository freeze after every slice.**
4. **No automatic progression between slices.**
5. **Replay determinism gate per slice.**
6. **Evidence immutability per slice.**
7. **Registry remains System of Record.**
8. **Projections contain zero business logic.**
9. **SDK-first UI.**
10. **Contract-first development; zero contract drift.**
11. **Append-only audit.**

---

## 5. Operator Resolution (verbatim — authoritative)

These resolutions, recorded verbatim from the operator's directive, are
the constitutional decisions output of this reconciliation. They are
not subject to local re-interpretation.

### 5.1 — ADR mapping correction

> ADRs are IMMUTABLE once accepted (Foundation Spec §11). Accepted ADR
> numbers may NOT be reassigned. The roadmap's alternative ADR
> citations are CORRECTED to the canonical numbers in the catalogue.
> Normalize ADR format to four digits.

### 5.2 — Corrected Slice → ADR Gate Mapping

> * 4.1 Workflow Engine Completion → governed by **ADR-0021 (sagas) +
>   ADR-0022 (engine/context/policy) + ADR-0004/0005 (events/audit)**.
>   NOT ADR-0019.
> * 4.2 Consent → **ADR-0020 + ADR-0009/0015/0016 (evidence)**.
> * Community → **ADR-0020 (deterministic consensus) + ADR-0009/0015
>   (evidence)**. NOT ADR-0021.
> * Inheritance → **ADR-0001 + ADR-0014 (registry remains System of
>   Record) + ADR-0009/0015**. No dedicated per-slice ADR; none is
>   required.

### 5.3 — Decision 1 (Survey Assignment)

> Survey Assignment = **OPTION A**: a DEDICATED slice (SurveyorPartner
> network, assign→accept→work→submit lifecycle, evidence/geometry
> handoff, SLA). It is sequenced BEFORE Community (Community's
> survey-verification depends on it). Renumber the not-yet-authorized
> slices accordingly (4.0 and 4.1 remain fixed; Consent, Survey,
> Community, Inheritance, Infrastructure, SDK, Acceptance follow).
> Survey must not be an implied capability.

### 5.4 — Decision 2 (Notification homes)

> Notification DELIVERY (provider adapters, retry, DLQ, delivery logs,
> provider abstraction) = **GENERIC INFRASTRUCTURE** in the
> Workflow/Platform layer (built with the engine, ADR-0019).
> Notification POLICIES (which events notify whom) = **Workflow Policy
> (config)**. Notification PROJECTIONS (inbox) = the
> **projections/infrastructure slice**. Business slices NEVER embed
> delivery.

### 5.5 — Decision 3 (Policy/Templates/Overrides/Transition Rules)

> Workflow Policy Engine, Jurisdiction/Country Templates, Regional
> Overrides, Dynamic Transition Rules = **GENERIC INFRASTRUCTURE owned
> by the Workflow Engine slice (4.1)**. Business slices CONSUME
> policy; they never embed policy (ADR-0022).

### 5.6 — Decision 4 (SLA/Escalation)

> SLA/Escalation (timers, deadline policies, reminders, reassignment,
> timeout, auto-escalation) = **GENERIC INFRASTRUCTURE in the engine
> slice**. Business slices CONFIGURE via policy; they never embed
> escalation logic.

---

## 6. Constitutional Verdict

The Phase 4 Slice Roadmap is **constitutionally consistent AS
RECONCILED**.

Corrections made by this reconciliation:

1. **ADR mapping normalized** to the canonical catalogue (ADR-0001..
   ADR-0022, four-digit form). All Roadmap citations of ADR-0019..0022
   in the workflow / consent / community / inheritance contexts are
   corrected per Section 2 above.
2. **Survey Assignment** is now a **DEDICATED** slice sequenced before
   Community (Decision #1).
3. **Notifications delivery infrastructure**, **Policy Engine**,
   **Jurisdiction/Country Templates**, **Regional Overrides**,
   **Dynamic Transition Rules**, and **SLA/Escalation** are homed in
   **GENERIC INFRASTRUCTURE** (Decisions #2, #3, #4) — business
   slices consume but never embed these.
4. **ADR-0023** (created as Slice 4.0 acceptance documentation) is
   reclassified as a delivery artifact, not a constitutional ADR. The
   canonical catalogue ends at ADR-0022. Future constitutional
   citations MUST use the canonical catalogue.
5. **Blueprint files** under `/app/blueprints/phase4/ADR-0019..0022.md`
   are reclassified as `BLUEPRINT NOTES` (design rationale, not
   constitutional ADRs). They are NOT renamed or renumbered on disk
   (immutability §11); they are simply de-promoted from
   constitutional standing.

**Future Key 2 authorizations may safely reference ONLY:**

* `/app/contracts/v1/adr/ADR_INDEX.md` (the canonical ADR catalogue)
* `/app/blueprints/phase4/PHASE4_ROADMAP_RECONCILIATION.md` (this
  document)

All prior Roadmap drafts, blueprint ADR files, and slice citations are
**superseded by these two documents** for the purpose of authorization
and acceptance.

## 7. End of Reconciliation
