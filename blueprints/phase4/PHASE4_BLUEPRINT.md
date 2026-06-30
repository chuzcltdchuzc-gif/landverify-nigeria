# Phase 4 — Master Implementation Blueprint (`PHASE4_BLUEPRINT.md`)

> **Status:** DRAFT — pending operator approval.
> **Scope:** the implementation blueprint for the Phase 4 Workflow
> bounded context. **Architecture only**. No code is produced.
> **Authority:** ADR-0019 / 0020 / 0021 / 0022 and `PHASE4_SPEC.md`.

This blueprint is the implementation map: how the Phase 4 codebase
will be organised, in what order it will be built, what ports
connect to what adapters, what risks must be mitigated, and how the
work will be accepted. It is **paired** with `PHASE4_SPEC.md` —
read both together.

---

## 1. Directory structure

```
/app/
├── backend/
│   ├── contexts/
│   │   ├── identity/          (Phase 1 — untouched)
│   │   ├── registry/          (Phase 2 — untouched in business code;
│   │   │                       command handlers ADD new commands per
│   │   │                       PHASE4_SPEC §5.5)
│   │   ├── evidence/          (Phase 3 — untouched in business code;
│   │   │                       no schema change, no behavior change)
│   │   └── workflow/          (NEW)
│   │       ├── __init__.py
│   │       ├── domain/
│   │       │   ├── __init__.py
│   │       │   ├── workflow_definition.py
│   │       │   ├── workflow_instance.py
│   │       │   ├── task.py
│   │       │   ├── timer.py
│   │       │   ├── compensation.py
│   │       │   ├── consent/                     (sub-context)
│   │       │   │   ├── consent_request.py
│   │       │   │   ├── consent_capture.py
│   │       │   │   ├── witness_attestation.py
│   │       │   │   └── consent_revocation.py
│   │       │   ├── community/                   (sub-context)
│   │       │   │   ├── community_validation.py
│   │       │   │   ├── compliance_review.py
│   │       │   │   ├── sg_review.py
│   │       │   │   ├── attestation_appeal.py
│   │       │   │   └── consensus.py             (pure scorer)
│   │       │   └── inheritance/                 (sub-context)
│   │       │       ├── inheritance_case.py
│   │       │       ├── beneficiary_claim.py
│   │       │       ├── share_calculation.py    (pure calculators)
│   │       │       ├── subdivision_plan.py
│   │       │       ├── court_order.py
│   │       │       └── inheritance_appeal.py
│   │       ├── application/
│   │       │   ├── engine.py                    (WorkflowEngine — ticks instances)
│   │       │   ├── task_service.py
│   │       │   ├── timer_service.py
│   │       │   ├── consent_service.py
│   │       │   ├── community_validation_service.py
│   │       │   ├── compliance_review_service.py
│   │       │   ├── sg_review_service.py
│   │       │   ├── inheritance_service.py
│   │       │   ├── saga_composer.py             (interprets "spawn next" expressions)
│   │       │   └── projectors/                  (Projection implementations)
│   │       │       ├── workflow_queue_projector.py
│   │       │       ├── consent_projector.py
│   │       │       ├── community_projector.py
│   │       │       └── inheritance_projector.py
│   │       ├── adapters/
│   │       │   ├── mongo_workflow_repository.py
│   │       │   ├── mongo_task_repository.py
│   │       │   ├── mongo_timer_repository.py
│   │       │   ├── mongo_consent_repository.py
│   │       │   ├── mongo_community_repository.py
│   │       │   ├── mongo_inheritance_repository.py
│   │       │   └── definition_loader.py         (loads frozen JSON definitions)
│   │       ├── api/
│   │       │   ├── workflow_router.py
│   │       │   ├── consent_router.py
│   │       │   ├── community_router.py
│   │       │   ├── inheritance_router.py
│   │       │   └── admin_router.py
│   │       └── authorization.py                 (registers Phase 4 policies)
│   ├── kernel/
│   │   └── (no kernel changes — Phase 4 uses existing kernel primitives)
│   └── tests/
│       └── (Phase 4 tests; see §7 — created during implementation, NOT now)
├── contracts/
│   └── v1/
│       └── (Phase 4 contract bump adds new artifact families — see PHASE4_SPEC §10. NOT created during blueprinting.)
├── frontend/
│   ├── src/
│   │   ├── sdk/
│   │   │   ├── workflow.ts                      (NEW — Phase 4 SDK client; created after backend stabilises)
│   │   │   ├── consent.ts
│   │   │   ├── community.ts
│   │   │   └── inheritance.ts
│   │   └── pages/
│   │       └── workflow/                        (NEW Evidence-style workspace; created in Phase 4.9 equivalent)
└── audit/
    └── phase4/                                  (the eventual Phase 4 Acceptance Packet)
```

## 2. Package layout (Python)

| Package | Owns | Pure / IO |
| --- | --- | --- |
| `contexts.workflow.domain.*` | Aggregates, invariants, scorers, state graphs | **pure** — no IO |
| `contexts.workflow.application.*` | Services that orchestrate domain + adapters | mostly pure logic, IO via injected ports |
| `contexts.workflow.adapters.*` | Mongo repositories, definition loader | IO only |
| `contexts.workflow.api.*` | FastAPI routers (thin) | HTTP only |
| `contexts.workflow.authorization` | Policy registration | called once at startup |

Phase 4 reuses every kernel primitive: outbox, audit log, PEP,
projection engine, persistence context, problem-detail errors,
JWT, security headers, rate limiter. **No new kernel module is
needed.**

## 3. Bounded contexts (final placement)

| Context | Owns | Communicates via |
| --- | --- | --- |
| Identity | users, sessions, roles | events (out) |
| Registry | parcels, ownership | commands (in), events (out) |
| Evidence | uploads, seals, anchors, timeline, custody, legal-hold | commands (in), events (out) |
| **Workflow** (new) | workflow definitions, instances, tasks, timers, consent, community validation, inheritance | commands (out to others), events (in from others), events (own) |

Workflow is the **only** context that emits commands TO Registry
and Evidence. Registry and Evidence remain pure System-of-Record
peers.

## 4. Ports & adapters (per ADR)

### 4.1 Engine ports (ADR-0019)

| Port (Protocol) | Default adapter |
| --- | --- |
| `WorkflowInstanceRepository` | `MongoWorkflowRepository` |
| `TaskRepository` | `MongoTaskRepository` |
| `TimerRepository` | `MongoTimerRepository` |
| `DefinitionLoader` | reads `contracts/v1/workflow_definitions/*.v1.json` at boot |
| `CommandBus` | kernel outbox (existing) |
| `EventBus` | kernel outbox subscribers (existing) |

### 4.2 Consent ports (ADR-0020)

| Port | Adapter |
| --- | --- |
| `ConsentRepository` | `MongoConsentRepository` |
| `EvidenceCommandPort` | thin wrapper around kernel outbox emitting `evidence.command.*` |
| `WitnessAttestationStore` | `MongoWitnessAttestationRepository` |
| `StatementTemplateLoader` | reads frozen JSON content |

### 4.3 Community ports (ADR-0021)

| Port | Adapter |
| --- | --- |
| `CommunityValidationRepository` | `MongoCommunityRepository` |
| `ConsensusScorer` | `domain/community/consensus.py` (pure function) |
| `ComplianceReviewRepository` | `MongoCommunityRepository` (same collection family) |
| `SGReviewRepository` | same |
| `AttestationAppealRepository` | same |

### 4.4 Inheritance ports (ADR-0022)

| Port | Adapter |
| --- | --- |
| `InheritanceCaseRepository` | `MongoInheritanceRepository` |
| `BeneficiaryClaimRepository` | same |
| `ShareCalculator` | `domain/inheritance/share_calculation.py` per-regime pure functions |
| `RegimeLoader` | reads `contracts/v1/inheritance_regimes/*.v1.json` |
| `CourtOrderStore` | `MongoCourtOrderRepository` |
| `RegistryCommandPort` | kernel outbox wrapper |

### 4.5 UI integration points (deferred to a Phase 4.9-equivalent)

- New SDK clients listed in §1 frontend layout.
- New React workspace at `/workflow/*` mirroring the Evidence
  workspace pattern (workspace shell + side nav + tabs).
- The SDK consumes ONLY the new admin/router endpoints under
  `/api/v1/workflow/*`; the existing UI is untouched.

## 5. Repositories & collections (Mongo)

| Collection | Aggregate | Indexes (proposed) |
| --- | --- | --- |
| `workflow_instances` | WorkflowInstance | `instance_id` unique, `(definition_name, state)`, `correlation_id`, `tenant_id` |
| `workflow_tasks` | Task | `task_id` unique, `(assigned_to_role, state)`, `(definition_name, due_at)` |
| `workflow_timers` | Timer | `timer_id` unique, `(fire_at, status)` |
| `workflow_compensation_log` | CompensationLog | `instance_id`, append-only |
| `workflow_event_log` | per-instance events | `(aggregate_id, seq)` unique |
| `consent_requests` | ConsentRequest | `request_id` unique, `(principal_id, state)` |
| `consent_captures` | ConsentCapture | `capture_id` unique, `request_id` |
| `witness_attestations` | WitnessAttestation | `attestation_id` unique, `capture_id` |
| `consent_revocations` | ConsentRevocation | `revocation_id` unique, `request_id` unique (1:1) |
| `community_validations` | CommunityValidation | `instance_id` unique, `(state, escalated_to)` |
| `attestations` | Attestation | `(instance_id, actor_id, seq)` unique |
| `compliance_reviews` | ComplianceReview | `instance_id` unique |
| `sg_reviews` | SGReview | `instance_id` unique |
| `attestation_appeals` | AttestationAppeal | `instance_id` unique |
| `inheritance_cases` | InheritanceCase | `case_id` unique, `(deceased_owner_id, state)` |
| `beneficiary_claims` | BeneficiaryClaim | `(case_id, beneficiary_id)` unique |
| `share_calculations` | ShareCalculation | `case_id` (1:N versioned) |
| `subdivision_plans` | SubdivisionPlan | `plan_id` unique, `case_id` |
| `court_orders` | CourtOrder | `court_order_id` unique, `evidence_id` unique |
| `inheritance_appeals` | InheritanceAppeal | `appeal_id` unique, `case_id` |

All repositories follow the kernel's BaseDocument pattern
(ObjectId → str via PyObjectId, idempotent `ensure_indexes()`).

## 6. Services (application layer)

### 6.1 Engine (`engine.py`)

The heart of Phase 4. Responsibilities:

- `start_workflow(definition_name, initiator, payload, correlation_id)` → instance_id
- `apply_command(instance_id, command_name, actor, payload)`
- `fire_timer(timer_id)` (invoked by the publisher loop)
- `replay(instance_id)` (rebuilds state from events)
- `cancel(instance_id, reason, actor)`
- `suspend(instance_id, reason, super_admin)` / `reactivate(...)`

Internally the engine:
1. Loads the `WorkflowDefinition` for the instance.
2. Asserts the command is legal in the current state.
3. Records the state transition as an event in `workflow_event_log`.
4. Emits any outbound commands declared by the definition.
5. Schedules timers declared by the definition.

### 6.2 Domain services

Pure modules:
- `consensus.py::compute_score(attestations, role_weights)` — deterministic.
- `share_calculation.py::<regime>_calculate(beneficiaries, parcels)` — one pure function per regime.
- `consent_scoring.py::strength(consent_request, captures, attestations)` — deterministic.

### 6.3 Saga composer

`saga_composer.py` interprets the `next_workflow` declaration on a
terminal state. Example declaration in `inheritance.v1.json`:

```jsonc
"shares_computed": {
  "spawn": {
    "definition": "consent.v1",
    "for_each": "$.beneficiaries[*]",
    "join_on_terminal": ["COMPLETED", "DECLINED"]
  }
}
```

The composer is a small DSL interpreter — pure, replayable, content-driven.

## 7. Implementation order

Phase 4 is broken into **6 vertical slices**, each with its own
acceptance gate (matching the Phase 3 cadence). Implementation
begins only after operator approval of this blueprint.

| Slice | Title | Scope | Acceptance gate |
| --- | --- | --- | --- |
| **4.0** | Foundation & blueprint freeze | Author content schemas; freeze contract v2.0.0 in dev; CI drift gate updated. | drift gate green; contract test passes |
| **4.1** | Workflow engine MVP | Engine + definitions + instances + tasks + timers + replay. ONE trivial workflow (`echo.v1`) demonstrates the engine end-to-end. | engine replay byte-identical; PEP enforced |
| **4.2** | Consent sub-context | ADR-0020 in full. | consent replay byte-identical; Evidence pipeline end-to-end |
| **4.3** | Community Validation sub-context | ADR-0021 (survey assignment, community_validation, clarification, compliance_review, sg_review, appeals). | consensus score deterministic; SG-only commit guard |
| **4.4** | Inheritance sub-context | ADR-0022 in full. | share calculation deterministic per regime; court order directive set complete |
| **4.5** | Saga composition + projections | `saga_composer.py`, all read-side projections, admin router. | projection determinism gate; queue-view tests |
| **4.6** | UI integration | TypeScript SDK + React workspace + WCAG 2.2 AA. | SDK consistency gate; no direct REST |
| **4.7** | Acceptance Review packet | mirrors Phase 3.10 — 17-section audit, real perf bench, ADR matrix, PRR. | operator approval |

Each slice ships independently behind a contract-version bump
(`v2.0.0` → `v2.0.6`). Slice acceptance gates use the same
`testing_agent_v3_fork` cadence Phase 3 used.

## 8. Acceptance gates

Per the consolidated checklist in `PHASE4_SPEC.md §9`. The
binding gates are:

1. Architectural review checklist (§9.9): no cross-context writes.
2. Replay determinism (§9.2): every aggregate.
3. Authorization (§9.3): every endpoint role-scoped.
4. Performance (§9.7): p95 ≤ 250 ms reads, replay ≤ 5 s/1k events.
5. Security (§9.8): all R-2 headers present.
6. Operator sign-off (§9.10).

## 9. Risk register

| ID | Title | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- | --- |
| RB-1 | Definition DSL turns Turing-complete by accident | Low | High | Constrain to a small, frozen vocabulary (states, transitions, spawn, timer). Reject Lua / Python expressions. |
| RB-2 | Replay-time complexity grows with instance length | Medium | Medium | Snapshot every 100 events (engine-level; opt-in per workflow). |
| RB-3 | Consensus role weights become politically contested | High | Medium | Treat weights as content + jurisdiction overlays; freeze per version; route changes through operator approval. |
| RB-4 | Court order directive vocabulary is insufficient | Medium | Medium | Allow `compliance_officer` to translate free-text directives into enumerated verbs; reject untranslated orders. |
| RB-5 | Multi-saga deadlock (cycle of "spawn next") | Low | High | Static analyser rejects cyclical `spawn` graphs at definition load. |
| RB-6 | Timer storm after a long outage | Medium | Medium | On boot, the timer service spreads pending fires across a configurable jitter window. |
| RB-7 | Migration of in-flight instances when a workflow definition is updated | Medium | High | Existing instances continue under the version they started on; new instances use the new version. Documented; no runtime migration. |
| RB-8 | Customary regime overlay missing for a jurisdiction at launch | Medium | High | Catalog launch-blocking jurisdictions; treat missing overlay as a launch checklist item. |
| RB-9 | Phase 4 perf below SLO under load | Low | Medium | Multi-client load test in 4.7 acceptance; horizontal-scale the worker pool. |
| RB-10 | Operator confusion between "appeal" workflows (community vs inheritance) | Medium | Low | Distinct naming + role-distinct queues. |

## 10. Migration strategy

There is no data to migrate. Phase 4 introduces NEW collections only
(`workflow_*`, `consent_*`, `community_*`, `inheritance_*`). Existing
Registry / Evidence data is unaffected.

Cutover sequencing:
1. Deploy slice 4.0 + 4.1 — engine live but no workflows invoke
   cross-context commands.
2. Deploy slice 4.2 — consent capture available; consuming
   workflows opt in.
3. Deploy 4.3–4.4 — full community + inheritance available; pilot in
   one jurisdiction.
4. Deploy 4.5–4.6 — UI + admin tooling.
5. Deploy 4.7 — Acceptance Review + operator approval.
6. National rollout follows operator authorization.

The platform never "switches off" the old (manual) flow — it always
exists as a `super_admin` break-glass. Phase 4 is purely additive.

## 11. Replay strategy

- **Workflow instance replay:** rebuilds aggregate state from
  `workflow_event_log` via the engine's pure `apply(state, event)`
  function. Tested byte-identical.
- **Projection replay:** uses the existing ADR-0010 engine.
- **Saga replay:** composing instances is implicit — each instance
  replays independently; the saga composer is stateless and reads
  terminal events.
- **Cross-context replay:** Phase 4 never replays Registry or
  Evidence events. It observes them. If a cross-context event is
  re-delivered, the instance's idempotency key
  (`correlation_id, command_id`) deduplicates.

## 12. Failure recovery

Inherited from Phase 3:
- Resumable saga retries (exponential backoff up to N attempts).
- Outbox idempotency (unique `event_id`).
- Optimistic concurrency on every aggregate.
- Compensation log replays in reverse emission order.

Net new for Phase 4:
- Timer storm jitter (RB-6).
- `definition_load_failure` event published at startup if a
  `WorkflowDefinition` JSON is malformed — engine refuses to boot.
- An instance whose definition has been removed (operationally
  forbidden, but defensively handled) transitions to a quarantine
  state and is paged.

## 13. Operational considerations

| Concern | Plan |
| --- | --- |
| Onboarding new workflows | Author a new `*.v1.json`; ship via the next contract bump; ADR if it crosses bounded contexts. |
| Onboarding new jurisdictions | Add an overlay JSON; no code change. |
| Operator visibility | New admin pages mirror the Phase 3 projections admin: `/workflow/admin/queues`, `/workflow/admin/instances/{id}`, `/workflow/admin/timers`. |
| Alerts | New alarms (per RUNBOOK §13): `workflow.task.expired_count > N`, `workflow.timer.backlog > N`, `workflow.command.rejected_streak > N`, `inheritance.case.closed_unresolved emitted`. |
| Audit | Append-only to `audit_log` (existing). |
| Backup | Existing Mongo backup policy covers the new collections. |
| Disaster recovery | Replay rebuilds every workflow aggregate from events; no special handling. |

## 14. Cross-references

- ADR-0019 — [`ADR-0019-workflow-engine.md`](ADR-0019-workflow-engine.md)
- ADR-0020 — [`ADR-0020-consent-engine.md`](ADR-0020-consent-engine.md)
- ADR-0021 — [`ADR-0021-community-validation-and-attestation.md`](ADR-0021-community-validation-and-attestation.md)
- ADR-0022 — [`ADR-0022-inheritance-and-customary-resolution.md`](ADR-0022-inheritance-and-customary-resolution.md)
- Constitutional spec — [`PHASE4_SPEC.md`](PHASE4_SPEC.md)
- Phase 3 Acceptance Packet — [`/app/audit/PHASE-3-ACCEPTANCE-PACKET.md`](file:///app/audit/PHASE-3-ACCEPTANCE-PACKET.md)
- Operational Runbook — [`/app/audit/RUNBOOK.md`](file:///app/audit/RUNBOOK.md)
- Security Readiness Report — [`/app/audit/R-2-SECURITY-READINESS-REPORT.md`](file:///app/audit/R-2-SECURITY-READINESS-REPORT.md)

## 15. End of blueprint

Awaiting explicit operator approval of this document, plus
ADRs 0019–0022 and `PHASE4_SPEC.md`. No implementation code,
contracts, SDK, schemas, migrations, tests, or UI will be produced
before that approval.
