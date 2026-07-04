"""Phase 4 Slice 4.1 — Workflow Engine Completion: binding tests.

Acceptance gates (Operator Key 2 directive §7):
* Policy Engine: mayTransition, requiredRoles, requiredEvidence,
  requiredConsensus, timeout, escalation, retry.
* Command Dispatcher: real emit_command envelope, retry, DLQ.
* Child Spawner: real spawn fan-out + parent-child registry.
* Compensation Executor: reverse-order execution with verb handlers;
  triggered by cancel(reason='saga_failed').
* SLA Engine: schedules timers on state entry per policy; advances
  escalation chain on timer fire.
* Notification Dispatcher: retry + DLQ; provider abstraction; no PII
  in delivery log.
* Deterministic replay: definition with policy + spawn + emit_command
  + compensation replays byte-identical from the outbox.
* Contract stability: VERSION 2.0.0 unchanged; drift gate GREEN.
* Bounded-context isolation preserved.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from contexts.workflow.adapters.definition_loader import (
    InMemoryDefinitionLoader,
)
from contexts.workflow.adapters.mongo_repositories import (
    MongoCompensationRepository,
    MongoTaskRepository,
    MongoTimerRepository,
    MongoWorkflowInstanceRepository,
)
from contexts.workflow.adapters.slice41_repositories import (
    MongoChildRegistry,
    MongoCommandOutbox,
    MongoNotificationLog,
)
from contexts.workflow.application.child_spawner import ChildSpawner
from contexts.workflow.application.command_dispatcher import (
    CommandDispatcher,
    NullCommandHandler,
)
from contexts.workflow.application.compensation_executor import (
    CompensationExecutor,
)
from contexts.workflow.application.engine import WorkflowEngine
from contexts.workflow.application.notification_dispatcher import (
    FailingStubProvider,
    LogProvider,
    NotificationDispatcher,
)
from contexts.workflow.application.policy_engine import (
    InMemoryPolicyRegistry,
    PolicyEngine,
)
from contexts.workflow.application.saga_composer import SagaComposer
from contexts.workflow.application.sla_engine import SlaEngine
from contexts.workflow.domain.command_envelope import CommandStatus
from contexts.workflow.domain.compensation import CompensationEntry
from contexts.workflow.domain.notification import DeliveryStatus
from contexts.workflow.domain.policy import (
    RetryPolicy,
    StateSlaRule,
    TransitionRule,
    WorkflowPolicy,
)
from contexts.workflow.domain.timer import Timer
from contexts.workflow.domain.value_objects import InstanceState, TimerState
from contexts.workflow.domain.workflow_definition import WorkflowDefinition
from contexts.workflow.domain.workflow_instance import WorkflowInstance
from kernel.persistence.context import ExecutionContext, set_context

API_URL_INTERNAL = "http://localhost:8001"


# ============================================================================
# Fixtures — isolated per-test Mongo namespaces
# ============================================================================

@pytest_asyncio.fixture
async def engine_bundle():
    """Fresh Motor client bound to the same DB the app uses; every
    collection is namespaced by a fresh uuid so tests are independent.

    Yields a dict of the wired engine + all Slice 4.1 services.
    """
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    prefix = f"t41_{uuid.uuid4().hex[:8]}_"

    class _NS:
        def __init__(self, real, coll: str):
            self._real = real
            self._coll = coll
            self.collection = real[prefix + coll]

    # Instantiate repos against namespaced collections by monkey-patching
    # the ``collection`` attribute AFTER construction.
    instances = MongoWorkflowInstanceRepository(db)
    instances.collection = db[prefix + "workflow_instances"]
    tasks = MongoTaskRepository(db)
    tasks.collection = db[prefix + "workflow_tasks"]
    timers = MongoTimerRepository(db)
    timers.collection = db[prefix + "workflow_timers"]
    compensations = MongoCompensationRepository(db)
    compensations.collection = db[prefix + "workflow_compensations"]
    command_outbox = MongoCommandOutbox(db)
    command_outbox.collection = db[prefix + "workflow_command_outbox"]
    child_registry = MongoChildRegistry(db)
    child_registry.collection = db[prefix + "workflow_children"]
    notification_log = MongoNotificationLog(db)
    notification_log.collection = db[prefix + "workflow_notifications"]

    await instances.ensure_indexes()
    await tasks.ensure_indexes()
    await timers.ensure_indexes()
    await compensations.ensure_indexes()
    await command_outbox.ensure_indexes()
    await child_registry.ensure_indexes()
    await notification_log.ensure_indexes()

    # Empty in-memory loader — tests inject definitions per case.
    loader = InMemoryDefinitionLoader([])

    policy_registry = InMemoryPolicyRegistry()
    policy_engine = PolicyEngine(policy_registry)
    dispatcher_handler = NullCommandHandler()
    dispatcher = CommandDispatcher(outbox=command_outbox,
                                     handler=dispatcher_handler)
    spawner = ChildSpawner(definitions=loader, registry=child_registry)
    compensator = CompensationExecutor(repository=compensations,
                                         dispatcher=dispatcher)
    sla = SlaEngine(policy_engine=policy_engine, timers=timers)
    notif = NotificationDispatcher(log=notification_log)
    notif.register_provider(LogProvider())

    engine = WorkflowEngine(
        client=client, db=db,
        instances=instances, tasks=tasks, timers=timers,
        compensations=compensations,
        definitions=loader,
        saga=SagaComposer(loader),
        policy_engine=policy_engine,
        command_dispatcher=dispatcher,
        child_spawner=spawner,
        compensation_executor=compensator,
        sla_engine=sla,
    )

    # Push a super_admin context so scoped queries return rows.
    ctx = ExecutionContext(principal_id="test_admin",
                             roles=("super_admin",),
                             tenant_id="t1", country="NG")
    token = set_context(ctx)

    yield {
        "client": client, "db": db,
        "engine": engine,
        "instances": instances, "tasks": tasks, "timers": timers,
        "compensations": compensations,
        "command_outbox": command_outbox,
        "child_registry": child_registry,
        "notification_log": notification_log,
        "loader": loader,
        "policy_registry": policy_registry,
        "policy_engine": policy_engine,
        "dispatcher": dispatcher,
        "dispatcher_handler": dispatcher_handler,
        "spawner": spawner,
        "compensator": compensator,
        "sla": sla,
        "notif": notif,
        "prefix": prefix,
    }

    # Cleanup
    from kernel.persistence.context import reset_context
    reset_context(token)
    for coll in [instances.collection, tasks.collection,
                 timers.collection, compensations.collection,
                 command_outbox.collection, child_registry.collection,
                 notification_log.collection]:
        await coll.drop()
    client.close()


def _demo_defn_doc(name: str = "demo41.v1", version: int = 1) -> dict:
    """A definition exercising every Slice 4.1 primitive:
    - schedule_timer
    - emit_command (real dispatch)
    - record_compensation
    - a spawn state that lands on entry
    """
    return {
        "name": name, "version": version,
        "description": "Slice 4.1 demo: policy + spawn + emit + compensation",
        "initial_state": "started",
        "states": {
            "started": {"on_enter": [
                {"verb": "record_compensation",
                 "params": {"verb": "record_audit",
                             "payload": {"message": "step-1"}}},
            ]},
            "dispatched": {"on_enter": [
                {"verb": "emit_command",
                 "params": {"target": "registry",
                             "command": "note_something",
                             "payload": {"note": "demo"}}},
                {"verb": "record_compensation",
                 "params": {"verb": "emit_command",
                             "payload": {"target": "registry",
                                          "command": "undo_note",
                                          "payload": {"note": "demo"}}}},
            ]},
            "fanned": {"on_enter": [
                {"verb": "spawn",
                 "params": {"definition": "child41.v1",
                             "for_each": [{"key": "a"},
                                             {"key": "b"}],
                             "join_on_terminal": True}},
            ]},
            "done": {"terminal": True, "on_enter": []},
        },
        "transitions": [
            {"from": "started", "command": "dispatch", "to": "dispatched"},
            {"from": "dispatched", "command": "fanout", "to": "fanned"},
            {"from": "fanned", "command": "finish", "to": "done"},
        ],
    }


def _child_defn_doc() -> dict:
    return {
        "name": "child41.v1", "version": 1,
        "initial_state": "start",
        "states": {"start": {"on_enter": []},
                     "end": {"terminal": True, "on_enter": []}},
        "transitions": [{"from": "start", "command": "finish", "to": "end"}],
    }


# ============================================================================
# 1. Policy engine
# ============================================================================

def test_policy_scope_specificity_ranking() -> None:
    global_pol = WorkflowPolicy(
        policy_id="p_global", workflow_name="w",
        workflow_version=None, country_code=None, tenant_id=None,
        version=1)
    country_pol = WorkflowPolicy(
        policy_id="p_ng", workflow_name="w",
        workflow_version=None, country_code="NG", tenant_id=None,
        version=1)
    tenant_pol = WorkflowPolicy(
        policy_id="p_tenant", workflow_name="w",
        workflow_version=None, country_code=None, tenant_id="t1",
        version=1)
    assert country_pol.scope_specificity() > global_pol.scope_specificity()
    assert tenant_pol.scope_specificity() > country_pol.scope_specificity()


def test_policy_engine_resolve_picks_most_specific() -> None:
    registry = InMemoryPolicyRegistry([
        WorkflowPolicy(policy_id="g", workflow_name="w",
                        workflow_version=None, country_code=None,
                        tenant_id=None, version=1),
        WorkflowPolicy(policy_id="ng", workflow_name="w",
                        workflow_version=None, country_code="NG",
                        tenant_id=None, version=1),
        WorkflowPolicy(policy_id="ng_t1", workflow_name="w",
                        workflow_version=None, country_code="NG",
                        tenant_id="t1", version=1),
    ])
    engine = PolicyEngine(registry)
    inst = WorkflowInstance(
        instance_id="wfi_1", definition_name="w", definition_version=1,
        tenant_id="t1", country_code="NG", initiator_id="u",
        created_at="2026-07-01T00:00:00+00:00", business_state="s")
    hit = engine.policy_for(inst)
    assert hit is not None and hit.policy_id == "ng_t1"


def test_policy_may_transition_denies_and_requires_roles() -> None:
    pol = WorkflowPolicy(
        policy_id="p", workflow_name="w", workflow_version=None,
        country_code=None, tenant_id=None, version=1,
        transition_rules=(
            TransitionRule(from_state="s0", command="go", allow=False),
            TransitionRule(from_state="s1", command="advance",
                             required_roles=("compliance_officer",)),
        ))
    engine = PolicyEngine(InMemoryPolicyRegistry([pol]))
    inst = WorkflowInstance(instance_id="wfi", definition_name="w",
                              definition_version=1, tenant_id="t",
                              country_code="NG", initiator_id="u",
                              created_at="x", business_state="s0")
    ok, why = engine.may_transition(instance=inst, command="go",
                                     actor_roles=frozenset({"super_admin"}))
    assert ok is False and "denies" in (why or "")
    inst.business_state = "s1"
    ok, why = engine.may_transition(instance=inst, command="advance",
                                     actor_roles=frozenset({"field_agent"}))
    assert ok is False and "requires" in (why or "")
    ok, _ = engine.may_transition(instance=inst, command="advance",
                                     actor_roles=frozenset(
                                         {"compliance_officer"}))
    assert ok is True


def test_retry_policy_backoff_is_deterministic() -> None:
    rp = RetryPolicy(initial_backoff_seconds=1, max_backoff_seconds=32,
                      backoff_multiplier=2.0, max_attempts=6)
    assert rp.backoff_for(1) == 1
    assert rp.backoff_for(2) == 2
    assert rp.backoff_for(3) == 4
    assert rp.backoff_for(4) == 8
    assert rp.backoff_for(6) == 32  # capped
    assert rp.backoff_for(50) == 32
    # Byte-identical across calls (replay determinism sanity).
    assert [rp.backoff_for(i) for i in range(1, 7)] == \
           [rp.backoff_for(i) for i in range(1, 7)]


# ============================================================================
# 2. Command dispatcher
# ============================================================================

@pytest.mark.asyncio
async def test_command_dispatcher_delivers_on_happy_path(engine_bundle):
    b = engine_bundle
    b["loader"]._by_qualified["demo41.v1@v1"] = WorkflowDefinition.from_dict(
        _demo_defn_doc())
    b["loader"]._latest_by_name["demo41.v1"] = \
        b["loader"]._by_qualified["demo41.v1@v1"]
    # Start workflow, transition to "dispatched" to trigger emit_command.
    inst = await b["engine"].start_workflow(
        definition_name="demo41.v1", initiator_id="u1",
        payload={}, tenant_id="t1", country_code="NG")
    await b["engine"].apply_command(instance_id=inst.instance_id,
                                       command="dispatch", actor="u1")
    envelopes = await b["command_outbox"].list_for_instance(inst.instance_id)
    assert len(envelopes) == 1
    assert envelopes[0].status == CommandStatus.PENDING.value
    processed = await b["dispatcher"].dispatch_once()
    assert processed == 1
    envelopes = await b["command_outbox"].list_for_instance(inst.instance_id)
    assert envelopes[0].status == CommandStatus.DELIVERED.value
    assert envelopes[0].attempts == 1
    assert b["dispatcher_handler"].calls == [
        ("registry", "note_something", {"note": "demo"})]


@pytest.mark.asyncio
async def test_command_dispatcher_retries_then_dlq(engine_bundle):
    b = engine_bundle
    b["loader"]._by_qualified["demo41.v1@v1"] = WorkflowDefinition.from_dict(
        _demo_defn_doc())
    b["loader"]._latest_by_name["demo41.v1"] = \
        b["loader"]._by_qualified["demo41.v1@v1"]
    # Fixed clock so backoff is deterministic.
    now = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
    ticks = {"n": 0}

    def clk():
        ticks["n"] += 1
        return now + timedelta(seconds=ticks["n"] * 3600)  # far past every retry
    b["dispatcher"]._clock = clk
    b["dispatcher"]._default_retry = RetryPolicy(
        max_attempts=3, initial_backoff_seconds=1,
        max_backoff_seconds=2, backoff_multiplier=2.0)
    # Force failure on every attempt.
    b["dispatcher_handler"].fail_all = True

    inst = await b["engine"].start_workflow(
        definition_name="demo41.v1", initiator_id="u1",
        payload={}, tenant_id="t1", country_code="NG")
    await b["engine"].apply_command(instance_id=inst.instance_id,
                                       command="dispatch", actor="u1")

    # dispatch_once with a very-far-future clock keeps the envelope eligible.
    for _ in range(5):
        await b["dispatcher"].dispatch_once()
    envelopes = await b["command_outbox"].list_for_instance(inst.instance_id)
    assert len(envelopes) == 1
    env = envelopes[0]
    assert env.status == CommandStatus.DEAD_LETTERED.value, env.to_state()
    assert env.attempts == 3
    dl = await b["command_outbox"].list_dead_lettered()
    assert env.command_id in {e.command_id for e in dl}


# ============================================================================
# 3. Child spawner (real spawn fan-out)
# ============================================================================

@pytest.mark.asyncio
async def test_child_spawner_fan_out(engine_bundle):
    b = engine_bundle
    b["loader"]._by_qualified["demo41.v1@v1"] = WorkflowDefinition.from_dict(
        _demo_defn_doc())
    b["loader"]._latest_by_name["demo41.v1"] = \
        b["loader"]._by_qualified["demo41.v1@v1"]
    b["loader"]._by_qualified["child41.v1@v1"] = WorkflowDefinition.from_dict(
        _child_defn_doc())
    b["loader"]._latest_by_name["child41.v1"] = \
        b["loader"]._by_qualified["child41.v1@v1"]
    parent = await b["engine"].start_workflow(
        definition_name="demo41.v1", initiator_id="u1",
        tenant_id="t1", country_code="NG")
    await b["engine"].apply_command(instance_id=parent.instance_id,
                                       command="dispatch", actor="u1")
    await b["engine"].apply_command(instance_id=parent.instance_id,
                                       command="fanout", actor="u1")
    children = await b["child_registry"].list_children(parent.instance_id)
    assert len(children) == 2
    keys = sorted(c.key for c in children)
    assert keys == ["a", "b"]
    # Each child is a real WorkflowInstance in the store.
    for link in children:
        child_inst = await b["instances"].get(link.child_instance_id)
        assert child_inst is not None
        assert child_inst.definition_name == "child41.v1"
        assert child_inst.correlation_id.endswith("::" + link.key)


# ============================================================================
# 4. Compensation executor
# ============================================================================

@pytest.mark.asyncio
async def test_compensation_executor_reverse_order(engine_bundle):
    b = engine_bundle
    b["loader"]._by_qualified["demo41.v1@v1"] = WorkflowDefinition.from_dict(
        _demo_defn_doc())
    b["loader"]._latest_by_name["demo41.v1"] = \
        b["loader"]._by_qualified["demo41.v1@v1"]
    inst = await b["engine"].start_workflow(
        definition_name="demo41.v1", initiator_id="u1",
        tenant_id="t1", country_code="NG")
    await b["engine"].apply_command(instance_id=inst.instance_id,
                                       command="dispatch", actor="u1")
    # We should have TWO compensation entries recorded:
    # step-1 (record_audit) and undo_note (emit_command).
    comps = await b["compensations"].list_for_instance(inst.instance_id)
    assert len(comps) == 2
    verbs_in_order = [c.verb for c in comps]
    assert verbs_in_order == ["record_audit", "emit_command"]
    # Cancel with saga_failed reason → executor runs compensations in
    # reverse order (LIFO). We spy by installing a recording verb.
    executed: list[str] = []
    original_emit = b["compensator"]._verb_handlers["emit_command"]
    original_audit = b["compensator"]._verb_handlers["record_audit"]

    async def spy_emit(payload, instance, actor):
        executed.append("emit")
        await original_emit(payload, instance, actor)

    async def spy_audit(payload, instance, actor):
        executed.append("audit")
        await original_audit(payload, instance, actor)

    b["compensator"].register_verb("emit_command", spy_emit)
    b["compensator"].register_verb("record_audit", spy_audit)

    await b["engine"].cancel(instance_id=inst.instance_id, actor="u1",
                                reason="saga_failed:test")
    assert executed == ["emit", "audit"]  # reversed


# ============================================================================
# 5. Notification dispatcher (retry + DLQ + no PII)
# ============================================================================

@pytest.mark.asyncio
async def test_notification_delivery_no_pii(engine_bundle):
    b = engine_bundle
    delivery = await b["notif"].enqueue(
        channel="inbox", provider_id="log",
        address="alice@example.com", subject_ref="test-subject",
        payload={"body": "Sensitive PII here"},
        tenant_id="t1", country_code="NG")
    # Raw address MUST NOT be persisted.
    doc = await b["notification_log"].collection.find_one(
        {"delivery_id": delivery.delivery_id})
    assert "alice@example.com" not in str(doc)
    assert doc["address_hash"].startswith("addr_")
    processed = await b["notif"].dispatch_once()
    assert processed == 1
    doc = await b["notification_log"].collection.find_one(
        {"delivery_id": delivery.delivery_id})
    assert doc["status"] == DeliveryStatus.DELIVERED.value


@pytest.mark.asyncio
async def test_notification_retry_then_dlq(engine_bundle):
    b = engine_bundle
    fail = FailingStubProvider()
    b["notif"].register_provider(fail)  # displaces default inbox provider
    # Advance clock deterministically past every retry backoff.
    now = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
    ticks = {"n": 0}

    def clk():
        ticks["n"] += 1
        return now + timedelta(hours=ticks["n"])
    b["notif"]._clock = clk

    delivery = await b["notif"].enqueue(
        channel="inbox", provider_id="fail_stub",
        address="x@y.z", subject_ref="s",
        payload={}, tenant_id="t1", country_code="NG",
        max_attempts=3)
    for _ in range(5):
        await b["notif"].dispatch_once()
    doc = await b["notification_log"].collection.find_one(
        {"delivery_id": delivery.delivery_id})
    assert doc["status"] == DeliveryStatus.DEAD_LETTERED.value
    assert doc["attempts"] == 3


# ============================================================================
# 6. SLA engine — schedule on state entry + chain advance
# ============================================================================

@pytest.mark.asyncio
async def test_sla_engine_schedules_timer_on_state_entry(engine_bundle):
    b = engine_bundle
    # Definition with two plain states.
    doc = {"name": "sla_demo.v1", "version": 1,
           "initial_state": "waiting",
           "states": {"waiting": {"on_enter": []},
                        "escalated": {"on_enter": []}},
           "transitions": [{"from": "waiting", "command": "escalate",
                              "to": "escalated"}]}
    defn = WorkflowDefinition.from_dict(doc)
    b["loader"]._by_qualified[defn.qualified_name()] = defn
    b["loader"]._latest_by_name[defn.name] = defn
    b["policy_registry"].add(WorkflowPolicy(
        policy_id="sla_p", workflow_name=defn.name,
        workflow_version=None, country_code=None, tenant_id=None,
        version=1,
        sla_rules=(StateSlaRule(state="waiting",
                                  timeout_seconds=60,
                                  escalation_command="escalate"),)))
    inst = await b["engine"].start_workflow(
        definition_name=defn.name, initiator_id="u1",
        tenant_id="t1", country_code="NG")
    # One SLA timer should be scheduled.
    timers_docs = [t async for t in b["timers"].collection.find(
        {"instance_id": inst.instance_id})]
    assert len(timers_docs) == 1
    assert timers_docs[0]["command_on_fire"] == "escalate"
    assert timers_docs[0]["payload_on_fire"]["_sla_state"] == "waiting"


# ============================================================================
# 7. Deterministic replay (byte-identical rebuild through engine primitives)
# ============================================================================

@pytest.mark.asyncio
async def test_slice41_replay_byte_identical_via_httpx() -> None:
    """Constitutional gate C-19.3 remains: replay rebuild MUST equal
    committed state after Slice 4.1 additions.

    Uses the production HTTP surface + echo.v1 (which now runs under
    Slice 4.1 wiring) to confirm end-to-end replay determinism.
    """
    email = f"wf41_admin_{uuid.uuid4().hex[:10]}@test.landvault"
    password = "TestPassword123!"
    async with httpx.AsyncClient(base_url=API_URL_INTERNAL,
                                    timeout=15) as cli:
        r = await cli.post("/api/v1/auth/register",
                             json={"email": email, "password": password,
                                    "full_name": "WF 4.1 Admin"})
        assert r.status_code in (200, 201), r.text
    motor = AsyncIOMotorClient(
        os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    await motor.identity_users.update_one(
        {"email": email},
        {"$set": {"roles": ["super_admin"], "role": "super_admin"},
         "$inc": {"version": 1}})
    async with httpx.AsyncClient(base_url=API_URL_INTERNAL,
                                    timeout=15) as cli:
        r = await cli.post("/api/v1/auth/login",
                             json={"email": email, "password": password})
        tok = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {tok}"}
        r = await cli.post("/api/v1/workflow/instances",
                             json={"definition_name": "echo.v1",
                                    "payload": {"replay": True}},
                             headers=headers)
        assert r.status_code == 201, r.text
        instance_id = r.json()["instance_id"]
        # Let outbox publisher deliver.
        await asyncio.sleep(2.5)
        r = await cli.post(
            f"/api/v1/workflow/admin/instances/{instance_id}/replay",
            headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["matches_committed"] is True
        assert body["business_state"] == "received"
        assert body["lifecycle"] == "running"


# ============================================================================
# 8. Contract stability + bounded-context isolation
# ============================================================================

def test_slice41_contract_version_unchanged() -> None:
    """Slice 4.1 MUST NOT change /app/contracts/VERSION (Operator §5).
    Any bump requires explicit approval."""
    with open("/app/contracts/VERSION", "r", encoding="utf-8") as fp:
        assert fp.read().strip() == "2.0.0"


def test_slice41_no_new_public_event_types() -> None:
    """The engine's canonical Phase 4 event list is FROZEN at Slice 4.0.

    Slice 4.1 uses only these existing event types. New event_types on
    this list would violate Operator §5 (no new public events without
    explicit approval).
    """
    from contexts.workflow.domain import events as evmod
    expected = {
        "workflow.instance.started",
        "workflow.instance.transitioned",
        "workflow.instance.completed",
        "workflow.instance.cancelled",
        "workflow.instance.suspended",
        "workflow.instance.reactivated",
        "workflow.task.created",
        "workflow.task.claimed",
        "workflow.task.completed",
        "workflow.task.cancelled",
        "workflow.task.expired",
        "workflow.timer.scheduled",
        "workflow.timer.fired",
        "workflow.timer.cancelled",
        "workflow.compensation.recorded",
    }
    assert set(evmod.WORKFLOW_EVENT_TYPES) == expected, \
        "Slice 4.1 must not introduce new event_types"


def test_slice41_no_cross_context_references() -> None:
    """Slice 4.1 modules MUST NOT import from other bounded contexts."""
    import inspect

    from contexts.workflow.application import (
        child_spawner,
        command_dispatcher,
        compensation_executor,
        notification_dispatcher,
        policy_engine,
        sla_engine,
    )
    from contexts.workflow.domain import (
        child_link,
        command_envelope,
        notification,
        policy,
    )
    from contexts.workflow.adapters import slice41_repositories

    forbidden = ("contexts.evidence", "contexts.registry",
                 "contexts.identity",
                 "evidence_items", "evidence_seals", "evidence_locks",
                 "registry_landvaults")
    modules = [child_spawner, command_dispatcher, compensation_executor,
                notification_dispatcher, policy_engine, sla_engine,
                child_link, command_envelope, notification, policy,
                slice41_repositories]
    for mod in modules:
        src = inspect.getsource(mod)
        for tok in forbidden:
            assert tok not in src, (
                f"{mod.__name__} illegally references {tok!r} — "
                "bounded-context isolation breach")


def test_slice41_contract_drift_gate_green() -> None:
    """The drift gate must remain GREEN throughout Slice 4.1."""
    import subprocess
    result = subprocess.run(
        ["python", "-m", "contracts.generate", "--check"],
        cwd="/app", capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, \
        f"drift gate FAILED: {result.stdout}\n{result.stderr}"
    assert "no drift" in result.stdout.lower()
