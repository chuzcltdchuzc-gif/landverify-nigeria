# Aquasavannah LandVault — Authoritative ADR Catalogue (ADR_INDEX)

* **Status:** OPERATOR-RATIFIED (single source of truth)
* **Date:** 2026-06-30
* **Authority:** Foundation Specification §11 (ADR immutability) +
  Operator Constitutional Reconciliation directive
* **Scope:** This is the authoritative ADR catalogue for the entire
  Aquasavannah LandVault platform. ADR-0001 through ADR-0022 listed
  here are CONSTITUTIONALLY BINDING.

## 0. Conventions

* **Number format:** four digits — `ADR-NNNN`. `ADR-019` ≡ `ADR-0019`,
  `ADR-22` ≡ `ADR-0022`. All future references MUST use the four-digit
  form.
* **Immutability:** ADRs are immutable once accepted (Foundation Spec
  §11). An accepted ADR's NUMBER may never be reassigned; its CONTENT
  may be EXTENDED or AMENDED by a new ADR but never silently rewritten.
* **Citation discipline:** When a slice / blueprint / acceptance review
  cites an ADR, it must cite the canonical number from this catalogue.
  Out-of-band ADR numbering (e.g. blueprint-local ADRs) is permissible
  as DESIGN NOTES but is NOT constitutional.
* **Out-of-scope ADRs:** Delivery artifacts (e.g. Slice 4.0's
  `ADR-0023-workflow-engine-foundation.md`) are NOT part of this
  catalogue. They are acceptance records, not constitutional decisions.

---

## 1. Catalogue (ADR-0001 .. ADR-0022)

### Phase 0 — Constitutional Foundation

#### ADR-0001 — LandVault is the canonical aggregate root
* **Purpose:** Establishes the LandVault as the single, canonical
  aggregate root for any parcel of land on the platform. All registry
  state, evidence binding, workflow correlation, and inheritance share
  computation reference the LandVault identity.
* **Status:** ACCEPTED
* **Phase:** 0
* **Supersedes / Extends:** —
* **Related ADRs:** ADR-0003 (repository pattern), ADR-0014 (canonical
  registry aggregate)
* **Related Blueprint:** Phase 1 / Phase 2 Registry blueprints
* **Related Acceptance Review:** Phase 2 Registry Acceptance Packet

#### ADR-0002 — Centralized Authorization Engine (default DENY)
* **Purpose:** All access decisions go through a centralized Policy
  Decision Point (PDP). Default decision is DENY; permits are explicit
  and policy-attributed. No JWT claim introspection inside domain code.
* **Status:** ACCEPTED
* **Phase:** 0
* **Supersedes / Extends:** —
* **Related ADRs:** ADR-0007 (controllers via repositories), ADR-0022
  (workflow policy engine consumes PDP)
* **Related Blueprint:** Platform Kernel Spec §authorization
* **Related Acceptance Review:** Phase 1 Identity Acceptance Packet

#### ADR-0003 — Repository pattern with automatic tenant scoping
* **Purpose:** Persistence is exclusively accessed via repository
  adapters that ENFORCE tenant + country scoping derived from the
  ExecutionContext. Client-supplied tenant_id / country_code values are
  ignored as defense-in-depth.
* **Status:** ACCEPTED
* **Phase:** 0
* **Supersedes / Extends:** —
* **Related ADRs:** ADR-0007 (no direct DB), ADR-0008 (transactions)
* **Related Blueprint:** Platform Kernel Spec §persistence
* **Related Acceptance Review:** Phase 1 / Phase 2 / Phase 3 Acceptance Packets

#### ADR-0004 — Event-Driven Architecture
* **Purpose:** Domain state changes are published as immutable events
  via the transactional outbox. Cross-context coordination uses events
  + sagas, never synchronous calls into other bounded contexts.
* **Status:** ACCEPTED
* **Phase:** 0
* **Supersedes / Extends:** —
* **Related ADRs:** ADR-0005 (audit), ADR-0021 (sagas), ADR-0022
  (workflow engine subscribes/emits)
* **Related Blueprint:** Platform Kernel Spec §events
* **Related Acceptance Review:** Phase 3 Acceptance Packet (anchor / replay)

#### ADR-0005 — Append-only Audit
* **Purpose:** Every authorization decision and every audit-relevant
  business event is appended to a tamper-evident audit log. No in-place
  mutation; no deletion.
* **Status:** ACCEPTED
* **Phase:** 0
* **Supersedes / Extends:** —
* **Related ADRs:** ADR-0004 (events), ADR-0009 (evidence immutability)
* **Related Blueprint:** Platform Kernel Spec §audit
* **Related Acceptance Review:** Phase 1 / Phase 3 Acceptance Packets

#### ADR-0006 — API First
* **Purpose:** Public capability is defined by the OpenAPI contract
  before code lands. Contract artifacts are governed by a drift gate;
  any deviation fails CI.
* **Status:** ACCEPTED
* **Phase:** 0
* **Supersedes / Extends:** —
* **Related ADRs:** ADR-0013 (stable contracts)
* **Related Blueprint:** Platform Kernel Spec §contract
* **Related Acceptance Review:** Every phase acceptance includes the
  drift gate.

#### ADR-0007 — No direct DB access from controllers
* **Purpose:** HTTP routers / controllers compose application services
  only. They never call repository adapters or Mongo collections
  directly. Routers are composition only.
* **Status:** ACCEPTED
* **Phase:** 0
* **Supersedes / Extends:** —
* **Related ADRs:** ADR-0003 (repositories)
* **Related Blueprint:** Platform Kernel Spec §architecture
* **Related Acceptance Review:** Every phase Acceptance Packet

#### ADR-0008 — Every financial mutation uses transactions
* **Purpose:** Any state change with monetary or balance semantics is
  wrapped in a Mongo replica-set transaction. No partial credit, no
  partial debit, no orphaned outbox envelopes.
* **Status:** ACCEPTED
* **Phase:** 0
* **Supersedes / Extends:** —
* **Related ADRs:** ADR-0004 (events written in the same txn)
* **Related Blueprint:** Platform Kernel Spec §persistence §transactions
* **Related Acceptance Review:** Phase 2 / Phase 3 Acceptance Packets

#### ADR-0009 — Evidence is immutable
* **Purpose:** Once recorded, an evidence item is content-addressed and
  cannot be edited. Evidence items can only be sealed, superseded, or
  legal-held. Deletion is prohibited; supersession is the only
  authorized "edit" path.
* **Status:** ACCEPTED (extended by ADR-0015)
* **Phase:** 0
* **Supersedes / Extends:** —
* **Related ADRs:** ADR-0015 (tamper-evidence), ADR-0016 (server-auth
  hashing + WORM), ADR-0017 (court-admissible export), ADR-0018
  (residency)
* **Related Blueprint:** Phase 3 Evidence Bounded Context spec
* **Related Acceptance Review:** Phase 3 Evidence Acceptance Packet

#### ADR-0010 — Platform independence
* **Purpose:** Aquasavannah LandVault is operable independently of any
  single cloud provider, single jurisdiction, or single tenant.
  Adapters are pluggable; the kernel is provider-agnostic.
* **Status:** ACCEPTED
* **Phase:** 0
* **Supersedes / Extends:** —
* **Related ADRs:** ADR-0011 (platform-not-application)
* **Related Blueprint:** Foundation Spec §portability
* **Related Acceptance Review:** PRR (Production Readiness Review)

#### ADR-0011 — LandVault is a platform, not an application
* **Purpose:** Aquasavannah LandVault delivers capabilities to many
  tenant governments / institutions. It is not a single-tenant
  application; multi-tenancy, country-scoping, and per-tenant policy
  are first-class.
* **Status:** ACCEPTED
* **Phase:** 0
* **Supersedes / Extends:** —
* **Related ADRs:** ADR-0010 (independence), ADR-0018 (per-tenant KMS)
* **Related Blueprint:** Foundation Spec §platform
* **Related Acceptance Review:** Every phase Acceptance Packet

#### ADR-0012 — Platform Kernel is immutable
* **Purpose:** The Platform Kernel (audit, authorization, outbox,
  projections, security headers, execution context) is constitutional
  infrastructure. Changes require a new ADR + phase acceptance, not
  ad-hoc edits.
* **Status:** ACCEPTED
* **Phase:** 0
* **Supersedes / Extends:** —
* **Related ADRs:** ADR-0002, ADR-0004, ADR-0005, ADR-0007
* **Related Blueprint:** Platform Kernel Spec
* **Related Acceptance Review:** Every phase Acceptance Packet

#### ADR-0013 — Internal services communicate through stable contracts
* **Purpose:** Bounded contexts communicate only via the contract
  package — events, schemas, SDKs. Direct cross-context calls or shared
  internal types are prohibited.
* **Status:** ACCEPTED
* **Phase:** 0
* **Supersedes / Extends:** —
* **Related ADRs:** ADR-0006 (API first), ADR-0004 (events)
* **Related Blueprint:** Foundation Spec §contracts
* **Related Acceptance Review:** Every phase Acceptance Packet

---

### Phase 2 — Registry

#### ADR-0014 — Canonical Registry Aggregate
* **Purpose:** Defines `registry_id` (internal opaque), `parcel_number`
  (public canonical), and `legacy_aliases` for migration. The Registry
  remains the System of Record for parcel identity and any
  share/inheritance state derived from it.
* **Status:** ACCEPTED (extends ADR-0001)
* **Phase:** 2
* **Supersedes / Extends:** Extends ADR-0001
* **Related ADRs:** ADR-0001, ADR-0003
* **Related Blueprint:** Phase 2 Registry Spec
* **Related Acceptance Review:** Phase 2 Registry Acceptance Packet

---

### Phase 3 — Evidence

#### ADR-0015 — Evidence Immutability & Tamper-Evidence
* **Purpose:** Specifies content hashing, append-only sealing and
  locking, and external anchoring. **Amended to REQUIRE operational
  Merkle anchoring + WORM** before any legal-defensibility claims are
  made.
* **Status:** ACCEPTED (extends ADR-0009; amended)
* **Phase:** 3
* **Supersedes / Extends:** Extends ADR-0009
* **Related ADRs:** ADR-0009, ADR-0016, ADR-0017, ADR-0018
* **Related Blueprint:** Phase 3 Evidence Bounded Context spec
* **Related Acceptance Review:** Phase 3 Evidence Acceptance Packet

#### ADR-0016 — Server-Authoritative Evidence Hashing & WORM Storage
* **Purpose:** Hashes are computed server-side, never trusting client
  inputs. Evidence binary artifacts are persisted to WORM storage
  (Write-Once-Read-Many). Server signs and timestamps the hash record.
* **Status:** ACCEPTED (extends ADR-0015)
* **Phase:** 3
* **Supersedes / Extends:** Extends ADR-0015
* **Related ADRs:** ADR-0015, ADR-0018
* **Related Blueprint:** Phase 3 Evidence spec §hashing §storage
* **Related Acceptance Review:** Phase 3 Acceptance Packet

#### ADR-0017 — Court-Admissible Evidence Export & Independent Verification
* **Purpose:** Defines an export bundle (evidence + Merkle proof +
  signed timestamp + chain-of-custody) that an independent verifier
  can validate offline. Establishes the legal-defensibility format.
* **Status:** ACCEPTED
* **Phase:** 3
* **Supersedes / Extends:** —
* **Related ADRs:** ADR-0015, ADR-0016
* **Related Blueprint:** Phase 3 Evidence spec §export §verification
* **Related Acceptance Review:** Phase 3 Acceptance Packet (court-export gate)

#### ADR-0018 — Per-Tenant / Per-Country Key Management & Evidence Residency
* **Purpose:** Each tenant / country has dedicated KMS keys and a
  residency policy that constrains where evidence binaries may be
  stored / replicated. Keys are operator-managed (envelope encryption);
  residency is policy-enforced.
* **Status:** ACCEPTED
* **Phase:** 3
* **Supersedes / Extends:** —
* **Related ADRs:** ADR-0011 (platform), ADR-0016 (server hashing)
* **Related Blueprint:** Phase 3 Evidence spec §residency §kms
* **Related Acceptance Review:** Phase 3 Acceptance Packet

---

### Phase 4 — Workflow & Consensus

#### ADR-0019 — Notifications as a non-authoritative delivery capability
* **Purpose:** Notifications (in-app inbox, email, SMS) are a
  DELIVERY capability. They are NEVER authoritative — they convey
  state that is recorded authoritatively elsewhere (events, registry,
  evidence). Delivery provider adapters (retry, DLQ, delivery logs)
  live in generic platform infrastructure; the inbox is a projection;
  policy ("which event notifies whom") is workflow policy. Business
  slices NEVER embed delivery.
* **Status:** ACCEPTED
* **Phase:** 4
* **Supersedes / Extends:** —
* **Related ADRs:** ADR-0004 (events), ADR-0022 (policy engine)
* **Related Blueprint:** `/app/blueprints/phase4/PHASE4_ROADMAP_RECONCILIATION.md` §1.2 Decision #2
* **Related Acceptance Review:** Slice 4.1 (delivery infrastructure) and Slice 4.6 (projections / inbox)

#### ADR-0020 — Consent & Customary Consensus are deterministic, evidence-backed, human-authoritative
* **Purpose:** Both Consent (individual) and Customary Consensus
  (community) flows are DETERMINISTIC — the same inputs produce the
  same outcome bit-for-bit — and HUMAN-AUTHORITATIVE — they are
  authenticated by human actors and persisted as immutable evidence.
  No ML / probabilistic scoring may drive the outcome.
* **Status:** ACCEPTED
* **Phase:** 4
* **Supersedes / Extends:** —
* **Related ADRs:** ADR-0009 / ADR-0015 / ADR-0016 (evidence
  immutability + tamper-evidence + server hashing)
* **Related Blueprint:** `/app/blueprints/phase4/PHASE4_ROADMAP_RECONCILIATION.md` §2 (Slices 4.2 and 4.4)
* **Related Acceptance Review:** Slice 4.2 (Consent) and Slice 4.4 (Community Validation)

#### ADR-0021 — Workflow Orchestration via Sagas
* **Purpose:** Cross-context coordination is implemented as sagas:
  long-running, replayable, compensating workflows driven by events.
  No bounded context performs cross-context writes; only sagas (in the
  Workflow context) compose cross-context effects.
* **Status:** ACCEPTED
* **Phase:** 4
* **Supersedes / Extends:** Extends ADR-0004 in the cross-context plane
* **Related ADRs:** ADR-0004 (events), ADR-0022 (engine)
* **Related Blueprint:** `/app/blueprints/phase4/PHASE4_ROADMAP_RECONCILIATION.md` §2 (Slices 4.0 and 4.1)
* **Related Acceptance Review:** Slice 4.0 Foundation (delivered) — `/app/audit/PHASE-4-SLICE-4.0-ACCEPTANCE.md`; Slice 4.1 (pending)

#### ADR-0022 — Workflow as a First-Class Bounded Context & Policy Engine
* **Purpose:** The Workflow Engine is a first-class bounded context
  with its own aggregates (Definition, Instance, Task, Timer,
  Compensation) and its own POLICY engine (jurisdiction templates,
  regional overrides, dynamic transition rules, SLA/escalation).
  Business slices CONSUME policy via configuration; they NEVER embed
  policy or escalation logic.
* **Status:** ACCEPTED
* **Phase:** 4
* **Supersedes / Extends:** Extends ADR-0021 (sagas)
* **Related ADRs:** ADR-0002 (PDP), ADR-0021 (sagas), ADR-0019
  (notifications policy)
* **Related Blueprint:** `/app/blueprints/phase4/PHASE4_ROADMAP_RECONCILIATION.md` §1.2 Decisions #3 #4
* **Related Acceptance Review:** Slice 4.0 Foundation (delivered) — `/app/audit/PHASE-4-SLICE-4.0-ACCEPTANCE.md`; Slice 4.1 (pending)

---

## 2. Out-of-Catalogue Artifacts (delivery records, NOT constitutional)

The following artifacts EXIST on disk but are NOT constitutional ADRs.
They are reclassified as delivery / acceptance records or blueprint
design notes. They are NOT renamed or renumbered (immutability §11);
they are simply de-promoted from constitutional standing.

| Path | Reclassified as |
| --- | --- |
| `/app/contracts/v1/adr/ADR-0023-workflow-engine-foundation.md` | Slice 4.0 delivery / acceptance record. NOT a constitutional ADR. |
| `/app/blueprints/phase4/ADR-0019-workflow-engine.md` | Phase 4 Blueprint Note — workflow engine design rationale. NOT a constitutional ADR (the canonical ADR-0019 is Notifications). |
| `/app/blueprints/phase4/ADR-0020-consent.md` | Phase 4 Blueprint Note — Consent design rationale. Content is largely consistent with canonical ADR-0020. |
| `/app/blueprints/phase4/ADR-0021-community-validation.md` | Phase 4 Blueprint Note — Community Validation design rationale. NOT a constitutional ADR (the canonical ADR-0021 is Sagas; Community Validation maps to ADR-0020). |
| `/app/blueprints/phase4/ADR-0022-inheritance.md` | Phase 4 Blueprint Note — Inheritance design rationale. NOT a constitutional ADR (Inheritance has no dedicated per-slice ADR per Decision §1.1; canonical ADR-0022 is the Workflow Engine + Policy). |

---

## 3. Authoritative Cross-References

* **Reconciliation document (the only Roadmap citation source):**
  `/app/blueprints/phase4/PHASE4_ROADMAP_RECONCILIATION.md`
* **Phase 3 Acceptance Packet:** `/app/audit/PHASE-3-ACCEPTANCE-PACKET.md`
* **Phase 3 Production Readiness Review:** `/app/audit/PRODUCTION-READINESS-REVIEW.md`
* **Phase 3 Operational Runbook:** `/app/audit/RUNBOOK.md`
* **Slice 4.0 Acceptance Review:** `/app/audit/PHASE-4-SLICE-4.0-ACCEPTANCE.md`

---

## 4. End of Catalogue

Future Key 2 authorizations MUST cite ADRs only by their canonical
number from this catalogue. The Roadmap Reconciliation document is the
only authoritative slice-planning artifact. Together, these two files
constitute the single source of truth for Aquasavannah LandVault's
constitutional architecture going forward.
