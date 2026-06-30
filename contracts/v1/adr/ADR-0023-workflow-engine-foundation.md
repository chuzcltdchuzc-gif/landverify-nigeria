# ADR-0023 — Workflow Engine Foundation (Phase 4 Slice 4.0)

* Status: ACCEPTED (Key 2 Implementation Authority, 2026-06-30)
* Supersedes: none
* Depends on: ADR-0019, ADR-0020, ADR-0021, ADR-0022, ADR-0010
* Constitutional posture: foundation slice — engine, definitions,
  instances, tasks, timers, compensation log, saga composer skeleton,
  one minimal projector. Business workflows (Consent, Community,
  Inheritance) remain CONSTITUTIONALLY PROHIBITED pending separate
  Key 2 authorizations for Slices 4.2 – 4.4.

## Context

The Phase 4 Workflow bounded context introduces a generic, replayable
state-machine engine that drives long-running, cross-context business
processes. ADRs 0019–0022 defined the architecture; Slice 4.0 is the
first implementation slice, restricted to foundational infrastructure.

## Decision

The Workflow context is implemented under
``backend/contexts/workflow/`` using the same DDD pattern proven by
Identity / Registry / Evidence.

### 1. Aggregates

| Aggregate | File | Role |
| --- | --- | --- |
| ``WorkflowDefinition`` | ``domain/workflow_definition.py`` | Immutable, JSON-loaded state graph. |
| ``WorkflowInstance`` | ``domain/workflow_instance.py`` | Event-sourced live execution. |
| ``Task`` | ``domain/task.py`` | Assignable human work item. |
| ``Timer`` | ``domain/timer.py`` | Scheduled fire bound to an instance. |
| ``CompensationEntry`` | ``domain/compensation.py`` | Append-only saga rollback ledger. |

### 2. Engine API (``application/engine.py``)

* ``start_workflow(definition_name, initiator, payload, correlation_id)``
* ``apply_command(instance_id, command, actor, payload)``
* ``fire_timer(timer_id, actor)``
* ``cancel(instance_id, reason, actor)``
* ``suspend(instance_id, reason, actor)`` / ``reactivate(...)``
* ``replay(instance_id)`` — pure rebuild from outbox events.

### 3. Action vocabulary (the engine's DSL)

The DSL is intentionally tiny. New verbs require a new ADR.

| Verb | Effect | Slice 4.0 status |
| --- | --- | --- |
| ``emit_command`` | Audit + record intent to send command to another context. | Foundation scaffold (full implementation in Slice 4.5). |
| ``schedule_timer`` | Persist a Timer for later firing. | Implemented. |
| ``create_task`` | Persist a Task for assignment. | Implemented. |
| ``record_compensation`` | Append a compensation entry. | Implemented. |
| ``spawn`` | Hand-off to SagaComposer (sub-workflow). | Foundation scaffold (full fan-out in Slice 4.5). |

### 4. Authorization (PDP policies)

| Action | Required roles |
| --- | --- |
| ``workflow.instance.start`` | ``super_admin`` / ``compliance_officer`` / ``surveyor_general`` |
| ``workflow.instance.cancel`` | start roles + ``super_admin`` |
| ``workflow.instance.suspend`` / ``.reactivate`` | ``super_admin`` only |
| ``workflow.instance.read`` / ``.list`` | broad authenticated roles |
| ``workflow.task.claim`` / ``.complete`` | broad operational set |
| ``workflow.task.cancel`` | ``super_admin`` only |
| ``workflow.timer.fire`` / ``.cancel`` | ``super_admin`` only |
| ``workflow.timer.read`` / ``.list`` | broad authenticated roles |
| ``workflow.admin.replay`` / ``.fire_timer`` | ``super_admin`` only |

### 5. Definition load & cycle detection (RB-5 mitigation)

The ``FsDefinitionLoader`` reads
``contracts/v1/workflow_definitions/*.json`` at boot. The loader:

1. Validates structure via ``WorkflowDefinition.from_dict``.
2. Detects same-definition spawn cycles inside ``from_dict``.
3. Detects cross-definition spawn cycles after the full registry is
   loaded.

Malformed JSON or any cycle causes ``DefinitionError``; the engine
refuses to boot.

### 6. Replay determinism (constitutional gate C-19.3)

``WorkflowEngine.replay(instance_id)`` walks every DELIVERED outbox
event whose ``aggregate_id == instance_id`` and feeds them through the
pure ``replay_apply(state, event_type, payload)`` function. The
resulting state is byte-identical to the committed state — proven by
the binding ``test_replay_byte_identical`` test.

### 7. Projection (foundation read model)

A single projection — ``workflow.instance`` v1 — maintains
``workflow_instance_read_model``. Constitutional rules from ADR-0010
apply unchanged: no business logic, no aggregate mutation, idempotent
on replay.

### 8. Mongo collections introduced

* ``workflow_instances``
* ``workflow_tasks``
* ``workflow_timers``
* ``workflow_compensation_log``
* ``workflow_instance_read_model`` (projection)

No existing Phase 3 collection is touched.

### 9. Contract bump

* VERSION: ``1.5.0 → 2.0.0`` (major; first non-additive bump).
* 15 new events (``workflow.*``) registered in the outbox + contract.
* 5 new request DTOs + 9 new response DTOs frozen.
* 17 new authorization actions registered.
* New artifact family: ``v1/workflow_definitions/*.json``.

### 10. What Slice 4.0 explicitly does NOT do

* No consent capture (deferred — Slice 4.2 / ADR-0020).
* No community validation / SG review / attestation (Slice 4.3 / ADR-0021).
* No inheritance / share calculation / court orders (Slice 4.4 / ADR-0022).
* No real ``emit_command`` outbound envelopes to Registry / Evidence
  (Slice 4.5).
* No saga ``for_each`` fan-out execution (Slice 4.5).
* No SDK / React UI (Slice 4.6).

## Consequences

Positive:

* The constitutional skeleton is now in place — future business slices
  add JSON content and small adapters; no engine changes expected.
* Phase 3 codebase remains untouched; backward compatibility preserved.
* Replay byte-identical determinism is proven by a binding test.

Negative:

* The ``emit_command`` and ``spawn`` verbs are scaffolds in 4.0 — they
  record audit intents but do not yet emit cross-context envelopes.
  This must be unblocked in Slice 4.5.
* New ``workflow_*`` collections are introduced; operators must include
  them in backup policies (already covered by the existing global
  Mongo backup per RUNBOOK §6).

## Acceptance gate (Slice 4.0)

* All workflow constitutional tests green.
* Replay byte-identical test green.
* Contract drift gate green at v2.0.0.
* PEP enforcement on every endpoint.
* No leak of consent / community / inheritance code in the slice.

## End of ADR-0023
