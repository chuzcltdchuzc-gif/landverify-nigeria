# FOUNDATION_SPECIFICATION.md

* **Source:** Operator-supplied Phase 0 Foundation Specification (verbatim).
* **Published at:** `/app/blueprints/foundation/FOUNDATION_SPECIFICATION.md`
* **Publish date:** 2026-07-01
* **Immutability:** This document is CONSTITUTIONALLY IMMUTABLE once ratified in `/app/governance/RATIFICATION_LOG.md`. Amendments happen only via a superseding version with a Ratification Log entry (Foundation §11 discipline applied to the Foundation itself).
* **Reconciliation:** Section-by-section citations to already-approved EMERGENT artifacts appear in **Reconciliation Annex** at the end of this file. Annex adds ONLY citations — no rewording of the source, no reinterpretation of any ADR.

---

<!-- BEGIN OPERATOR-SUPPLIED PHASE 0 FOUNDATION SPECIFICATION — VERBATIM -->

# Phase 0 Foundation Specification
AquaSavannah LandVault
Enterprise Foundation Specification
Phase 0 - Foundation
Government-Grade Digital Land Governance Platform
Document type: Architecture specification (design only - no implementation code)
Prepared by: Lead Enterprise Architect
Audience: Chief Architect (review and approval gate before implementation)
Status: Approved in principle - v1.1 with constitutional refinements (ADR-011..013, Anti
Corruption Layer, AI Governance, Legal Record Classification, Enterprise Capability Map)
Date: June 26, 2026
Authority: Derived from, and constrained by, the approved Master Enterprise Architecture 
Blueprint. No decision herein may contradict the Blueprint.
Scope statement. This phase establishes the platform itself, not business features. It 
contains no parcel registration, wallets, certificates, inheritance, AI, fraud, or public 
verification logic. Those are delivered in later phases and must attach to the foundation 
defined here without further architectural decisions.

## Contents
0. Architectural principles (binding)

Every specification in this document is traceable to the following principles. Each principle 
has a defined enforcement point so that compliance is verifiable, not aspirational. No 
implementation may violate a principle; deviations require a new ADR approved by the 
Chief Architect.

| Principle | Meaning for the foundation | Primary enforcement point |
| --- | --- | --- |
| Security by Default | Deny-by-default everywhere; least privilege; no implicit trust | Authorization Engine (section 5) |
| Privacy by Design | PII minimized, classified, encrypted, and projected away by default | Data Standards (section 8), Repository (section 4) |
| API First | Every capability is an API with a contract before it has a UI | API Standards (section 7), OpenAPI |
| Domain Driven Design | Code is organized by bounded context, not technical layer | Domain Structure (section 2) |
| Event Driven | State changes emit immutable events; side effects are subscribers | Event Architecture (section 6) |
| Zero Trust | Identity verified on every call; network location grants nothing | Authorization Engine (section 5) |
| Cloud Native | Stateless services, externalized state, horizontal scale | Infrastructure (section 9) |
| Platform Independent | No proprietary lock-in; portable runtimes and open standards | ADR-010, ADR-013 (section 11) |
| Multi Tenant | Tenant isolation is structural and server-enforced | Repository (section 4), Authz (section 5) |
| Multi Country Ready | Country is a first-class scoping dimension above tenant | Data and Domain (sections 2,8) |
| Immutable Audit | Audit and evidence are append-only; no update/delete path | ADR-005, ADR-009 (section 11) |
| GIS Native | Geospatial data is first-class, indexed, and validated | Data Standards (section 8), GIS domain |
| AI Ready | Clean event stream and read models feed AI without coupling | AI domain (section 2), AI Governance (section 14) |
| Government Grade | Auditability, recoverability, and accountability are non-negotiable | All sections |

## 1. Enterprise folder structure

The platform is organized as a single governed monorepo so that contracts, shared 
libraries, and infrastructure evolve atomically with the services that consume them. The 
backend is structured by bounded context (Domain Driven Design), not by technical layer, 
so that a domain can be reasoned about, tested, and later extracted as an independent 
service without restructuring.

Why a monorepo (recommended over polyrepo): a government platform needs one 
source of truth for API contracts and audit/security primitives. A monorepo guarantees 
that a change to a shared contract cannot be merged without updating every consumer, 
eliminates version-drift between frontend and backend, and keeps the architecture-review 
surface in one place. Independent deployability is preserved because each app and worker 
has its own build and release pipeline.

### 1.1 Top-level layout
```
aquasavannah-landvault/
|– apps/
   |– web/                # React frontend (presentation only)
   |– api/                # FastAPI application (HTTP edge + composition root)
   +– workers/            # Background worker processes (event/queue consumers)
|– contexts/              # Bounded contexts (the heart of the system)
   |– identity/ registry/ landvault/ evidence/ community/
   |– verification/ economics/ gis/ ai/ administration/ integration/
|– platform/              # Cross-cutting platform kernel (shared by all contexts)
   |– authorization/      # Authorization Engine (PEP/PDP/PIP/PAP)
   |– persistence/        # Repository base, unit-of-work, tenant context
   |– events/             # Event bus abstraction, outbox, envelope schema
   |– audit/              # Append-only audit primitives
   |– observability/      # Logging, metrics, tracing, correlation
   |– config/             # Typed configuration and secrets loading
   +– errors/             # Canonical error model (RFC 7807)
|– contracts/             # API and event contracts (OpenAPI, event schemas, DTOs)
|– infra/                 # Infrastructure-as-code and runtime topology
   |– mongodb/ redis/ object-storage/ workers/ gateway/
   |– environments/       # dev / staging / prod / per-country overlays
   +– pipelines/          # CI/CD, security scans, migration runners
|– tests/                 # Cross-cutting suites (contract, e2e, load, security)
|– docs/                  # Architecture docs, ADRs, runbooks, threat models
   +– adr/ runbooks/ diagrams/ threat-models/
+– tooling/               # Dev tooling, generators, lint/format config
```

### 1.2 Internal shape of a bounded context
Every context under contexts/ follows the same internal skeleton so that any engineer can 
navigate any domain. This uniformity is itself an architectural control.
```
contexts/<context>/
|– domain/                # Entities, aggregates, value objects, domain events (pure)
|– application/           # Use-case services, command/query handlers, DTOs
|– ports/                 # Interfaces this context requires (repository, gateways)
|– adapters/              # Implementations of ports (Mongo repo, storage, http clients)
|– events/                # Published and subscribed event definitions + handlers
|– api/                   # API contract surface for this context (router wiring only)
+– tests/                 # Unit + integration tests owned by the context
```

### 1.3 Why each module exists

| Module | Reason it exists |
| --- | --- |
| apps/web | Presentation only. Holds no business rules and no authorization logic; talks to the platform exclusively through versioned APIs via a generated SDK. |
| apps/api | The HTTP edge and composition root. Wires requests to the Authorization Engine and application services. Performs no data access and no business logic itself (ADR-007). |
| apps/workers | Executes asynchronous and scheduled work (event consumers, projections, long-running jobs) so the request path stays fast and stateless. |
| contexts/* | The business itself, isolated by bounded context. Each owns its data, rules, and events. This is where future features live. |
| platform/* | The kernel every context depends on: authorization, persistence base, events, audit, observability, config, errors. Centralizing these makes the binding principles enforceable in one place (ADR-012). |
| contracts/ | Single source of truth for API and event shapes. Generated SDKs and validators derive from here, guaranteeing producer/consumer agreement (API First). |
| infra/ | Declarative runtime topology and environment overlays (including per-country). Makes infrastructure reviewable and reproducible (Cloud Native). |
| tests/ | Cross-cutting suites that no single context owns: contract tests, end-to-end journeys, load and security tests. |
| docs/ (incl. adr/) | The decision record and operational knowledge. ADRs are versioned with the code so architecture and implementation never diverge. |
| tooling/ | Generators and standards (lint, format, codegen) that mechanically enforce conventions instead of relying on reviewer memory. |

## 2. Domain structure (bounded contexts)

The platform is decomposed into eleven bounded contexts plus the platform kernel. 
Contexts communicate through published events and explicit public interfaces only - never 
by reaching into one another's data. The dependency rule is strict: a context may depend on 
the platform kernel and on the published contracts of other contexts, but never on another 
context's internals.

Dependency direction. Identity is foundational and depended upon by all. LandVault is 
the central aggregate domain (see section 3). GIS, Evidence, Community, Verification, 
Economics, and AI attach to LandVault through events and references rather than shared 
tables. Administration and Integration are cross-cutting. This keeps the core registry 
deployable before any satellite capability exists.

### 2.1 Context dependency overview

| Context | Depends on | Depended on by |
| --- | --- | --- |
| Identity | Platform kernel | All contexts |
| Registry | Identity | LandVault, Administration |
| LandVault | Identity, Registry | Evidence, Community, Verification, Economics, GIS, AI |
| Evidence | Identity, LandVault | Verification, AI |
| Community | Identity, LandVault | Verification |
| Verification | Identity, LandVault, Evidence, Community | Economics, AI |
| Economics | Identity, LandVault, Verification | Administration |
| GIS | Identity, LandVault | Verification, AI |
| AI | Read models + events (all) | (advisory only - no write authority) |
| Administration | Identity | All (governance/observability) |
| Integration | Identity, contracts | External systems |

### 2.2 Context specifications

**Identity**

| Aspect | Specification |
| --- | --- |
| Purpose | Establish who is acting, in what role, for which tenant/country/organization, with what scopes. |
| Responsibilities | Authentication, identity lifecycle, role/attribute assignment, service accounts, delegation grants, session and token issuance. |
| Dependencies | Platform kernel only. |
| Public interfaces | Token issuance/refresh; principal resolution; role/attribute query; delegation issuance. |
| Internal services | Credential verification, token signing/rotation, account status, scoped service-account registry. |
| Future expansion | National e-ID integration, federated identity per country, biometric assurance levels, government-to-government delegation. |

**Registry**

| Aspect | Specification |
| --- | --- |
| Purpose | Authoritative catalogue of administrative geography and reference data (country, state, LGA, ward, property types, sequences). |
| Responsibilities | Reference taxonomies, canonical identifiers, sequence/counter custody, code lists used across the platform. |
| Dependencies | Identity. |
| Public interfaces | Reference lookups; identifier allocation; taxonomy resolution. |
| Internal services | Atomic sequence allocation, taxonomy versioning, geography hierarchy. |
| Future expansion | Additional countries' administrative hierarchies, gazetted boundary updates, multilingual code lists. |

**LandVault (canonical aggregate domain)**

| Aspect | Specification |
| --- | --- |
| Purpose | Own the LandVault aggregate root - the single authoritative representation of a unit of land and everything attached to it (see section 3). |
| Responsibilities | LandVault lifecycle and state, identity/reference of the land unit, the attachment points for ownership, survey, evidence, certificates, timeline, GIS, community, inheritance, customary rights, verification, revenue. |
| Dependencies | Identity, Registry. |
| Public interfaces | LandVault creation and lifecycle transitions; reference resolution; attachment-point contracts consumed by satellite contexts. |
| Internal services | Aggregate invariants, state machine, timeline append, optimistic-concurrency guard. |
| Future expansion | Subdivision/merge, 3D/strata volumes, digital-twin linkage, cross-border land units. |

**Evidence**

| Aspect | Specification |
| --- | --- |
| Purpose | Capture and preserve immutable proof artefacts associated with a LandVault. |
| Responsibilities | Evidence intake, immutability sealing, integrity verification, timeline events, retention. |
| Dependencies | Identity, LandVault. |
| Public interfaces | Evidence submission; integrity status query; evidence timeline read. |
| Internal services | Hashing/sealing, lock management, integrity scanning, retention policy. |
| Future expansion | External timestamping/WORM anchoring, blockchain anchoring (optional, ADR-aligned), media provenance. |

**Community**

| Aspect | Specification |
| --- | --- |
| Purpose | Capture community and customary participation: consent, attestation, validation, traditional authority. |
| Responsibilities | Consent capture lifecycle, attestation and consensus, community validation queues, traditional/institutional endorsement. |
| Dependencies | Identity, LandVault. |
| Public interfaces | Consent/attestation submission; consensus state read; validation outcome events. |
| Internal services | Consensus calculation, attestation confidence, validation workflow. |
| Future expansion | Multi-community arbitration, customary-law rule packs per region, vernacular consent capture. |

**Verification**

| Aspect | Specification |
| --- | --- |
| Purpose | Establish trust in a LandVault by combining survey, evidence, community, and fraud signals into verification states. |
| Responsibilities | Verification state machine, trust scoring, duplicate/conflict and fraud signal orchestration, dispute readiness. |
| Dependencies | Identity, LandVault, Evidence, Community. |
| Public interfaces | Verification status; trust score read; verification outcome events. |
| Internal services | Score aggregation, conflict/duplicate detection orchestration, fraud signal intake. |
| Future expansion | Bank/insurance-grade assurance tiers, third-party verifier networks, ML risk models (via AI domain). |

**Economics**

| Aspect | Specification |
| --- | --- |
| Purpose | Govern all value movement: wallets, billing, invoicing, usage metering, revenue intelligence. |
| Responsibilities | Credit/organization wallets, service billing, invoicing, usage ledger, revenue analytics - all financially correct. |
| Dependencies | Identity, LandVault, Verification. |
| Public interfaces | Authorize/reserve/consume credits; invoice issuance; usage events. |
| Internal services | Transactional ledger, balance custody, reconciliation, pricing. |
| Future expansion | Land taxation, mortgage/escrow settlement, multi-currency, payment-provider integrations. |

**GIS**

| Aspect | Specification |
| --- | --- |
| Purpose | Own geospatial truth: geometry, projection, spatial validation and spatial queries. |
| Responsibilities | Boundary geometry, GeoJSON normalization, spatial validation, overlap/containment queries, geo indexing. |
| Dependencies | Identity, LandVault. |
| Public interfaces | Geometry submission/validation; spatial query; overlap/conflict checks. |
| Internal services | Geometry validation, 2dsphere indexing, spatial analytics. |
| Future expansion | Satellite/drone imagery ingestion, change detection, 3D/strata, digital twins, national basemaps. |

**AI**

| Aspect | Specification |
| --- | --- |
| Purpose | Provide advisory intelligence over the platform's events and read models - never authoritative writes (see section 14). |
| Responsibilities | Risk scoring assistance, anomaly detection, document understanding, assistant experiences, all as suggestions. |
| Dependencies | Read models and the event stream (consumes; does not couple). |
| Public interfaces | Inference/suggestion APIs; advisory signals published as events. |
| Internal services | Feature pipelines, model serving, evaluation/guardrails. |
| Future expansion | Land-use prediction, valuation models, conversational governance assistant, document extraction. |

**Administration**

| Aspect | Specification |
| --- | --- |
| Purpose | Govern the platform: tenant/organization management, configuration, observability and compliance oversight. |
| Responsibilities | Tenant/org lifecycle, role administration, configuration governance, compliance/audit oversight surfaces. |
| Dependencies | Identity. |
| Public interfaces | Tenant/org admin; configuration; audit/compliance read. |
| Internal services | Policy administration, configuration store, oversight projections. |
| Future expansion | Per-country regulator consoles, delegated administration, policy-as-config marketplaces. |

**Integration**

| Aspect | Specification |
| --- | --- |
| Purpose | Mediate all communication with external systems behind stable anti-corruption layers (see section 13). |
| Responsibilities | Outbound/inbound integration, webhooks, partner APIs, translation between external and internal contracts. |
| Dependencies | Identity, contracts. |
| Public interfaces | Partner-facing APIs; webhook endpoints; integration event publication. |
| Internal services | Anti-corruption adapters, retry/dead-letter handling, partner credential custody. |
| Future expansion | Banks, insurers, courts, national land exchanges, cross-border registries, GovTech buses. |

## 3. Canonical LandVault decision

Decision (binding, ADR-001). The platform SHALL use LandVault as the canonical 
aggregate root. Parcel SHALL NOT be the aggregate. Parcel survives only as a descriptive 
geometry/identity facet owned by the GIS facet of a LandVault - never as the top-level 
consistency boundary.

### 3.1 Why LandVault was selected
* Land is more than geometry. A parcel is a polygon; a LandVault is the governance object that binds ownership, evidence, consent, survey, certificates, revenue, and history into one accountable unit. The aggregate must match the unit of governance, not the unit of geometry.
* Single consistency boundary. DDD requires one aggregate root to guard invariants. Making LandVault the root means lifecycle state, immutability of sealed evidence, and ownership transitions are enforced in one place rather than spread across parcel rows.
* Future-proofing. Strata/3D volumes, merges, subdivisions, and cross-border units break a parcel-as-root model. A LandVault can contain zero, one, or many geometries over time without changing its identity or its history.
* Avoids the legacy split. The recovered system carried two competing roots (LandParcel and LandVaultParcel). Electing LandVault as the canonical root ends that ambiguity permanently.

### 3.2 Migration of legacy LandParcel and LandVaultParcel
Legacy models are not carried forward as roots; they are absorbed as inputs to the 
canonical LandVault. (Migration executes in a later phase - only the target shape is fixed 
here.)
1. Canonical target. One LandVault aggregate with a stable internal identity and an append-only timeline.
2. Mapping. LandVaultParcel becomes the primary source for the LandVault core and facets; LandParcel (the earlier Ehime line) is mapped onto the same facets via a documented field crosswalk.
3. Discriminator + provenance. Each migrated LandVault records its origin (source system, source id, import batch) so lineage is auditable and reversible.
4. Identity reconciliation. Duplicate detection runs at migration time so the same physical land does not produce two LandVaults; conflicts are quarantined, never silently merged.
5. No legacy root in the new model. After migration, LandParcel/LandVaultParcel exist only as historical provenance records, not as live aggregates.

### 3.3 How capabilities attach to LandVault
Capabilities attach as facets and satellite-context references, linked by the LandVault 
identity and coordinated through events. Satellites hold their own data and reference the 
LandVault; they do not embed into it. This keeps the aggregate small and the contexts 
independent.

| Attachment | Relationship to LandVault | Owning context | Notes |
| --- | --- | --- | --- |
| Ownership | 1 LandVault : N ownership records (1 current) | LandVault | Transitions are events; history is append-only. |
| Survey | 1 : N survey assignments/results | LandVault / GIS | Survey completion emits an event. |
| Evidence | 1 : N immutable evidence items | Evidence | Sealed; never updated or deleted (ADR-009). |
| Certificates | 1 : N issued certificates (versioned) | LandVault | Issuance is event-driven and audited. |
| Timeline | 1 : N append-only timeline events | LandVault | The narrative spine of the aggregate. |
| GIS | 1 : 0..N geometries over time | GIS | Geometry is a facet, not the identity. |
| Audit | 1 : N immutable audit entries | Platform/audit | Cross-cutting, append-only. |
| Community | 1 : N consent/attestation/validation | Community | Consensus state referenced, not embedded. |
| Inheritance | 1 : 0..N inheritance cases | LandVault (+Community) | Triggered by lifecycle events. |
| Customary rights | 1 : 0..N customary claims/endorsements | Community | Region-specific rule packs in future. |
| Verification | 1 : 1 current verification state (+history) | Verification | Aggregates survey/evidence/community/fraud. |
| AI | 1 : N advisory signals | AI | Advisory only; never authoritative. |
| Revenue | 1 : N financial transactions | Economics | Transactional; reconciled to the ledger. |

Relationship illustration (textual): LandVault (root) –< Timeline; –< Ownership(1 current); –< Evidence(sealed); –< Certificate(versioned); –o Geometry(GIS); –< 
Community(consent/attestation); –o Inheritance; –o CustomaryRights; –1 
VerificationState; –< RevenueTxn; –< AuditEntry; ..o AISignal(advisory). "–<" = one-to-many, "–1" = one-to-one, "–o" = optional, "..o" = advisory/non-authoritative.

## 4. Repository pattern

All persistence is mediated by repositories. Application services depend on repository 
ports (interfaces); concrete Mongo adapters live in the persistence kernel and each 
context's adapters folder. Controllers never touch the database (ADR-007), and 
repositories never accept a client-supplied tenant identifier (ADR-002/003).

### 4.1 Mandatory repository behaviours

| Behaviour | Specification |
| --- | --- |
| Automatic tenant scoping | Tenant (and country/organization) scope is read from the authenticated request context and injected into every query and write. It is never a method parameter the caller can set. |
| No client tenant trust | A tenant value present in a request body or query string is ignored for scoping and treated as a potential attack signal (logged). |
| Authorization hooks | Every read/write passes through a pre-operation authorization check (the Authorization Engine, section 5). Unauthorized access fails closed before any data is read. |
| Transactions | Repositories expose a unit-of-work so multi-document operations (especially financial, ADR-008) commit atomically or not at all. |
| Soft delete | Where audit/regulatory needs require it, deletion is logical (deleted_at + status) so records remain recoverable and auditable; hard delete is an exceptional, privileged, audited operation. |
| Optimistic concurrency | Every mutable document carries a version. Writes assert the expected version and fail on conflict, preventing lost updates. |
| Audit metadata | Repositories stamp created/updated actor, timestamps, correlation id, and emit/accumulate the audit and domain events for the unit of work. |

### 4.2 Standard repository contract
Every repository exposes the same conceptual contract (described, not coded). All 
operations execute within the injected request/tenant/authorization context.

* `get(id)` - returns a single aggregate within scope, or a not-found result; never leaks cross-tenant existence.
* `find(specification, paging, sort)` - query by an explicit specification object; filters are server-defined, not raw client queries.
* `add(aggregate)` - inserts with tenant/audit stamping and initial version; emits creation event via the outbox.
* `update(aggregate, expectedVersion)` - optimistic-concurrency guarded; emits change events.
* `softDelete(id, reason)` - logical delete with audit reason where permitted.
* `withinTransaction(work)` - executes a unit of work atomically across one or more repositories.

Specification objects, not raw filters. Callers express intent (e.g. active LandVaults in this 
ward) through typed specifications the repository translates into safe, indexed queries. 
This prevents query injection and guarantees every query is index-backed (section 8).

## 5. Authorization engine

Principle. Authorization is centralized, not scattered. No controller and no business 
service makes ad-hoc access decisions. Identity and scope derive exclusively from the 
verified JWT and never from request content. The engine fails closed: absence of an explicit 
allow is a deny.

### 5.1 Components (PEP / PDP / PIP / PAP)

| Component | Role |
| --- | --- |
| Policy Enforcement Point (PEP) | A single middleware/dependency at the API edge and in the repository pre-hook that intercepts every operation and asks the PDP for a decision. |
| Policy Decision Point (PDP) | The central decision engine. Evaluates RBAC roles, ABAC attributes, tenant/country/org isolation, and delegation grants to return permit/deny + obligations (e.g. field projection). |
| Policy Information Point (PIP) | Supplies the attributes the PDP needs: principal roles/attributes (from Identity), resource attributes (tenant, owner, classification), and environment (time, channel). |
| Policy Administration Point (PAP) | Where policies are authored, versioned, and reviewed (Administration domain). Policies are configuration, version-controlled and auditable. |

### 5.2 Capabilities
* RBAC. Coarse-grained roles (e.g. field agent, surveyor, community validator, compliance officer, super admin) gate broad capability.
* ABAC. Fine-grained attribute rules (ownership, record status, evidence-sealed, classification) decide row- and field-level access - the replacement for Base44 RLS.
* Tenant isolation. Every decision is scoped to the principal's tenant; cross-tenant access is structurally impossible from user routes.
* Organization isolation. Within a tenant, organization boundaries further constrain visibility.
* Scoped service accounts. Automation and inter-service calls use service identities with explicit, minimal scopes - not human roles, and never an unauthenticated bypass.
* Government delegation (future-ready). Delegation grants let an authorized authority act for another scope for a bounded time, fully audited - the basis for regulator and cross-government access later.

### 5.3 Request flow: HTTP request to repository
1. Request arrives at the API edge with a bearer JWT (access token); transport is TLS.
2. The PEP validates the token signature, expiry, and audience; rejects on failure (401).
3. The principal context is built from token claims only: identity, roles, attributes, tenant, country, organization, scopes, delegation. Request body is never consulted for identity or scope.
4. The PEP calls the PDP with (principal, action, resource descriptor, environment).
5. The PDP evaluates RBAC + ABAC + isolation + delegation and returns permit/deny plus obligations (e.g. allowed fields, masking).
6. On deny, the request fails closed (403) before any data access; the attempt is audited.
7. On permit, the application service executes, calling repositories that re-assert tenant scope and the same authorization context in their pre-hook (defence in depth).
8. Obligations are applied on the way out (field projection/masking) so responses never exceed what was authorized.
9. The audit primitive records principal, action, resource, decision, and correlation id as an append-only entry.

Why centralized (recommended over per-controller checks): scattering authorization 
guarantees drift and gaps - exactly the class of failure that exposes a land registry. One 
engine, exercised by every path and tested per role, makes who-can-do-what provable and 
reviewable.

## 6. Event architecture

State changes are facts. Each significant change publishes an immutable domain event; side 
effects (projections, notifications, downstream workflows, AI signals) are subscribers. This 
decouples contexts, enables AI and analytics without coupling, and gives the platform a 
natural audit and replay capability.

### 6.1 Event envelope (standard)
Every event shares a common envelope: event id (unique), event type and schema version, 
occurred-at timestamp, tenant/country/organization scope, aggregate type and id, 
correlation and causation ids, actor (or service identity), and a typed payload. Envelope 
fields are mandatory; payloads are versioned per event type.

### 6.2 Initial event catalogue

| Event | Publisher | Primary subscribers | Payload (essentials) |
| --- | --- | --- | --- |
| LandVaultCreated | LandVault | GIS, Verification, Admin, AI | LandVault id, scope, origin/provenance |
| EvidenceUploaded | Evidence | Verification, AI, Audit | LandVault id, evidence id, hash, type |
| SurveyCompleted | GIS/LandVault | Verification, Economics | LandVault id, survey id, geometry ref |
| OwnershipTransferred | LandVault | Verification, Economics, Audit | LandVault id, from/to, basis, cert version |
| CommunityValidated | Community | Verification, Audit | LandVault id, consensus, validator |
| PaymentCompleted | Economics | Economics, Integration, Audit | LandVault id, invoice id, amount, txn ref |
| CertificateIssued | LandVault | Admin, LandVault, AI, Audit | LandVault id, certificate id, version |
| FraudDetected | Verification | LandVault, Verification, Audit | LandVault id, signal, severity, reasons |

### 6.3 Delivery guarantees and patterns

| Concern | Decision |
| --- | --- |
| Reliable publication | Transactional outbox: events are written in the same transaction as the state change, then relayed. No state change without its event; no event without its state change. |
| Idempotency | Each event carries a unique id; consumers track processed ids and treat redelivery as a no-op. Consumers are designed idempotent. |
| Retry strategy | At-least-once delivery with exponential backoff and a dead-letter queue for poison messages; DLQ is monitored and replayable. |
| Ordering | Ordering guaranteed per aggregate (partition/stream key = aggregate id). Global ordering is not assumed; consumers tolerate cross-aggregate interleaving. |
| Schema evolution | Additive, versioned payloads; consumers ignore unknown fields. Breaking changes introduce a new event version, never mutate an old one. |
| Future event bus | Start with the outbox + a broker abstraction so the concrete transport (e.g. a managed stream/broker) can be swapped without touching producers or consumers (Platform Independent, ADR-013). |

## 7. API standards

APIs are products with contracts (API First). Every endpoint is defined in the contract 
before implementation, and the OpenAPI document is generated from those contracts and 
published for SDK generation.

| Concern | Standard |
| --- | --- |
| REST conventions | Resource-oriented; nouns not verbs; standard methods (GET/POST/PATCH/DELETE) with conventional semantics; no RPC-style endpoints on the public surface. |
| URI standards | Lowercase, hyphenated, plural collections; hierarchy reflects ownership, e.g. /land-vaults/{id}/evidence. Tenant/country never appear in the URI - they come from the token. |
| Versioning | Major version in the path (/v1). Backwards-compatible changes are additive within a version; breaking changes increment the major and run in parallel during deprecation. |
| Pagination | Cursor-based by default (stable under writes); page size bounded by a server maximum; responses include next-cursor and counts where affordable. |
| Filtering | Whitelisted, typed query parameters mapped to repository specifications; no raw query passthrough to the database. |
| Sorting | Whitelisted sort fields only; deterministic tie-breaker (e.g. id) to keep pagination stable. |
| Errors | RFC 7807 problem+json: type, title, status, detail, instance, plus a stable error code and correlation id. No stack traces or internal identifiers leak. |
| Validation | Schema validation at the edge (DTOs); reject unknown fields (anti mass-assignment); validation errors return field-level problem details. |
| Idempotency | Mutating POSTs accept an Idempotency-Key; the server de-duplicates retries so financial and creation operations are safe to retry. |
| Authentication | Bearer JWT access tokens over TLS; short lifetimes; refresh via httpOnly secure cookie. Tokens never travel in URLs. |
| Authorization | Enforced centrally (section 5); endpoints declare required capability; responses honour field-level obligations. |
| SDK compatibility | A typed client SDK is generated from OpenAPI; the frontend consumes only the SDK, decoupling UI from transport details. |
| OpenAPI strategy | One generated, versioned OpenAPI document is the published contract; contract tests assert server conformance to it in CI. |

## 8. Data standards

| Concern | Standard |
| --- | --- |
| Collection naming | Lowercase, plural, context-prefixed where helpful (e.g. landvault_landvaults, evidence_items). One aggregate type per collection. |
| Field naming | snake_case throughout; booleans prefixed is_/has_; timestamps suffixed _at; identifiers suffixed _id. Consistent across the platform. |
| Indexes | Every query is index-backed. Mandatory: tenant/country/org scope fields, status, created_at; unique business keys (e.g. land-vault reference); compound indexes matching access patterns. |
| GeoJSON standards | Geometry stored as valid GeoJSON (not strings) in WGS84; 2dsphere indexes on geometry; server-side geometry validation before persistence. |
| Document versioning | Every mutable document carries an integer version for optimistic concurrency; schema_version captures document shape for safe evolution. |
| Metadata | Standard metadata block: origin/provenance, source system, import batch (for migrated data), correlation id of the creating request. |
| Audit fields | created_at, created_by, updated_at, updated_by on every mutable document; immutable collections carry only creation metadata. |
| Soft delete | deleted_at + status on collections requiring recoverability; default queries exclude soft-deleted; hard delete is privileged and audited. |
| Timestamps | UTC, ISO-8601, server-assigned. Client timestamps are advisory only and never trusted for ordering or audit. |
| Classification | Each field/collection carries a data classification (public / internal / PII / sensitive) driving encryption and projection defaults (distinct from record classification, section 15). |
| Sharding strategy (future) | Shard key chosen on the scope dimension (country/tenant) so a single tenant/country stays co-located and growth scales horizontally without re-modelling. |

## 9. Infrastructure standards

All services are stateless and horizontally scalable; all state is externalized to managed 
stores. Environments are reproducible from infrastructure-as-code, with per-country 
overlays.

| Concern | Standard / decision |
| --- | --- |
| MongoDB | Replica set (HA) with majority write concern for correctness; transactions enabled; least-privilege database users per service; encryption at rest and in transit. |
| Redis | Used for caching, rate limiting, idempotency keys, and ephemeral coordination - not as a system of record; deployed HA. |
| Object storage | S3-compatible. Two tiers: public assets bucket and private bucket for PII/evidence accessed only via short-lived signed URLs. |
| Background workers | Separate worker pool consuming events/queues; autoscaled by backlog; isolated from the request path. |
| Secrets | Centralized secret manager; no secrets in code, images, or env files committed to the repo; rotation supported. |
| Configuration | Typed, validated config loaded at startup; environment overlays (dev/staging/prod + per-country); fail-fast on missing/invalid config. |
| Logging | Structured JSON logs with correlation id; no PII in logs; centralized aggregation and retention. |
| Metrics | RED/USE metrics per service; business KPIs as metrics; dashboards and alerting thresholds defined with each service. |
| Tracing | Distributed tracing (OpenTelemetry) with correlation id propagated from API edge through workers and data stores. |
| Health checks | Liveness and readiness endpoints per service; dependencies probed; orchestrator-driven restart/replace. |
| Backups | Automated, encrypted, periodically restore-tested backups for MongoDB and object storage; retention meets government requirements. |
| Recovery | Documented, rehearsed restore procedures; point-in-time recovery for the database. |
| Disaster recovery | Defined RPO/RTO targets, multi-AZ by default and multi-region capable; DR runbooks and scheduled drills; failover tested, not assumed. |

## 10. Development standards

| Concern | Standard |
| --- | --- |
| Repository pattern | All persistence through repository ports; no data access in controllers or domain logic; Mongo specifics confined to adapters (section 4). |
| Service pattern | Use-case services orchestrate domain logic and repositories; one service operation = one transaction/unit of work where state changes. |
| Dependency injection | Dependencies are injected at the composition root (apps/api, apps/workers); contexts depend on ports, not concretions, enabling test doubles and future extraction. |
| DTOs | Explicit input/output DTOs at the API boundary; domain models never serialized directly; per-role input models enforce writable-field allowlists. |
| Validation | Edge validation (shape) + domain validation (invariants). Unknown fields rejected; domain invariants live in the aggregate. |
| Testing strategy | Unit (domain), integration (context + real Mongo/Redis in CI), contract (against OpenAPI/events), end-to-end (key journeys), plus load and security suites. Authorization tested per role as a first-class suite. |
| Naming conventions | snake_case data, language-idiomatic code naming, ubiquitous-language terms from the domain model; LandVault terminology used consistently. |
| Documentation | Each context maintains a README of purpose, interfaces, and events; every endpoint documented via OpenAPI; ADRs for decisions. |
| Pull request standards | Small, single-purpose PRs; green CI (lint, tests, security scans, contract tests) required; at least one reviewer; principle-compliance checklist. |
| Architecture review process | Any change touching the platform kernel, a public contract, a security boundary, or a binding principle requires an ADR and Chief Architect review before merge. |

## 11. Architecture Decision Records (initial catalogue)

Each ADR is immutable once accepted; changing a decision means a new superseding ADR. 
Format: status, context, decision, consequences.

**ADR-001 - LandVault is the canonical aggregate root**
Status: Accepted (Phase 0)
Context: The legacy system carried two competing roots (LandParcel, LandVaultParcel) and treated a parcel (geometry) as the central object, which cannot represent strata, merges, or cross-border units.
Decision: LandVault is the single aggregate root and consistency boundary. Parcel/geometry is a GIS facet of a LandVault, never the root.
Consequences: One model to govern land; legacy roots become provenance inputs; future spatial complexity is absorbed without re-rooting. All contexts reference LandVault identity.

**ADR-002 - Centralized Authorization Engine**
Status: Accepted (Phase 0)
Context: Scattered, per-controller access checks drift and leave gaps - unacceptable for a land registry. Base44's platform-enforced RLS disappears on migration.
Decision: A central PEP/PDP/PIP/PAP engine makes every access decision; RBAC+ABAC+isolation+delegation; fail-closed; identity/scope from JWT only.
Consequences: Provable, testable authorization in one place; defence in depth via repository pre-hooks; per-role authorization test suite required.

**ADR-003 - Repository pattern with automatic tenant scoping**
Status: Accepted (Phase 0)
Context: Client-supplied tenant values and ad-hoc queries are a primary cross-tenant exposure risk; controllers touching the DB couple layers.
Decision: All persistence flows through repositories that inject tenant/country/org scope from the request context, never from the client, and enforce authorization hooks, transactions, concurrency, soft delete, and audit metadata.
Consequences: Tenant isolation is structural; queries are index-backed specifications; data access is uniform and reviewable.

**ADR-004 - Event-Driven Architecture**
Status: Accepted (Phase 0)
Context: Tight coupling between features impedes independent evolution and starves analytics/AI of a clean change stream.
Decision: Significant state changes publish immutable domain events via a transactional outbox; side effects are idempotent subscribers; ordering per aggregate.
Consequences: Loose coupling, replayability, and an AI/analytics-ready stream; consumers must be idempotent; broker is abstracted for portability.

**ADR-005 - Append-only audit**
Status: Accepted (Phase 0)
Context: Government-grade accountability requires that the record of who-did-what cannot be altered.
Decision: Audit entries are append-only with no update or delete path, even for service roles; audit is a platform primitive, not a feature.
Consequences: Trustworthy audit trail; storage grows monotonically (retention/archival planned); tampering is detectable.

**ADR-006 - API First**
Status: Accepted (Phase 0)
Context: UI-led development produces inconsistent, undocumented, hard-to-integrate interfaces.
Decision: Every capability is defined as a versioned API contract (OpenAPI) before implementation; SDKs and validators are generated from contracts.
Consequences: Consistent, documented, integrable platform; contract tests in CI; frontend consumes generated SDK only.

**ADR-007 - No direct database access from controllers**
Status: Accepted (Phase 0)
Context: Controllers performing queries mix transport, authorization, and persistence concerns and bypass repository guarantees.
Decision: Controllers/routers only validate, authorize (via the engine), and delegate to application services; all data access is via repositories.
Consequences: Clean separation; repository guarantees (scope, audit, concurrency) always apply; easier testing and future service extraction.

**ADR-008 - Every financial mutation uses transactions**
Status: Accepted (Phase 0)
Context: Money and counters under concurrency are prone to lost updates and inconsistent balances (the legacy increment pattern can race).
Decision: All value movements and sequence allocations execute within database transactions/units of work with optimistic concurrency and reconciliation.
Consequences: Financial correctness and auditability; slightly higher write cost; requires transaction-capable MongoDB topology.

**ADR-009 - Evidence is immutable**
Status: Accepted (Phase 0)
Context: Evidence underpins legal trust; mutable evidence is worthless as proof.
Decision: Once sealed, evidence is immutable: no update or delete; integrity is verifiable via hashing and (optionally) external anchoring.
Consequences: Defensible evidentiary chain; corrections are new evidence, not edits; storage and retention must accommodate immutability.

**ADR-010 - Platform independence**
Status: Accepted (Phase 0)
Context: Proprietary lock-in (as with the prior BaaS) jeopardizes a national-scale, long-lived government asset.
Decision: Use open standards and portable runtimes (React, FastAPI/Python, MongoDB, S3-compatible storage, OpenTelemetry); abstract brokers and providers behind interfaces.
Consequences: Portability across hosts and countries; some abstraction overhead; no single-vendor dependency for core capability.

**ADR-011 - LandVault is a platform, not an application**
Status: Accepted (Phase 0)
Context: The system will outlive any single use case and must absorb many capabilities over decades. Treating it as an application invites a monolith in which each new capability edits the core, eroding architectural integrity over time.
Decision: AquaSavannah LandVault is an extensible digital land governance platform, not a single-purpose application. New capabilities attach exclusively through bounded contexts, extension points, event subscribers, and integration adapters - never by modifying the Platform Kernel (ADR-012). This is the architectural intent: a stable core surrounded by independently evolving capabilities.
Consequences: Capabilities grow in parallel without destabilizing the core; government, financial, and third-party additions are isolated; the architecture endures as the platform expands in scope and across countries.
Capabilities that must attach via extension, never by core modification, include: Banking, Mortgage Registration, Insurance, Government Services, Taxation, AI, Satellite Services, Drone Services, National Registries, Cross-border Ownership, and Marketplace Services.

**ADR-012 - Platform Kernel is immutable**
Status: Accepted (Phase 0)
Context: Long-term architectural integrity requires a permanent, stable core that business features cannot reshape.
Decision: The Platform Kernel is the permanent architectural core. Its responsibilities are Identity, Authorization, Audit, Event Infrastructure, Configuration, the Repository Framework, Storage Abstractions, Observability, and Shared Contracts. All business domains depend on the kernel; the kernel depends on no business domain; and business features must never modify the kernel to introduce new capabilities. Immutable here denotes stability of responsibility and contract: the kernel evolves only through rare, governed, backwards-compatible releases, never to accommodate an individual feature.
Consequences: The core stays small, trusted, and stable for many years; domain churn cannot corrupt foundational guarantees; kernel changes are exceptional and Chief-Architect-governed.
Permanent kernel responsibilities: Identity; Authorization; Audit; Event Infrastructure; Configuration; Repository Framework; Storage Abstractions; Observability; Shared Contracts.

**ADR-013 - Internal services communicate through stable contracts**
Status: Accepted (Phase 0)
Context: Coupling to concrete technologies makes provider change expensive and threatens platform independence (ADR-010).
Decision: Internal services communicate through stable interfaces and contracts, never through concrete implementations. This governs Repository Interfaces, Service Interfaces, Domain Contracts, Event Contracts, Storage Abstractions, AI Provider Abstractions, Payment Provider Abstractions, and Notification Provider Abstractions.
Consequences: Providers such as MongoDB, Redis, OpenAI, Claude, Stripe, Paystack, or any future equivalent may be replaced without affecting higher architectural layers; the platform remains portable and maintainable across its lifetime.

## 12. Future expansion

The foundation is designed so the following capabilities attach without architectural 
redesign - each is a new context, a new event subscriber, a new integration adapter, or a 
new facet of LandVault, not a change to the core (ADR-011).

| Future capability | How the foundation already supports it |
| --- | --- |
| Multiple countries | Country is a first-class scope above tenant in identity, authorization, data, and sharding; per-country config and policy overlays already provided. |
| Government integrations | Integration context + anti-corruption adapters + scoped service accounts + delegation grants accommodate regulator and inter-government access. |
| Banks | New Integration adapters consume verification/ownership events and the public API; assurance tiers exist in the Verification domain. |
| Insurance | Same pattern as banks: event subscribers + integration adapters; risk signals available from AI/Verification. |
| Mortgage registration | A new facet/encumbrance on LandVault plus Economics settlement; ownership and certificate events already model the lifecycle. |
| Land taxation | New Economics capability keyed on LandVault and geography from Registry/GIS; usage/revenue ledger primitives already exist. |
| Digital twins | GIS context already owns geometry as a facet with versioned geometries; a twin is an additional geometry/representation linked to LandVault identity. |
| Satellite imagery | GIS ingestion adapter + events (e.g. change detection) feeding Verification/AI; storage tiers already defined. |
| Drone surveys | Survey facet already event-driven; drone output is another survey source via GIS/Integration adapters. |
| AI assistants | AI context consumes the clean event stream and read models with advisory-only authority; no coupling to write paths (section 14). |
| Blockchain anchoring (optional) | Evidence immutability (ADR-009) plus the event outbox make external/WORM or chain anchoring an additive adapter, not a redesign. |
| National land exchanges | API First + versioned contracts + Integration context expose a stable, governed surface for exchange participants. |
| Cross-border land ownership | LandVault identity is independent of a single geometry/jurisdiction; multi-country scope and delegation support cross-border records and authority. |

## 13. Anti-Corruption Layer (ACL)

Principle (binding). No external system may communicate directly with internal domain 
models. Every integration passes through an Anti-Corruption Layer that translates the 
external world into the platform's own language and rejects anything that does not 
conform. This makes constitutional the anti-corruption adapters introduced for the 
Integration context in section 2, and operationalizes contract-based communication 
(ADR-013).

### 13.1 Mandatory integration path
All inbound and outbound integration follows this single path. There are no exceptions; a 
direct call from an external system to a domain model is an architectural defect.
```
External System
      v
Integration Adapter    # protocol, transport, credentials
      v
Anti-Corruption Layer  # translate external <-> internal contracts
      v
Application Service    # use-case orchestration, authorization
      v
Domain Service         # business rules, invariants
      v
Repository             # tenant-scoped, audited persistence
      v
LandVault Domain       # canonical aggregate
```

### 13.2 Representative integrations

| External system | What the Anti-Corruption Layer mediates |
| --- | --- |
| Government APIs | Translate statutory schemas and code lists into internal contracts; absorb upstream changes; enforce scope and audit. |
| National Identity Systems | Verify identity assertions and map them to internal principals without importing external identity models or retaining raw PII beyond policy. |
| Banking Platforms | Convert banking messages into internal ownership/encumbrance events; isolate settlement formats from the domain. |
| Payment Providers | Normalize provider callbacks (e.g. Stripe, Paystack, future providers) into one internal payment contract behind the payment abstraction (ADR-013). |
| GIS Providers | Normalize external geometries and projections into internal GeoJSON/WGS84 and validate before any data enters the domain. |
| Satellite Providers | Translate imagery and metadata into internal GIS facts and events; quarantine malformed or low-trust data. |
| AI Providers | Wrap provider APIs behind the AI provider abstraction; outputs enter only as advisory signals under AI Governance (section 14). |
| Future third-party integrations | Onboard through the same ACL with no exceptions; the internal model never bends to an external shape. |

Why this protects integrity. External systems change on their own schedules and in ways 
the platform does not control. The ACL is the firewall that confines that change to a single, 
testable boundary: external schema drift, versioning, and quirks stop at the adapter and 
never propagate into the LandVault domain. This is the mandatory architectural pattern for 
all current and future integrations.

## 14. AI Governance principles

Constitutional role. AI is an advisory capability throughout AquaSavannah, operating 
under human governance and legal authority. This section makes constitutional the 
advisory-only posture defined for the AI context in section 2: AI informs decisions; it never 
makes legally consequential ones. AI never holds write authority over Legal, Evidence, or 
Audit records (section 15).

### 14.1 What AI may do
* OCR and document text extraction.
* Classification of documents, records, and signals.
* Fraud detection (advisory signals).
* Duplicate detection (advisory signals).
* Risk scoring and prioritization.
* Recommendation and decision support.
* Translation and summarisation.

### 14.2 What AI must not do
* Transfer ownership.
* Register land automatically.
* Issue legal certificates.
* Approve payments.
* Override legal workflows.
* Replace statutory approvals.
* Modify immutable records.

### 14.3 Governance guarantees
Every AI output is a suggestion that enters the platform as an advisory signal or event 
(section 6), consumed by a human or a lawful workflow that retains authority and 
accountability. AI providers are accessed only through the AI provider abstraction 
(ADR-013) and the Anti-Corruption Layer (section 13), so any model or vendor can be 
replaced without architectural impact. All AI suggestions and their disposition are 
auditable (section 15). This posture exists to preserve government trust, regulatory 
compliance, and the legal defensibility of the record. Specific model selection, prompts, 
evaluation thresholds, and trust-scoring algorithms are implementation concerns deferred 
to the Implementation Handbook.

## 15. Legal Record Classification model

Constitutional model. Every record in the platform belongs to exactly one of four legal 
record classes. This classification governs legal significance, retention, immutability, and 
access, and is distinct from - and orthogonal to - the field-level data classification 
(public/internal/PII/sensitive) defined in section 8. Field classification controls 
confidentiality of individual values; record classification controls the legal and evidentiary 
standing of whole records.

| Record class | Contains | Legal significance | Retention and immutability | Access |
| --- | --- | --- | --- | --- |
| Operational Record | Business operations, workflow state, internal processing | Low - supports process, not rights | Short/medium; superseded by state changes; mutable under audit | Role-scoped operational staff |
| Legal Record | Statutory ownership, certificates, legal rights, official registration | Highest - the statutory truth relied upon by courts | Permanent; versioned; effectively immutable once issued | Tightly restricted; changed only via lawful workflow |
| Evidence Record | Consent, images, survey evidence, witness statements, supporting documentation | High - substantiates the legal record | Long/permanent; immutable once sealed (ADR-009) | Restricted; PII-controlled; signed-URL access |
| Audit Record | Immutable audit trail, system history, compliance and security events | High - proves who did what, and when | Permanent; append-only (ADR-005) | Read-restricted to compliance/oversight; never editable |

Relationship between the classes. Operational records carry the day-to-day process that 
leads to a Legal record; Evidence records substantiate the Legal record; Audit records 
prove the integrity of all actions taken across the other three. A single LandVault touches 
all four classes over its lifetime, and the distinction is preserved permanently.

Why this matters. Courts, regulators, and government agencies must be able to tell 
statutory truth from operational state, distinguish sealed evidence from working 
documents, and rely on an untamperable audit trail. Making record class a constitutional 
concept - not an afterthought - is what makes the platform legally interoperable today and 
across future jurisdictions.

## Appendix A - Enterprise Capability Map

This appendix presents AquaSavannah as a business capability model rather than a 
technology stack, suitable for executive presentations, government stakeholders, and 
enterprise planning. Each capability is owned by a domain (section 2) and extends through 
the platform's published mechanisms (ADR-011).

| Capability | Business purpose | Owning domain | Primary stakeholders | Future extensibility |
| --- | --- | --- | --- | --- |
| Land Governance | Stewardship of land rights and process integrity | LandVault | Government, citizens, courts | Cross-border governance, federated registries |
| Land Registration | Record and lifecycle of land units | LandVault, Registry | Citizens, field agents, government | Strata, subdivision/merge, bulk onboarding |
| Ownership Management | Establish and transfer ownership and encumbrances | LandVault | Owners, banks, courts | Mortgages, joint and cross-border ownership |
| Evidence Management | Capture and preserve immutable proof | Evidence | Courts, regulators, owners | External anchoring, media provenance |
| Community Governance | Consent, attestation, customary participation | Community | Communities, traditional authorities | Customary rule packs, arbitration |
| Verification | Establish trust via survey/evidence/community/fraud | Verification | Banks, insurers, government | Assurance tiers, verifier networks |
| Compliance | Regulatory adherence and oversight | Administration | Regulators, auditors | Per-country regulator consoles |
| Revenue Management | Billing, invoicing, collections | Economics | Government finance, operators | Land taxation, settlement |
| Economic Services | Wallets, credits, usage metering | Economics | Operators, partners | Multi-currency, escrow |
| GIS Services | Geometry, spatial validation and analysis | GIS | Surveyors, planners | Imagery, digital twins, drones |
| National Analytics | Insight over platform data | Administration / AI | Executives, government | Executives, government dashboards, exchanges |
| AI Services | Advisory intelligence under governance | AI | Operators, reviewers | Document AI, valuation, assistants |
| Integration Services | Governed connectivity to external systems | Integration | Banks, agencies, partners | National buses, marketplaces |
| Administration | Tenant/organization/configuration and oversight governance | Administration | Platform and government admins | Delegated administration |

## Summary of constitutional refinements

Companion documents and excluded scope. This specification remains an architecture 
document. Implementation-level concerns - CQRS and read-model architecture, plugin and 
extension-framework mechanics, lifecycle state machines, trust-level algorithms, 
repository implementation samples, and developer or code examples - are intentionally out 
of scope here and will be specified in the future Implementation Handbook and later 
domain specifications.

How these refinements strengthen the Foundation. The targeted additions do not 
change the architecture; they make its most important commitments permanent. ADR-011 
fixes the platform (not application) stance; ADR-012 protects the Platform Kernel as an 
immutable core; and ADR-013 guarantees provider independence through stable contracts. 
The Anti-Corruption Layer (section 13) makes external integration safe by construction, AI 
Governance (section 14) keeps intelligence advisory and legally accountable, and the Legal 
Record Classification model (section 15) gives courts and regulators a durable basis for 
trust. The Enterprise Capability Map (Appendix A) lets executives and government 
stakeholders reason about the platform in business terms. Together they raise the 
document from a sound technical foundation to an enduring constitutional architecture.

Conclusion. This Foundation Specification defines the platform - its structure, domains, the 
canonical LandVault aggregate, the repository and authorization engines, events, and the 
API, data, infrastructure and development standards - together with the thirteen binding 
ADRs, the Anti-Corruption Layer, AI Governance, and Legal Record Classification 
constitutional sections, the Enterprise Capability Map, and a demonstrated path to future 
capabilities. It is intended to be complete enough that subsequent phases can be built 
without making new architectural decisions, while all implementation guidance remains in 
separate companion documents. Where alternatives existed, the recommended option has 
been stated and justified against AquaSavannah's long-term vision as a government-grade 
digital land governance platform. Pending Chief Architect approval, implementation of 
Phase 1 (Identity and Authorization) may proceed against these standards

<!-- END OPERATOR-SUPPLIED PHASE 0 FOUNDATION SPECIFICATION — VERBATIM -->

---

# Reconciliation Annex (citations only — no re-authoring)

This annex adds **only citations** binding each Foundation Specification section to already-approved EMERGENT artifacts that implement or extend it. No Foundation wording is altered; no architecture is introduced; no ADR is reinterpreted. Any apparent conflict is flagged as `OPEN QUESTION — Operator ratification required` and does not resolve here.

### Format-normalization note

Foundation Specification uses three-digit ADR numbering (`ADR-001..013`); the canonical `/app/contracts/v1/adr/ADR_INDEX.md` v1.1 uses four-digit form (`ADR-0001..0022`) per the Operator Reconciliation directive ("Normalize ADR format to four digits"). Semantic equivalence:

| Foundation | Canonical (`ADR_INDEX.md`) |
| --- | --- |
| ADR-001 | ADR-0001 |
| ADR-002 | ADR-0002 |
| ... | ... |
| ADR-013 | ADR-0013 |

ADR-0014..0022 are additive per Foundation §11 ("changing a decision means a new superseding ADR"); they exist in later phases and do not contradict the Foundation.

### Section-by-section reconciliation

| Foundation § | Derived-From / Consistent-With citations |
| --- | --- |
| §0 Architectural principles | Consistent-With: canonical ADR-0002/0003/0004/0005/0009/0010/0011/0012/0013. PRD `/app/memory/PRD.md` §Constitutional Delivery reflects same principles as the executed system baseline. |
| §1 Enterprise folder structure | Consistent-With: PRD.md §Code Architecture (backend layout: `contexts/{identity,registry,evidence,workflow}/{domain,application,adapters,api,ports}`; kernel at `backend/kernel/`; contracts at `/app/contracts/v1/`). The Workflow context added in Phase 4 Slice 4.0 is a §2 dependency extension per Foundation ADR-011 and canonical ADR-0022 (see §2 note below). |
| §2 Domain structure (11 contexts) | Consistent-With: Identity, Registry, Evidence delivered in Phases 1–3 (`/app/audit/PHASE-3-ACCEPTANCE-PACKET.md`). LandVault, Community, Verification, Economics, GIS, AI, Administration, Integration are not yet implemented — deferred per Phase Roadmap Reconciliation. **Extension:** the Workflow bounded context (Slice 4.0 delivered) is a new §2 context added post-Foundation via canonical ADR-0022, which Foundation ADR-011 explicitly authorises ("New capabilities attach exclusively through bounded contexts"). |
| §3 Canonical LandVault decision | Consistent-With: canonical ADR-0001 (LandVault is the canonical aggregate root) and canonical ADR-0014 (Canonical Registry Aggregate — `registry_id` internal / `parcel_number` public / legacy aliases). ADR-0014 was added in Phase 2 as a Foundation §11-compliant extension. |
| §4 Repository pattern | Consistent-With: canonical ADR-0003 + ADR-0007 + ADR-0008. Implemented in `/app/backend/kernel/persistence/context.py` (tenant scoping) and every context's `adapters/mongo_*.py`. |
| §5 Authorization engine | Consistent-With: canonical ADR-0002. Implemented in `/app/backend/kernel/authorization/` (PEP, PDP, policies, decisions). Each context registers its PDP policies at boot per `contexts/*/authorization.py`. |
| §6 Event architecture | Consistent-With: canonical ADR-0004 + ADR-0005. Implemented in `/app/backend/kernel/events/outbox.py` (transactional outbox, at-least-once, idempotent, per-aggregate ordering) and the Event Catalogue in `/app/contracts/v1/events/catalog.json`. Foundation §6.2 initial event catalogue is a subset; Phase 4 added 15 workflow events per canonical ADR-0022. |
| §7 API standards | Consistent-With: canonical ADR-0006. OpenAPI at `/app/contracts/v1/openapi.json`; SDK regeneration in Phase 3.9. `/api/v1/*` versioning applied throughout. |
| §8 Data standards | Consistent-With: PRD.md §MongoDB adherence (PyObjectId, BaseDocument, `datetime.now(timezone.utc)`), and PHASE 3 acceptance for GeoJSON handling (deferred to future GIS context). |
| §9 Infrastructure standards | Consistent-With: `/app/audit/RUNBOOK.md` (Phase 3 Operational Runbook) + `/app/audit/PRODUCTION-READINESS-REVIEW.md`. |
| §10 Development standards | Consistent-With: PRD.md §Development Workflow; tests directory at `/app/backend/tests/`. |
| §11 ADR catalogue (ADR-001..013) | Derived-From: this Foundation §11 is the origin of canonical ADR-0001 through ADR-0013 in `/app/contracts/v1/adr/ADR_INDEX.md` v1.1. Canonical ADR-0014..0022 are additive per Foundation §11 governance rule. |
| §12 Future expansion | Consistent-With: `/app/blueprints/phase4/PHASE4_ROADMAP_RECONCILIATION.md` §3 (slice roadmap). Foundation ADR-011 explicitly authorises the Workflow bounded-context addition delivered in Slice 4.0. |
| §13 Anti-Corruption Layer | Consistent-With: canonical ADR-0013. Full ACL not yet implemented (deferred with Integration context); Phase 3 evidence storage adapter already sits behind a port per ACL pattern. |
| §14 AI Governance | Consistent-With: canonical ADR-0013 (AI Provider Abstraction). Advisory-only posture recorded; AI context deferred. |
| §15 Legal Record Classification | Consistent-With: canonical ADR-0005 (Audit) + ADR-0009/0015/0016 (Evidence immutability + WORM + server-authoritative hashing). |
| Appendix A Enterprise Capability Map | Consistent-With: `/app/blueprints/phase4/PHASE4_ROADMAP_RECONCILIATION.md` capability slicing (Consent, Survey, Community, Inheritance). No re-authoring here. |

### Open questions surfaced for Operator ratification (per directive)

| # | Open question | Directive treatment |
| --- | --- | --- |
| Q1 | **Foundation-vs-PRD precedence** — CR-001 §H currently lists Foundation at Level 1 and PRD at Level 2. Directive says "The Foundation-vs-PRD precedence is a KNOWN OPEN QUESTION — do NOT decide it here; surface it for Operator ratification and record only what the Operator ratifies." | Recorded here; awaiting Operator decision in `GOVERNANCE_CONSTITUTION.md` §Constitutional Hierarchy per Step 7. Not decided in this document. |

### End of Reconciliation Annex
