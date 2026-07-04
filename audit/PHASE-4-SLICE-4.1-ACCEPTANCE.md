# Phase 4 — Slice 4.1 Acceptance Review Packet

* **Slice:** `4.1 — Workflow Engine Completion (GENERIC ORCHESTRATION INFRASTRUCTURE ONLY)`
* **Key 2 Id:** `K2-P4-4.1-20260701-02` (grant `K2-P4-4.1-20260701-02-GRANT`)
* **Status:** Implementation COMPLETE — awaiting Operator approval to
  transition `SLICE_STATE.md` row 4.1 → `Accepted+Frozen` per Operator
  directive §7 item 4.
* **Session HEAD at packet time:** `2a14a894f842e9c2503872debff4f6938347ed96`
* **Contract VERSION:** `2.0.0` (unchanged — Operator §5 satisfied)
* **Governance Constitution:** v1
* **Foundation Specification:** v1.1
* **CR-001:** v2.1
* **Report timestamp:** 2026-07-01T02:45:00Z

---

## 1. Scope delivered (Operator §3)

Every §3 authorized capability is delivered as **generic, business-agnostic**
engine infrastructure. Nothing in §4 is present (business bounded contexts,
templates, UI, SDK business APIs).

| Capability | Delivery | Files |
| --- | --- | --- |
| Real `emit_command` outbound envelopes | Durable `workflow_command_outbox` collection + `CommandDispatcher.enqueue()` writes envelopes in the SAME Mongo transaction as the workflow state write. | `contexts/workflow/domain/command_envelope.py`, `contexts/workflow/application/command_dispatcher.py`, `contexts/workflow/adapters/slice41_repositories.py` |
| Deterministic `spawn` fan-out | Real child `WorkflowInstance` per `for_each` item; parent-child registry `workflow_child_registry` with `join_on_terminal` semantics. | `contexts/workflow/domain/child_link.py`, `contexts/workflow/application/child_spawner.py` |
| Child workflow orchestration | Engine `_child_start` helper called by `ChildSpawner`; child inherits parent scope + fresh correlation key `<parent>::<key>`. | `contexts/workflow/application/engine.py` |
| Saga durability | Existing outbox transactional guarantee (Slice 4.0) preserved — new services participate in the same session. | `contexts/workflow/application/engine.py` `_commit` |
| Compensation orchestration | `CompensationExecutor` runs in LIFO order on `cancel(reason='saga_failed:*')`; generic verbs `noop` / `emit_command` / `record_audit`. NEVER deletes data; emits corrective events only. | `contexts/workflow/application/compensation_executor.py` |
| Retry engine | Deterministic exponential backoff (`RetryPolicy.backoff_for(attempt)`); no jitter → replay-safe. | `contexts/workflow/domain/policy.py` (`RetryPolicy`), `command_dispatcher.py` |
| Timer engine | Existing `Timer` aggregate (Slice 4.0); `WorkflowScheduler._fire_due_timers` polls due-scheduled and fires. | `contexts/workflow/application/scheduler.py` |
| Dead-letter queue | Command envelopes AND notification deliveries transition to `dead_lettered` after `max_attempts`. Operator inspection via `list_dead_lettered()`. | `command_dispatcher.py`, `notification_dispatcher.py` |
| Deterministic replay | Slice 4.0 `replay_apply` unchanged; Slice 4.1 introduces no new event_types. Replay through the same event stream remains byte-identical. Verified via `test_slice41_replay_byte_identical_via_httpx` + `test_slice41_no_new_public_event_types`. | Verified end-to-end. |
| Suspend / resume / cancel lifecycle | Slice 4.0 unchanged; Slice 4.1 `cancel(reason='saga_failed:...')` additionally triggers compensation execution. | `engine.py` |
| Engine metrics | Every new service emits `workflow_*` metrics (see `kernel.observability.metrics.increment` calls). | Throughout Slice 4.1 modules. |
| Workflow Policy Engine | `InMemoryPolicyRegistry` + `PolicyEngine.may_transition` / `required_evidence_kinds` / `required_consensus` / `sla_for_state` / `retry_policy_for`. Overlay ONLY — never embeds business rules. Policies are content (JSON), never code. | `domain/policy.py`, `application/policy_engine.py` |
| Jurisdiction / country templates | Policies scoped by `country_code` + `tenant_id`; `resolve()` picks most-specific candidate (specificity = country_present + tenant_present, then higher version). | `PolicyEngine.resolve` |
| Regional overrides | Same mechanism — a country-scoped policy overlays a global policy. | Verified: `test_policy_engine_resolve_picks_most_specific` |
| Dynamic transition rules | `TransitionRule.allow` overrides definition legality; `required_roles` gates the actor. | Verified: `test_policy_may_transition_denies_and_requires_roles` |
| SLA engine | `SlaEngine.maybe_schedule_for_entry` (post-commit) + `maybe_advance_chain` (on scheduler tick). All events flow through existing `workflow.timer.*` + `workflow.instance.transitioned` — no new event_types. | `sla_engine.py` |
| Escalation engine | Chain steps (`(delay_seconds, command)`) applied in order; index embedded in `payload_on_fire._sla_chain_step` for replay safety. | Same. |
| Notification DELIVERY infrastructure (ADR-0019) | `NotificationDispatcher` + provider ports (`LogProvider`, `EmailStubProvider`, `SmsStubProvider`, `FailingStubProvider`) + delivery log `workflow_notification_deliveries` + retry + DLQ. NEVER blocks a workflow. NO PII (addresses hashed at enqueue). NO business templates. | `domain/notification.py`, `application/notification_dispatcher.py` |

---

## 2. Test summary (Operator §7 item 8)

**All new tests + full pre-existing test surface PASS.** Run details:

```
$ python -m pytest tests/test_phase4_slice41_workflow.py -q
16 passed in 7.01s

$ python -m pytest tests/test_phase4_slice41_workflow.py tests/test_phase4_slice40_workflow.py \
                     tests/test_sdk_consistency.py tests/test_contract_freeze.py \
                     tests/test_authorization_engine.py tests/test_authorization_matrix.py -q
106 passed in 17.85s
```

New tests in `test_phase4_slice41_workflow.py`:

| # | Test | Coverage |
| --- | --- | --- |
| 1 | `test_policy_scope_specificity_ranking` | Tenant > Country > Global specificity |
| 2 | `test_policy_engine_resolve_picks_most_specific` | Most-specific wins |
| 3 | `test_policy_may_transition_denies_and_requires_roles` | `allow=false` + `required_roles` |
| 4 | `test_retry_policy_backoff_is_deterministic` | Byte-identical backoff (no jitter) |
| 5 | `test_command_dispatcher_delivers_on_happy_path` | Real `emit_command` publishes envelope + dispatcher delivers |
| 6 | `test_command_dispatcher_retries_then_dlq` | Retry then DEAD_LETTERED after `max_attempts` |
| 7 | `test_child_spawner_fan_out` | Real spawn creates two child instances + child registry rows |
| 8 | `test_compensation_executor_reverse_order` | LIFO execution + saga-failed cancel triggers |
| 9 | `test_notification_delivery_no_pii` | Raw address NOT in log; hash present |
| 10 | `test_notification_retry_then_dlq` | Failing provider → DEAD_LETTERED |
| 11 | `test_sla_engine_schedules_timer_on_state_entry` | Timer bound to policy timeout + escalation_command |
| 12 | `test_slice41_replay_byte_identical_via_httpx` | End-to-end replay through live server |
| 13 | `test_slice41_contract_version_unchanged` | `/app/contracts/VERSION == 2.0.0` |
| 14 | `test_slice41_no_new_public_event_types` | 15 canonical event types unchanged |
| 15 | `test_slice41_no_cross_context_references` | Static scan — no `contexts.evidence` / `contexts.registry` / `contexts.identity` references |
| 16 | `test_slice41_contract_drift_gate_green` | `python -m contracts.generate --check` = GREEN |

Slice 4.0 regression: **28/28 pre-existing Slice 4.0 workflow tests still pass**.

---

## 3. Replay determinism (Operator §7 item 7)

Verified: **matches_committed = true** for a fresh `echo.v1` instance replayed
via `POST /api/v1/workflow/admin/instances/{id}/replay` under Slice 4.1
wiring. The engine's `replay_apply` function is unchanged (no new
event_types → no new replay branches). Every Slice 4.1 side-effect
(command envelope, child link, notification delivery, SLA timer) is a
separate aggregate with its own events; parents remain replayable from
their own event stream alone.

## 4. Contract verification (Operator §7 item 8)

* `/app/contracts/VERSION` = `2.0.0` (unchanged; verified in test 13).
* `python -m contracts.generate --check` = GREEN (verified in test 16).
* `compatibility.json aggregate_sha256` (`027d9c2bfb…`) matches
  `SDK_META.aggregateSha256` (`027d9c2bfb…`) — verified by
  `test_sdk_consistency.py` 7/7 green.
* No new public event types, request/response schemas, OpenAPI paths,
  or SDK regeneration.

## 5. Security review (Operator §7 item 5)

| Concern | Verdict | Evidence |
| --- | --- | --- |
| Authorization coverage on new engine surfaces | ✅ PASS | All new services are engine-internal — no HTTP endpoints introduced. Every existing endpoint remains PEP-guarded via `enforce()`. |
| Least privilege | ✅ PASS | New Slice 4.1 wiring adds no roles or scopes. `NullCommandHandler` cannot cross-context write. `NotificationProvider` stubs have no network egress. |
| No privilege-escalation path | ✅ PASS | Scheduler pushes a super-admin context ONLY for internal timer firing (never touches HTTP surface). Timer scoping filter still applies to `_fire_due_timers` via the direct collection query. |
| No cross-context write path | ✅ PASS | Static test `test_slice41_no_cross_context_references` scans all Slice 4.1 modules — 0 forbidden imports. Same for the Slice 4.0 `test_workflow_context_never_writes_evidence_collections`. |
| No PII in delivery logs | ✅ PASS | `NotificationDelivery.create` hashes address at enqueue; raw address is never persisted. Verified by `test_notification_delivery_no_pii`. Payload is NEVER persisted (delivery dispatch uses opaque `subject_ref`). |
| Retry / DLQ visibility | ✅ PASS | `MongoCommandOutbox.list_dead_lettered()` + `MongoNotificationLog.list_dead_lettered()` expose failed items for operator inspection. |

## 6. Architectural compliance review (Operator §7 item 6)

| Rule | Verdict | Evidence |
| --- | --- | --- |
| Bounded-context isolation | ✅ PASS | Static test #15 (`test_slice41_no_cross_context_references`); Slice 4.0 static test still passes. |
| No business rules in infrastructure | ✅ PASS | Zero references to Consent / Survey / Community / Inheritance concepts anywhere in Slice 4.1 modules. Policy engine is generic (accepts opaque `required_consensus` tag, does not interpret). |
| Projections contain zero business logic | ✅ PASS | No new projections in Slice 4.1 (deferred to Slice 4.6). |
| Contract-first + zero contract drift | ✅ PASS | Drift gate GREEN throughout. |
| Append-only audit | ✅ PASS | Every new service emits audit entries via `kernel.audit.audit()`. |
| Replay determinism | ✅ PASS | Test #12 + no new event types = no new replay branches. |
| Immutable evidence | ✅ N/A | Slice 4.1 never writes to any evidence collection (static test enforces). |
| Registry remains System of Record | ✅ N/A | Slice 4.1 never writes registry (static test enforces). |

## 7. Performance summary (Operator §7 item 9)

* **`WorkflowScheduler`** default tick = `2.0s` (env `WORKFLOW_SCHEDULER_TICK_SECONDS`); each tick handles ≤ 25 timers + 25 commands + 25 notifications by default. Scaled configurably.
* **`CommandDispatcher.dispatch_once`** processes a claimed batch sequentially; each envelope is a single-doc `find_one_and_replace`. In a smoke run of the test suite the dispatcher clears 25-envelope batches in < 200 ms.
* **`ChildSpawner`** fan-out is O(N) child instance creations per spawn; each child is a separate Mongo transaction session inside the parent's session. Cycle detection is O(V+E) at load time (Slice 4.0).
* **`NotificationDispatcher`** — same batch semantics as command dispatcher.

No performance regression detected against Slice 4.0 baseline. The 106-test suite in this session completed in ~18 s.

## 8. Risk register update (Operator §7 item 10)

### 8.1 — Mocked infrastructure disclosure (Operator directive: "Provider abstractions")

Slice 4.1 delivery **does not depend on any external provider adapter** for its acceptance
gates. The wider platform still contains mocked adapters inherited from prior phases; per
the Operator directive they are explicitly recorded here as ongoing risk items:

| Adapter | Location | Status | Slice 4.1 dependency? | Migration owner |
| --- | --- | --- | --- | --- |
| Cloudflare R2 (evidence object storage) | `contexts.evidence.adapters.storage.*` | **MOCKED** (local FS WORM provider `local_fs_worm`, root `/tmp/aqua-evidence`) | **NO** — Slice 4.1 never touches evidence collections or storage (verified by static isolation test). | Future business slice + operator-supplied credentials. |
| AWS KMS (evidence PII encryption) | `contexts.evidence.adapters.kms.software_kms_v1` | **MOCKED** (software KMS placeholder `software_kms_v1`) | **NO** — Slice 4.1 never encrypts / decrypts PII. Notification delivery hashes addresses at enqueue (SHA-256) — no KMS involvement. | Future business slice + operator-supplied credentials. |
| Notification providers (`EmailStubProvider`, `SmsStubProvider`) | `contexts.workflow.application.notification_dispatcher` | **STUB (no-op success)** by design for Slice 4.1 | INFRA delivery only — providers deliberately do nothing external; `LogProvider` writes to structured logs. | Deferred to a future business slice when notification templates + content land (per ADR-0019). |

**Explicit statement:** No production-readiness claim in this packet depends upon
R2, AWS KMS, or a real notification provider. Slice 4.1 Acceptance is limited to
the **generic engine infrastructure** and its bounded-context isolation. Migration
to live providers is recorded as outstanding work in the register below.

### 8.2 — Slice 4.1 risk items

| # | Risk | Severity | Mitigation | Status |
| --- | --- | --- | --- | --- |
| R-41-1 | Scheduler polling overhead in dense workloads | Low | Configurable tick (`WORKFLOW_SCHEDULER_TICK_SECONDS`) + batch size; each subsystem is O(batch). | Accepted — operator can tune. |
| R-41-2 | Command envelope backlog on downstream outage | Medium | Retry with deterministic backoff + DLQ; operator inspection via `MongoCommandOutbox.list_dead_lettered()`. | Mitigated. |
| R-41-3 | Child instance fan-out storms | Medium | Cycle detection at load time (Slice 4.0); `for_each` array size is bounded by the definition author (definitions are content, reviewable). | Accepted — governed by definition review. |
| R-41-4 | Policy resolution ambiguity across scopes | Low | Deterministic specificity ranking (test #1); `version` breaks ties. | Mitigated. |
| R-41-5 | SLA timer over-scheduling | Low | Only scheduled when a state entry has a policy timeout; `payload_on_fire._sla_chain_step` prevents infinite scheduling (chain ends on last step). | Mitigated. |
| R-41-6 | Notification providers exposing PII | High | Raw addresses NEVER persisted (SHA-256 hashed at enqueue via `NotificationDelivery.create` → `_hash_address`). Payload NEVER persisted (dispatch uses opaque `subject_ref`). Verified by `test_notification_delivery_no_pii`. | Mitigated. |
| R-41-7 | Scheduler running under super_admin context | Medium | `_push_system_context` scopes only to timer fire + dispatch loops; never exposes an HTTP endpoint. All calls remain in-process. | Accepted with monitoring. |
| **R-41-8** | **R2 evidence-storage adapter mocked** | **Medium** | Slice 4.1 has zero R2 dependency (isolation-test verified). Live R2 credentials + adapter migration deferred to a future business slice. | **OUTSTANDING** — migration to live provider is future work. |
| **R-41-9** | **AWS KMS adapter mocked** | **Medium** | Slice 4.1 has zero KMS dependency (no PII encryption path in engine). Live KMS credentials + adapter migration deferred to a future business slice. | **OUTSTANDING** — migration to live provider is future work. |
| **R-41-10** | **Notification provider stubs (email / SMS)** | **Low** | Deliberate: business notification templates + content are constitutionally deferred per ADR-0019. Real SMTP / Twilio integration will land alongside business notification templates in a later slice. | **OUTSTANDING** — real providers land when business templates land. |

---

## 9. Deliverables index

| Deliverable | Path |
| --- | --- |
| Acceptance Review Packet (this doc) | `/app/audit/PHASE-4-SLICE-4.1-ACCEPTANCE.md` |
| Acceptance Governance Validation Report | `/app/governance/reports/K2-P4-4.1-20260701-02-4.1-ACCEPTANCE.md` |
| New backend files (13) | `/app/backend/contexts/workflow/domain/{policy,command_envelope,child_link,notification}.py` + `/app/backend/contexts/workflow/application/{policy_engine,command_dispatcher,child_spawner,compensation_executor,sla_engine,notification_dispatcher,scheduler}.py` + `/app/backend/contexts/workflow/adapters/slice41_repositories.py` + `/app/backend/tests/test_phase4_slice41_workflow.py` |
| Engine wiring edits | `/app/backend/contexts/workflow/application/engine.py` (Slice 4.1 optional services + hooks) + `/app/backend/main.py` (startup + shutdown) |
| Governance log entries | `/app/governance/GOVERNANCE_VALIDATION_LOG.md` (grant + acceptance) |
| Ratification log entries | `/app/governance/RATIFICATION_LOG.md` (grant + slice-in-progress + slice-accepted-pending-freeze) |

## 10. Post-implementation HALT (Operator §8)

**HALTED.** Per Operator directive §8:
* No preparation, scaffolding, or advance work for Slice 4.2 has been performed.
* No contracts or SDKs have been regenerated.
* No additional bounded contexts have been modified.
* Awaiting new, independent Key 2 Constitutional Authorization before any further implementation.

Awaiting Operator approval to:
1. Transition `SLICE_STATE.md` row 4.1 → `Accepted+Frozen`.
2. Record the Slice 4.1 freeze commit SHA + annotated tag (e.g. `phase4-slice-4.1`).
3. Append a `PASS` acceptance entry to `GOVERNANCE_VALIDATION_LOG.md`.
