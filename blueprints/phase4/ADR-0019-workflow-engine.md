# ADR-0019 — Workflow Engine (Phase 4)

* **Status:** DRAFT — pending operator approval
* **Phase:** 4 (Workflows)
* **Contract version on acceptance:** to be assigned at implementation start (proposed `v2.0.0` major)
* **Authoring directive:** "Constitutional Authorization — Begin Phase 4 Blueprinting Only" (operator, 2026-06-30)
* **Constitutional ancestry:** ADR-0001 (Platform Contract Freeze), ADR-0003 (Bounded Context), ADR-0010 (Projection Engine)
* **Scope of this document:** architecture only. No code, no contracts, no schemas. The implementation contract lives in `PHASE4_SPEC.md`.

---

## 1. Context

Phases 1–3 produced three bounded contexts that hold authoritative
state:

| Bounded context | Owns |
| --- | --- |
| Identity | users, roles, sessions |
| Registry | LandVault aggregates (parcels) |
| Evidence | upload, hashes, seals, anchors, integrity, timeline, custody, legal-hold |

What is **missing** is the orchestration layer that drives
**multi-step, multi-actor, human-authoritative processes** through
those contexts. Recording an ownership transfer today requires a
trained operator to issue a sequence of Registry + Evidence commands
manually. Phase 4 introduces a fourth bounded context — **Workflow**
— that owns:

- the **business processes** of land governance (consent, survey,
  community validation, attestation, inheritance, appeal),
- the **state machines** that govern each process,
- the **task queues** that route work to human actors,
- the **timers** that enforce SLAs and escalations,
- the **sagas** that compose Registry + Evidence + Workflow events
  into a single replayable narrative.

## 2. Decision

We adopt a single, dedicated **Workflow bounded context** that
follows the same Domain-Driven, CQRS, event-sourced, replay-safe
disciplines established in Phases 1–3, with the additional
constitutional rule that **Workflows are observers and orchestrators,
not mutators, of every other bounded context**.

### 2.1 Bounded context boundary

```
contexts/
├── identity/       ← Phase 1 (untouched)
├── registry/       ← Phase 2 (untouched)
├── evidence/       ← Phase 3 (untouched)
└── workflow/       ← Phase 4 (NEW)
    ├── domain/
    ├── application/
    ├── adapters/
    └── api/
```

`contexts/workflow/` is a **peer** of Identity / Registry / Evidence
— never a parent, never a child. It speaks to them through the
existing **outbox + command bus** pattern.

### 2.2 Aggregates owned by the Workflow context

| Aggregate | Owns | Lifecycle |
| --- | --- | --- |
| `WorkflowDefinition` | The static state-machine graph (states, allowed transitions, role requirements, timer specs) for one workflow kind. | Versioned. Immutable per version. |
| `WorkflowInstance` | A single in-flight execution of a `WorkflowDefinition`. Holds current state, correlation id, event-sourced. | Created → running → terminal (completed/cancelled/compensated). |
| `Task` | A human-actionable item assigned to a role / actor. Owns due_at, assigned_to, claim history, completion data. | Created → claimed → completed / cancelled / expired. |
| `Timer` | A scheduled event that fires at an absolute time. | Scheduled → fired / cancelled. |
| `CompensationLog` | Append-only record of compensation steps applied when an instance must roll back a previously-emitted command effect. | Append-only. |

`WorkflowDefinition` is platform-frozen content (loaded at startup
from `contracts/v1/workflow_definitions/` — a NEW frozen artifact
family introduced under Phase 4's contract bump). The other four are
write-side aggregates owned by Mongo collections under
`workflow_*` prefixes.

### 2.3 Responsibilities

The Workflow context is responsible for:

1. **State-machine execution.** Given a `WorkflowDefinition` and a
   current `WorkflowInstance` state, deterministically compute the
   next state on receipt of a command/event.
2. **Task lifecycle.** Create, assign, claim, complete, expire tasks.
3. **Timer lifecycle.** Schedule absolute-time timers (durable);
   fire them via the existing outbox publisher.
4. **Saga orchestration.** Emit cross-context commands (e.g.
   "transfer ownership") to Registry / Evidence, and consume the
   resulting events to advance the workflow state.
5. **Compensation.** When a workflow cancels mid-flight, emit
   compensating commands in reverse order.
6. **Read-side projections.** Materialise queryable views — work
   queues, instance timelines, compliance dashboards — through the
   existing Projection Engine from ADR-0010.

The Workflow context is NOT responsible for:

- Mutating Registry aggregates directly. Forbidden.
- Mutating Evidence aggregates directly. Forbidden.
- Containing business rules that belong to Registry / Evidence
  domain models (e.g. "an evidence item must be VERIFIED before
  sealing"). Workflows compose those rules; they do not redefine
  them.

### 2.4 Boundaries (the four constitutional vows)

The Workflow context obeys four binding rules — every one of them is
a registered invariant in `PHASE4_SPEC.md`:

1. **No direct cross-context writes.** A workflow advancing a
   Registry parcel emits a `registry.commands.transfer_ownership`
   command via the outbox; the Registry context's command handler
   accepts or rejects it. A rejection produces a domain event the
   workflow observes and acts upon.
2. **No business logic in projections.** ADR-0010 §1 still binds.
   Every workflow read model is event-to-row only.
3. **No AI decision-making.** Scoring (e.g. consensus strength) is
   deterministic, fully explainable, and reproducible from the
   event stream. ML / LLM components MAY assist a human reviewer
   (e.g. extract candidate beneficiary names from a court order PDF)
   but MUST NOT issue commands. Every workflow transition that
   carries legal weight is signed by a human actor.
4. **Replay determinism (extended).** Re-applying the event stream
   for a `WorkflowInstance` MUST reproduce the exact same state, task
   set, timer set, and emitted command set. This extends ADR-0010
   from projections to instances.

### 2.5 Aggregate ownership table (write-side)

| Aggregate | Created by | Mutated by | Read by |
| --- | --- | --- | --- |
| `WorkflowDefinition` | platform deploy (frozen) | never | workflow engine, audit |
| `WorkflowInstance` | `WorkflowEngine.start()` | own command handlers only | projections |
| `Task` | own command handlers | claim/complete commands | task-queue projection |
| `Timer` | own command handlers | fire/cancel commands | timer-queue projection |
| `CompensationLog` | own command handlers | append-only | audit, projections |

### 2.6 Event ownership

| Event family | Owner | Examples |
| --- | --- | --- |
| `workflow.instance.*` | Workflow | `started`, `state_entered`, `state_exited`, `completed`, `cancelled`, `compensated`, `replay_observed` |
| `workflow.task.*` | Workflow | `created`, `assigned`, `claimed`, `completed`, `cancelled`, `expired`, `reassigned` |
| `workflow.timer.*` | Workflow | `scheduled`, `fired`, `cancelled` |
| `workflow.command.*` | Workflow | `issued`, `accepted`, `rejected`, `compensated` |
| `consent.*` | Consent sub-context (ADR-0020) | see ADR-0020 |
| `community.*` | Community sub-context (ADR-0021) | see ADR-0021 |
| `inheritance.*` | Inheritance sub-context (ADR-0022) | see ADR-0022 |

The full event catalogue is enumerated in `PHASE4_SPEC.md §5`.

### 2.7 Saga ownership

There is exactly **one** saga implementation pattern: the
`WorkflowInstance` itself IS the saga. When an instance transitions
into a state whose `WorkflowDefinition` declares an outbound
command, the engine emits that command via the kernel outbox. When
the corresponding result event arrives (`registry.ownership.recorded`
or `registry.command.rejected`), the engine maps the event back to
the instance via `correlation_id` and advances the state machine.

**No separate "saga manager" exists.** This is intentional — sagas
that live outside the workflow engine create dual sources of truth
and break replay determinism.

### 2.8 Replay rules

A `WorkflowInstance` is fully event-sourced. To rehydrate:

1. Load the instance's correlation_id.
2. Query `workflow_event_log` for every event whose `aggregate_id ==
   instance.id`, sorted by `seq` ASC.
3. Fold the events through the `WorkflowDefinition.apply(state,
   event) → state` pure function.
4. Idempotency: re-folding the same events MUST produce the same
   state. Tested in the Phase 4 acceptance suite.

Replay of cross-context events (`registry.ownership.recorded`) is
unchanged — Workflow simply observes them. The Workflow context
NEVER replays cross-context events; it replays its own log only.

### 2.9 Failure handling

| Failure | Workflow response |
| --- | --- |
| Command rejected by target context | Move to error state declared in the `WorkflowDefinition`. Operator-driven retry or compensation. |
| Timer fires but instance is gone | Logged and dropped (event is harmless). |
| Task expires without completion | Emit `workflow.task.expired`. The `WorkflowDefinition` declares the next state. |
| External adapter timeout | Resumable saga retry policy — exponential backoff up to N attempts, then escalate to the error state. |
| Concurrent commands on the same instance | Optimistic concurrency on `version` field; second command rejected. |
| Definition version mismatch (instance started against v1, definition redeployed as v2) | Instance carries the version it was started on; v2 applies only to NEW instances. Old instances continue under v1 until they reach a terminal state. |

### 2.10 Constitutional constraints (binding)

| # | Constraint | Enforcement |
| --- | --- | --- |
| C-19.1 | Workflows MUST NOT directly write to any collection outside `workflow_*`. | Static import discipline + Phase 4 acceptance test. |
| C-19.2 | Every cross-context effect MUST be emitted as a command through the kernel outbox. | Static check on `application/` layer. |
| C-19.3 | Replay of any `WorkflowInstance` MUST be byte-identical. | Acceptance gate test (mirrors ADR-0010 §3). |
| C-19.4 | All state transitions that carry legal weight MUST be signed by an identified human actor (PEP enforcement). | `enforce("workflow.<action>", …)` on every command handler. |
| C-19.5 | `WorkflowDefinition` is platform-frozen content; live mutation is forbidden. | The frozen contract family `contracts/v1/workflow_definitions/`. |
| C-19.6 | Compensation MUST run commands in reverse emission order. | Domain invariant in `CompensationLog`. |
| C-19.7 | Projections MUST follow ADR-0010 purity rules. | Existing `assert_projection_purity` check. |
| C-19.8 | No AI / LLM component MAY issue a workflow command. | All command handlers go through PEP; PEP rejects unidentified principals. |

## 3. Consequences

### Positive

- A single, replayable, audit-grade home for every business process.
- Registry and Evidence remain perfectly clean — no business
  process leaks into their domain models.
- Operators gain a queryable work queue, SLA dashboard, and
  per-instance replay just like the projection admin UI today.
- New workflows are added by writing a new `WorkflowDefinition` —
  no code change to the engine.

### Negative / trade-offs

- A new bounded context grows the platform footprint.
- The "commands only" rule adds latency for cross-context effects
  compared to direct writes — accepted in exchange for the
  separation of concerns.
- Compensation logic is non-trivial; it must be modelled per
  `WorkflowDefinition`.

## 4. Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| **Embed workflows inside Registry** | Couples business processes to the System of Record; would violate ADR-0003 (bounded context). |
| **External workflow engine (Temporal / Camunda)** | Replay semantics differ; we'd lose the constitutional projection determinism guarantee. Operationally heavier than a small in-house engine. May be re-evaluated post-launch. |
| **Direct-write commands ("workflow can update Registry")** | Violates C-19.1. Breaks the bounded-context invariant Phase 0 spent six months earning. |
| **AI-driven decisions for consensus scoring** | Violates the "human-authoritative" and "explainable scoring only" principles. Land governance has legal weight; an unexplainable model is unacceptable. |

## 5. Open questions for the implementation phase

All deferred to operator approval; none should block this ADR:

- Exact wire format for `WorkflowDefinition` — JSON vs YAML vs a
  small Python DSL. Tentative: JSON Schema-validated YAML.
- Whether the engine ticks via a Mongo change-stream observer or a
  poll loop. Implementation detail; both satisfy replay.
- Whether timers are stored in-Mongo or delegated to a sidecar
  (e.g. APScheduler). Implementation detail.

## 6. Dependencies

- ADR-0010 (Projection Engine) — required.
- ADR-0007 / ADR-0009 (Evidence aggregate + Timeline) — required
  because Consent (ADR-0020) emits evidence items.
- ADR-0002 (Registry) — required because workflows emit Registry
  commands.
- No dependency on yet-undrafted ADRs.

---

> This ADR is the **first** of a four-ADR set. It defines the
> engine. ADR-0020 / ADR-0021 / ADR-0022 each declare a workflow
> sub-context that runs **on** this engine, using only the
> constitutional primitives defined above.
