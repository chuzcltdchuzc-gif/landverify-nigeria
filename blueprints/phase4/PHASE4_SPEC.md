# Phase 4 — Constitutional Specification (`PHASE4_SPEC.md`)

> **Status:** DRAFT — pending operator approval.
> **Scope:** the binding implementation contract for the Phase 4
> Workflow bounded context.
> **Authority:** ADR-0019 (Workflow Engine), ADR-0020 (Consent),
> ADR-0021 (Community Validation), ADR-0022 (Inheritance).
> **Implementation:** NONE — this is architecture only.

This document is the constitutional contract. It defines every
workflow, aggregate, invariant, command, event, policy, saga,
projection, authorization rule, state transition, and acceptance
gate for Phase 4. Implementation begins only after operator
approval of this spec + the master blueprint.

---

## 1. Workflow inventory

| # | Workflow | Authority ADR | Initiating role |
| --- | --- | --- | --- |
| 1 | `consent.v1` | ADR-0020 | calling workflow (saga-initiated) |
| 2 | `consent_revocation.v1` | ADR-0020 | the original principal |
| 3 | `survey_assignment.v1` | ADR-0021 | `field_agent`, `compliance_officer` |
| 4 | `community_validation.v1` | ADR-0021 | preceding workflow's saga |
| 5 | `clarification.v1` | ADR-0021 | any attesting party |
| 6 | `compliance_review.v1` | ADR-0021 | preceding workflow's saga |
| 7 | `surveyor_general_review.v1` | ADR-0021 | preceding workflow's saga |
| 8 | `attestation_appeal.v1` | ADR-0021 | aggrieved party |
| 9 | `inheritance.v1` | ADR-0022 | `compliance_officer`, next of kin |
| 10 | `inheritance_appeal.v1` | ADR-0022 | aggrieved party |
| 11 | `subdivision.v1` (embedded in inheritance) | ADR-0022 | surveyor |
| 12 | `notification.v1` | this spec §3.4 | any workflow's saga |
| 13 | `escalation.v1` (helper) | ADR-0021 | engine timer |
| 14 | `withdrawal.v1` (helper) | ADR-0019 | originator |
| 15 | `suspension.v1` (helper, super_admin) | ADR-0019 | `super_admin` only |
| 16 | `reactivation.v1` (helper, super_admin) | ADR-0019 | `super_admin` only |
| 17 | `cancellation.v1` (helper) | ADR-0019 | originator |

Each workflow's state-machine, role table, event set, command set,
and timeouts are codified per-workflow below.

## 2. Aggregates

| Aggregate | Owning ADR | Collection (proposed) | Append-only? |
| --- | --- | --- | --- |
| `WorkflowDefinition` | 0019 | (frozen content) | yes |
| `WorkflowInstance` | 0019 | `workflow_instances` | event-sourced |
| `Task` | 0019 | `workflow_tasks` | mutable on claim/complete; history in events |
| `Timer` | 0019 | `workflow_timers` | mutable on fire/cancel; history in events |
| `CompensationLog` | 0019 | `workflow_compensation_log` | yes |
| `ConsentRequest` | 0020 | `consent_requests` | event-sourced |
| `ConsentCapture` | 0020 | `consent_captures` | yes |
| `WitnessAttestation` | 0020 | `witness_attestations` | yes |
| `ConsentRevocation` | 0020 | `consent_revocations` | yes |
| `InheritanceCase` | 0022 | `inheritance_cases` | event-sourced |
| `BeneficiaryClaim` | 0022 | `beneficiary_claims` | event-sourced |
| `ShareCalculation` | 0022 | `share_calculations` | yes |
| `SubdivisionPlan` | 0022 | `subdivision_plans` | yes |
| `CourtOrder` | 0022 | `court_orders` | yes (wraps Evidence) |
| `InheritanceAppeal` | 0022 | `inheritance_appeals` | event-sourced |

## 3. Invariants (binding — enforced mechanically at acceptance)

### 3.1 Workflow engine (ADR-0019)

| ID | Invariant |
| --- | --- |
| INV-WF-01 | A `WorkflowInstance` exists only via the `start_workflow` command. |
| INV-WF-02 | `WorkflowDefinition.version` is immutable; new versions are new files. |
| INV-WF-03 | A state transition not declared in the definition raises `InvariantViolation`. |
| INV-WF-04 | An instance MUST NOT emit a command to a collection outside `workflow_*` directly. |
| INV-WF-05 | Replay of an instance's event log reproduces state, task set, timer set, and emitted commands byte-for-byte. |
| INV-WF-06 | Compensation runs in reverse emission order. |
| INV-WF-07 | A Task may be claimed by at most one actor at a time. |
| INV-WF-08 | A Timer fires at most once per scheduling. |
| INV-WF-09 | Optimistic concurrency: every aggregate carries a `version` field; conflicting writes are rejected. |
| INV-WF-10 | The kernel outbox is the ONLY mechanism for emitting events from the Workflow context. |

### 3.2 Consent (ADR-0020)

| ID | Invariant |
| --- | --- |
| INV-CN-01 | A `ConsentCapture` produces exactly one Evidence item. |
| INV-CN-02 | A capture mode declared as required MUST be captured before `COMPLETED`. |
| INV-CN-03 | Every required witness MUST attest before `COMPLETED`. |
| INV-CN-04 | Strength score is a pure function of the event log; replay reproduces it byte-for-byte. |
| INV-CN-05 | A `ConsentRevocation` is terminal; the revoked consent is never re-activated. |
| INV-CN-06 | Statement template version cannot change after `REQUESTED`. |
| INV-CN-07 | Decline is terminal; an actor cannot un-decline. |
| INV-CN-08 | Consent never emits a Registry command. |

### 3.3 Community Validation (ADR-0021)

| ID | Invariant |
| --- | --- |
| INV-CV-01 | Consensus score is pure-functional from the attestation event log. |
| INV-CV-02 | The Surveyor General is the only role that may emit `registry.command.commit_parcel`. |
| INV-CV-03 | An attestation is append-only; re-attestation creates a revision event, original preserved. |
| INV-CV-04 | A clarification request pauses the instance until `RESPONDED` or `TIMED_OUT`. |
| INV-CV-05 | A workflow is REJECTED if any `traditional_authority` dissents OR consensus_score ≤ 0.30. |
| INV-CV-06 | A rejected workflow is never deleted. |
| INV-CV-07 | An appeal is a separate workflow; it does not mutate the appealed instance's events. |

### 3.4 Inheritance (ADR-0022)

| ID | Invariant |
| --- | --- |
| INV-IH-01 | A case requires death verification before any beneficiary work. |
| INV-IH-02 | Share calculation is deterministic and reproducible. |
| INV-IH-03 | Customary regime overlays are content, not code. |
| INV-IH-04 | A court order's directives use enumerated verbs. |
| INV-IH-05 | Subdivisions supersede; the parent parcel is never deleted. |
| INV-IH-06 | An appeal blocks the case at its current state until terminal. |
| INV-IH-07 | A `NULLIFIED` or `CLOSED_UNRESOLVED` case retains full history. |

## 4. State transitions (explicit per workflow)

For each workflow, the spec enumerates allowed transitions in the
form `from → to | guard | required_role | emits`. For brevity in
this section, the spec references the diagrams in each ADR (see
ADR-0020 §2.2, ADR-0021 §2.1, ADR-0022 §2.2) and adds the binding
that **any transition not listed is illegal**.

The frozen state tables live in
`contracts/v1/workflow_definitions/*.v1.json` once Phase 4
implementation is authorized. They are NOT created during
blueprinting.

## 5. Event catalogue (complete)

All Phase 4 events follow the existing Envelope schema (Phase 1)
with `event_type = "<context>.<aggregate>.<verb>.v1"`. The catalog
is enumerated by the four ADRs; below is the consolidated index.
Versioning: every event is `.v1`; a breaking change demands a
new `.v2` file. Idempotency: every event carries a unique `event_id`;
projections dedup on `(aggregate_id, seq)`.

### 5.1 Workflow engine events

`workflow.instance.started.v1` · `state_entered.v1` ·
`state_exited.v1` · `completed.v1` · `cancelled.v1` ·
`compensated.v1` · `replay_observed.v1`
`workflow.task.created.v1` · `assigned.v1` · `claimed.v1` ·
`completed.v1` · `cancelled.v1` · `expired.v1` · `reassigned.v1`
`workflow.timer.scheduled.v1` · `fired.v1` · `cancelled.v1`
`workflow.command.issued.v1` · `accepted.v1` · `rejected.v1` ·
`compensated.v1`

### 5.2 Consent events

`consent.request.created.v1` · `state_entered.v1` ·
`completed.v1` · `expired.v1` · `cancelled.v1`
`consent.witness.invited.v1` · `arrived.v1` · `attested.v1` ·
`declined_arrival.v1`
`consent.capture.recorded.v1` · `sealed.v1` ·
`evidence_bound.v1`
`consent.revocation.requested.v1` · `recorded.v1`
`consent.decline.recorded.v1`

### 5.3 Community Validation events

`community_validation.initiated.v1` · `attestation_recorded.v1` ·
`attestation_revised.v1` · `dissent_recorded.v1` ·
`consensus_computed.v1` · `attested.v1` · `rejected.v1` ·
`escalated.v1`
`clarification.requested.v1` · `responded.v1` · `timed_out.v1`
`compliance_review.queued.v1` · `under_review.v1` ·
`approved.v1` · `returned.v1` · `rejected.v1`
`surveyor_general_review.queued.v1` · `approved.v1` ·
`held_for_info.v1` · `rejected.v1`
`attestation_appeal.filed.v1` · `heard.v1` · `decision_final.v1` ·
`dismissed.v1`

### 5.4 Inheritance events

`inheritance.filed.v1` · `death_verified.v1` ·
`death_nullified.v1` · `beneficiary_added.v1` ·
`beneficiary_validated.v1` · `beneficiary_disputed.v1` ·
`regime_determined.v1` · `shares_computed.v1` ·
`shares_recomputed.v1` · `beneficiary_consent_collected.v1` ·
`subdivision_drafted.v1` · `subdivision_approved.v1` ·
`committed.v1` · `closed_unresolved.v1` · `withdrawn.v1` ·
`nullified.v1`
`inheritance_appeal.filed.v1` · `noticed.v1` · `heard.v1` ·
`decision_drafted.v1` · `decision_final.v1` · `dismissed.v1`
`court_order.received.v1` · `directive_applied.v1`

### 5.5 Cross-context commands EMITTED by Phase 4

(Consumed by Registry / Evidence — handlers already exist in
Phases 2 / 3; new command types declared here.)

| Command | Target | Authority |
| --- | --- | --- |
| `evidence.command.initiate_upload` | Evidence | any consent capture |
| `evidence.command.complete_upload` | Evidence | any consent capture |
| `evidence.command.seal` | Evidence | any consent capture |
| `evidence.command.apply_worm` | Evidence | any consent capture |
| `registry.command.transfer_ownership` | Registry | SG-approved workflow |
| `registry.command.create_parcel` | Registry | SG-approved subdivision |
| `registry.command.supersede_parcel` | Registry | SG-approved subdivision |
| `registry.command.attach_legal_hold_reference` | Registry | court order |

Every command carries:
- `command_id` (UUIDv7),
- `correlation_id` (== workflow instance id),
- `causation_id` (the workflow event that emitted it),
- `actor` (the signing human role),
- `tenant_id`,
- `payload`.

## 6. Authorization (PEP rules)

Every workflow command goes through `await enforce(<action>,
resource=...)`. The new actions introduced by Phase 4:

| Action | Required role(s) |
| --- | --- |
| `workflow.start.<def>` | varies per definition (see ADRs) |
| `workflow.task.claim` | the role declared in the task |
| `workflow.task.complete` | the role declared in the task |
| `workflow.cancel` | originator or `super_admin` |
| `workflow.suspend` | `super_admin` |
| `workflow.reactivate` | `super_admin` |
| `consent.witness.attest` | `compliance_officer`, `traditional_authority`, `community_representative`, `surveyor`, or other configured slate role |
| `consent.revoke` | the original principal only |
| `community_validation.attest` | `village_elder`, `traditional_authority`, `community_representative`, `surveyor`, or jurisdiction overlay |
| `compliance_review.decide` | `compliance_officer` |
| `surveyor_general_review.decide` | `surveyor_general` |
| `inheritance.file` | `compliance_officer`, next-of-kin attested via Evidence |
| `inheritance.commit` | spawned-saga only (system); requires SG approval upstream |
| `court_order.record` | `compliance_officer` |
| `appeal.file` | aggrieved party (identified via JWT) |
| `appeal.decide` | `compliance_officer`, escalated to court if external |

The full policy table is content (`contracts/v1/security/workflow_actions.json`), frozen.

### 6.1 Role catalogue (consolidated)

| Role | Source | New in Phase 4 |
| --- | --- | --- |
| `super_admin` | Phase 1 | no |
| `compliance_officer` | Phase 3 | no |
| `field_agent` | Phase 2 | no |
| `surveyor` | Phase 2 | no |
| `traditional_authority` | yes (Phase 4) | **yes** |
| `village_elder` | yes (Phase 4) | **yes** |
| `community_representative` | yes (Phase 4) | **yes** |
| `surveyor_general` | yes (Phase 4) | **yes** |
| `witness` | yes (Phase 4) | **yes** (label only — actor must hold another role) |
| `next_of_kin` | yes (Phase 4) | **yes** (label only) |
| `beneficiary` | yes (Phase 4) | **yes** (label only) |

Observation: `witness`, `next_of_kin`, and `beneficiary` are **labels**
the workflow attaches to an authenticated actor; they are not
stand-alone JWT roles. They are scoped to a workflow instance.

### 6.2 Authorization meta-rules

For every workflow transition the spec MUST declare:
- **who may perform it** (positive grant),
- **who may observe it** (read scope),
- **who may override it** (`super_admin` + `compliance_officer`
  break-glass with audit),
- **who may appeal it** (typically `traditional_authority`,
  `next_of_kin`, `beneficiary` of the affected case).

## 7. Sagas (composition rules)

Every multi-step process is a sequence of `WorkflowInstance`s
chained by event correlation. Examples (full list in
PHASE4_BLUEPRINT §7):

- **Full inheritance saga.** `inheritance.v1` → `community_validation.v1`
  for each contested beneficiary → `consent.v1` per beneficiary →
  `subdivision.v1` if multi-heir → `compliance_review.v1` →
  `surveyor_general_review.v1` → emit Registry commands.
- **Spousal transfer saga.** `consent.v1` (spouse) →
  `community_validation.v1` → `surveyor_general_review.v1` →
  Registry transfer.
- **Beacon dispute saga.** `clarification.v1` → if unresolved,
  `community_validation.v1` for the beacon area → SG review →
  surveyor re-issues report.

Saga composition is mechanical — each workflow's terminal events
specify a "spawn next" expression that the engine interprets.
Compositions never live in code.

## 8. Projections (read models)

All projections are ADR-0010 compliant: zero business logic,
disposable, replayable, versioned.

| Projection | Backed collections | Refreshed by events |
| --- | --- | --- |
| `workflow.queue` | `workflow_queue_view` | `workflow.task.*` |
| `workflow.instance_timeline` | `workflow_instance_timeline` | every event of an instance |
| `consent.requests` | `consent_request_view` | `consent.*` |
| `community.case_dashboard` | `community_case_view` | `community_validation.*`, `compliance_review.*`, `surveyor_general_review.*` |
| `inheritance.case_dashboard` | `inheritance_case_view` | `inheritance.*`, `inheritance_appeal.*`, `court_order.*` |
| `compliance.work_queue` | `compliance_queue_view` | `compliance_review.queued.v1`, `…approved.v1`, … |
| `sg.work_queue` | `sg_queue_view` | `surveyor_general_review.*` |
| `audit.timeline` | reuses Phase 3 timeline | inherits |

Each projection registers through the existing Projection Engine
(ADR-0010). Each has `reset()` that wipes its own rows. Each is
replay-byte-identical.

## 9. Acceptance gates (binding for Phase 4 implementation)

Acceptance follows the discipline established by Phase 3.10. The
following items MUST be green before Phase 4 is declared complete:

### 9.1 Invariant checklist

- [ ] Every invariant in §3 has a positive AND a negative test.
- [ ] Every workflow's illegal transitions raise `InvariantViolation`.
- [ ] Optimistic concurrency on every aggregate.

### 9.2 Replay checklist

- [ ] `test_workflow_instance_replay_byte_identical` for the
  Workflow engine (mirrors ADR-0010 §3).
- [ ] `test_consent_replay_byte_identical`.
- [ ] `test_community_validation_replay_byte_identical`.
- [ ] `test_inheritance_replay_byte_identical`.
- [ ] All projections (§8) pass the determinism gate.

### 9.3 Authorization checklist

- [ ] Every Phase 4 endpoint declares its required role(s).
- [ ] No anonymous mutation possible.
- [ ] PEP rejects unrecognised actions with `auth.policy_deny`.
- [ ] `kernel.projections.admin` continues to be the only
  super_admin-only namespace for projection admin.

### 9.4 Evidence integrity checklist

- [ ] Every legally-consequential event carries the required
  Evidence id.
- [ ] Evidence items produced by Phase 4 pass the existing
  Phase 3 invariants (sealed, WORM-applied, integrity-checked).

### 9.5 State-machine validation

- [ ] Every workflow's state graph is parsed at startup.
- [ ] A workflow with an unreachable terminal state fails to load.
- [ ] A workflow with a cycle that lacks a guard fails to load.

### 9.6 Failure recovery / saga tests

- [ ] Resumable saga recovers from publisher crash mid-emit.
- [ ] Compensation runs in reverse emission order.
- [ ] Cross-context command rejection routes to the workflow's
  declared error branch.

### 9.7 Performance objectives

- [ ] `POST /api/v1/workflow/instances` p95 < 200 ms (single-client).
- [ ] `GET .../workflow/instances/{id}/timeline` p95 < 250 ms.
- [ ] Replay of a 1,000-event workflow instance < 5 s.

### 9.8 Security objectives

- [ ] All Phase 4 endpoints carry the production security headers
  from R-2.
- [ ] Rate limiter buckets defined for each new public path.
- [ ] No new secret hardcoded; all keys from `.env`.

### 9.9 Architectural review checklist

- [ ] No `from contexts.registry` or `from contexts.evidence`
  imports inside `contexts/workflow/`.
- [ ] No collection write outside `workflow_*` from `application/`.
- [ ] Static check: `tests/test_phase4_architecture.py::test_no_cross_context_writes`.

### 9.10 Operator sign-off checklist

- [ ] Phase 4 Acceptance Review packet generated (analogous to
  Phase 3.10).
- [ ] PRR for Phase 4 generated.
- [ ] Operator explicitly authorizes Phase 5 (whatever comes next).

---

## 10. Frozen content artifacts introduced by Phase 4

A future contract bump (proposed `v2.0.0` major — this is the
first non-additive change since v1.0.0) introduces these new artifact
families under `contracts/v1/`:

- `workflow_definitions/*.v1.json` — every state machine.
- `inheritance_regimes/*.v1.json` — per-regime share formulae +
  jurisdiction overlays.
- `consent_statement_templates/*.v1.json` — versioned consent text.
- `security/workflow_actions.json` — action → role mapping.
- `events/workflow.*.v1.json` + `consent.*.v1.json` +
  `community.*.v1.json` + `inheritance.*.v1.json` — every event
  schema.

The drift gate extends to all of the above. None of these files
are created during blueprinting.

---

## 11. Out of scope (explicit non-goals)

- **AI-assisted attestation extraction.** Out of scope; a candidate
  for Phase 5+ assistive tooling only.
- **Cross-border inheritance.** Out of scope.
- **Real-time push notifications.** A read-only push channel exists
  (`notification.v1` workflow) but no SMS / Email adapter is part of
  this spec — those are deferred sub-adapters.
- **Smart-contract / DLT export.** Out of scope; OTS already provides
  external timestamp anchoring.
- **Public-facing self-service portals for citizens.** Out of scope
  for Phase 4; planned in a later phase once the operator-facing
  experience is hardened.

---

## 12. Conclusion

This spec is the **constitutional contract** for Phase 4. It is
complete enough to drive implementation while remaining
implementation-agnostic. Every binding rule has a test; every test
has an invariant; every invariant is traceable to an ADR.

**Phase 4 implementation may begin only after operator approval
of this document + `PHASE4_BLUEPRINT.md` + ADRs 0019–0022.**
