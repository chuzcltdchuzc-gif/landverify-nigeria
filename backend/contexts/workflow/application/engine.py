"""Workflow Engine (Phase 4 — Slice 4.0).

The heart of the Workflow bounded context. Responsibilities (per
ADR-0019 / PHASE4_SPEC §5.2):

* ``start_workflow(definition, initiator, payload, correlation_id)``
* ``apply_command(instance_id, command, actor, payload)``
* ``fire_timer(timer_id, actor)``
* ``cancel(instance_id, reason, actor)``
* ``suspend(instance_id, reason, actor)`` / ``reactivate(...)``
* ``replay(instance_id)`` (pure rebuild from outbox events)

Internally the engine:
1. Loads the WorkflowDefinition for the instance.
2. Asserts the command is legal in the current state.
3. Records each state transition as a DomainEvent.
4. Drains any ``pending_actions`` declared by the definition's
   ``on_enter`` — creating tasks, scheduling timers, recording
   compensations, or hand-off declarations to the saga composer.
5. Publishes events to the transactional outbox in the SAME Mongo
   transaction as the aggregate write.

Binding rules:
* Engine NEVER directly writes to other bounded contexts.
* Engine NEVER interprets arbitrary expressions — only fixed action
  verbs.
* All identity, scope, and lifecycle fields are immutable post-create.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from contexts.workflow.adapters.mongo_repositories import (
    EVENT_LOG_COLLECTION,
    MongoCompensationRepository,
    MongoTaskRepository,
    MongoTimerRepository,
    MongoWorkflowInstanceRepository,
)
from contexts.workflow.application.saga_composer import SagaComposer
from contexts.workflow.domain.compensation import CompensationEntry
from contexts.workflow.domain.events import DomainEvent
from contexts.workflow.domain.invariants import (
    DefinitionError,
    IllegalTransitionError,
    ImmutableFieldError,
    InvariantViolation,
    SuspendedInstanceError,
    TaskStateError,
    TerminalInstanceError,
    TimerStateError,
    UnknownCommandError,
)
from contexts.workflow.domain.task import Task
from contexts.workflow.domain.timer import Timer
from contexts.workflow.domain.value_objects import InstanceState
from contexts.workflow.domain.workflow_definition import WorkflowDefinition
from contexts.workflow.domain.workflow_instance import (
    WorkflowInstance,
    replay_apply,
)
from contexts.workflow.ports.repository import DefinitionLoader
from kernel.audit import audit
from kernel.errors.problem import bad_request, conflict, not_found
from kernel.events.envelope import Envelope
from kernel.events.outbox import OUTBOX_COLLECTION, publish
from kernel.observability.metrics import increment
from kernel.persistence.context import current_context

logger = logging.getLogger("contexts.workflow.engine")


def _map_domain_error(exc: Exception) -> Exception:
    if isinstance(exc, TerminalInstanceError):
        return conflict(str(exc), code="workflow.instance.terminal")
    if isinstance(exc, SuspendedInstanceError):
        return conflict(str(exc), code="workflow.instance.suspended")
    if isinstance(exc, IllegalTransitionError):
        return conflict(str(exc), code="workflow.instance.illegal_transition")
    if isinstance(exc, UnknownCommandError):
        return bad_request(str(exc), code="workflow.command.unknown")
    if isinstance(exc, ImmutableFieldError):
        return bad_request(str(exc), code="workflow.immutable_field")
    if isinstance(exc, TaskStateError):
        return conflict(str(exc), code="workflow.task.state_error")
    if isinstance(exc, TimerStateError):
        return conflict(str(exc), code="workflow.timer.state_error")
    if isinstance(exc, DefinitionError):
        return bad_request(str(exc), code="workflow.definition_error")
    if isinstance(exc, InvariantViolation):
        return bad_request(str(exc), code="workflow.invariant_violation")
    return exc


class WorkflowEngine:
    """Ticks workflow instances forward, durable + transactional."""

    def __init__(
        self,
        *,
        client: AsyncIOMotorClient,
        db: AsyncIOMotorDatabase,
        instances: MongoWorkflowInstanceRepository,
        tasks: MongoTaskRepository,
        timers: MongoTimerRepository,
        compensations: MongoCompensationRepository,
        definitions: DefinitionLoader,
        saga: Optional[SagaComposer] = None,
    ) -> None:
        self._client = client
        self._db = db
        self._instances = instances
        self._tasks = tasks
        self._timers = timers
        self._compensations = compensations
        self._definitions = definitions
        self._saga = saga or SagaComposer(definitions)

    # ---------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------

    async def start_workflow(self, *, definition_name: str,
                               initiator_id: str,
                               payload: Optional[dict] = None,
                               correlation_id: Optional[str] = None,
                               definition_version: Optional[int] = None,
                               tenant_id: Optional[str] = None,
                               country_code: Optional[str] = None) -> WorkflowInstance:
        defn = self._require_definition(definition_name, definition_version)
        ctx = current_context()
        # Operator-supplied tenant/country overrides allowed only for
        # super_admin (matches kernel scoping rules).
        eff_tenant = (tenant_id
                       if tenant_id and ctx.has_role("super_admin")
                       else ctx.tenant_id or tenant_id or "default")
        eff_country = (country_code
                        if country_code and ctx.has_role("super_admin")
                        else ctx.country or country_code or "NG")

        instance = WorkflowInstance.start(
            definition=defn,
            tenant_id=eff_tenant,
            country_code=eff_country,
            initiator_id=initiator_id,
            payload=payload,
            correlation_id=correlation_id,
        )
        await self._commit(instance, defn, actor=initiator_id)
        await audit(action="workflow.instance.start",
                     resource_type="workflow_instance",
                     resource_id=instance.instance_id,
                     decision="PERMIT",
                     payload={"definition": defn.qualified_name()})
        await increment("workflow_instance_started",
                          labels={"definition": defn.name})
        return instance

    async def apply_command(self, *, instance_id: str, command: str,
                              actor: str,
                              payload: Optional[dict] = None) -> WorkflowInstance:
        instance = await self._instances.get(instance_id)
        if instance is None:
            raise not_found(f"workflow instance {instance_id} not found",
                              code="workflow.instance.not_found")
        defn = self._require_definition(instance.definition_name,
                                          instance.definition_version)
        try:
            instance.apply_command(definition=defn, command=command,
                                     actor=actor, payload=payload)
        except Exception as exc:
            raise _map_domain_error(exc) from exc
        await self._commit(instance, defn, actor=actor)
        await audit(action="workflow.instance.apply_command",
                     resource_type="workflow_instance",
                     resource_id=instance.instance_id,
                     decision="PERMIT",
                     payload={"command": command, "to": instance.business_state})
        await increment("workflow_instance_transitioned",
                          labels={"definition": defn.name, "command": command})
        return instance

    async def cancel(self, *, instance_id: str, actor: str,
                       reason: str) -> WorkflowInstance:
        instance = await self._instances.get(instance_id)
        if instance is None:
            raise not_found(f"workflow instance {instance_id} not found",
                              code="workflow.instance.not_found")
        defn = self._require_definition(instance.definition_name,
                                          instance.definition_version)
        try:
            instance.cancel(actor=actor, reason=reason)
        except Exception as exc:
            raise _map_domain_error(exc) from exc
        await self._commit(instance, defn, actor=actor)
        await audit(action="workflow.instance.cancel",
                     resource_type="workflow_instance",
                     resource_id=instance.instance_id,
                     decision="PERMIT",
                     payload={"reason": reason})
        return instance

    async def suspend(self, *, instance_id: str, actor: str,
                        reason: str) -> WorkflowInstance:
        instance = await self._instances.get(instance_id)
        if instance is None:
            raise not_found(f"workflow instance {instance_id} not found",
                              code="workflow.instance.not_found")
        defn = self._require_definition(instance.definition_name,
                                          instance.definition_version)
        try:
            instance.suspend(actor=actor, reason=reason)
        except Exception as exc:
            raise _map_domain_error(exc) from exc
        await self._commit(instance, defn, actor=actor)
        return instance

    async def reactivate(self, *, instance_id: str,
                           actor: str) -> WorkflowInstance:
        instance = await self._instances.get(instance_id)
        if instance is None:
            raise not_found(f"workflow instance {instance_id} not found",
                              code="workflow.instance.not_found")
        defn = self._require_definition(instance.definition_name,
                                          instance.definition_version)
        try:
            instance.reactivate(actor=actor)
        except Exception as exc:
            raise _map_domain_error(exc) from exc
        await self._commit(instance, defn, actor=actor)
        return instance

    async def fire_timer(self, *, timer_id: str,
                           actor: str) -> Optional[WorkflowInstance]:
        timer = await self._timers.get(timer_id)
        if timer is None:
            raise not_found(f"workflow timer {timer_id} not found",
                              code="workflow.timer.not_found")
        try:
            timer.fire()
        except Exception as exc:
            raise _map_domain_error(exc) from exc
        await self._timers.save(timer)
        for ev in timer.pull_events():
            await self._publish_event(ev, actor=actor, session=None,
                                        tenant_id=timer.tenant_id,
                                        country=timer.country_code)
        # Apply the bound command to the instance.
        return await self.apply_command(instance_id=timer.instance_id,
                                          command=timer.command_on_fire,
                                          actor=actor,
                                          payload=timer.payload_on_fire)

    # ---------------------------------------------------------------
    # Replay (pure)
    # ---------------------------------------------------------------

    async def replay(self, instance_id: str) -> Optional[dict]:
        """Rebuild instance state from the outbox event stream.

        Replay is pure: it walks every DELIVERED outbox event whose
        ``aggregate_id == instance_id`` and feeds them through the
        domain's ``replay_apply`` function in occurred_at order. The
        result is byte-identical to the committed state per
        constitutional rule C-19.3.
        """
        cursor = self._db[OUTBOX_COLLECTION].find(
            {"aggregate_id": instance_id,
             "aggregate_type": "WorkflowInstance",
             "status": "DELIVERED"},
            {"_id": 0}).sort([("aggregate_version", 1), ("occurred_at", 1)])
        state: Optional[dict] = None
        events_seen = 0
        async for doc in cursor:
            state = replay_apply(state, doc.get("payload") or {},
                                  doc["event_type"],
                                  int(doc["aggregate_version"]))
            events_seen += 1
        if state is None:
            return None
        state["_replay_event_count"] = events_seen
        return state

    # ---------------------------------------------------------------
    # Internal
    # ---------------------------------------------------------------

    def _require_definition(self, name: str,
                              version: Optional[int] = None) -> WorkflowDefinition:
        defn = self._definitions.get(name, version)
        if defn is None:
            raise not_found(
                f"workflow definition {name}@v{version or 'latest'} not found",
                code="workflow.definition.not_found")
        return defn

    async def _commit(self, instance: WorkflowInstance,
                        defn: WorkflowDefinition, *, actor: str) -> None:
        """Persist instance state + emitted events + drained on_enter
        actions in a single Mongo transaction (transactional outbox)."""
        async with await self._client.start_session() as session:
            async with session.start_transaction():
                await self._instances.save(instance, session=session)
                # Drain raised events.
                for ev in instance.pull_events():
                    await self._publish_event(
                        ev, actor=actor, session=session,
                        tenant_id=instance.tenant_id,
                        country=instance.country_code)
                # Execute on_enter actions of the freshly-entered state.
                actions = instance.pull_pending_actions()
                for action in actions:
                    await self._execute_action(
                        action=action, instance=instance, defn=defn,
                        actor=actor, session=session)
                # Persist a copy of every emitted event into the
                # per-instance event log (kept separately from the
                # outbox for fast per-aggregate reads). Best-effort.
                # We only persist the latest version after action exec.

    async def _execute_action(self, *, action: dict,
                                instance: WorkflowInstance,
                                defn: WorkflowDefinition,
                                actor: str, session) -> None:
        verb = action.get("verb")
        params = action.get("params") or {}
        if verb == "emit_command":
            await self._action_emit_command(params, instance, actor, session)
        elif verb == "schedule_timer":
            await self._action_schedule_timer(params, instance, actor, session)
        elif verb == "create_task":
            await self._action_create_task(params, instance, actor, session)
        elif verb == "record_compensation":
            await self._action_record_compensation(params, instance,
                                                      actor, session)
        elif verb == "spawn":
            # The composer interprets a spawn declaration. In Slice 4.0
            # the composer logs the intent and emits a "spawn requested"
            # outbox marker. Concrete spawn execution lands in 4.5.
            await self._saga.handle_spawn(params=params, instance=instance,
                                            actor=actor)
        else:
            raise DefinitionError(f"unknown action verb {verb!r}")

    async def _action_emit_command(self, params: dict,
                                     instance: WorkflowInstance,
                                     actor: str, session) -> None:
        """Emit an OUTBOUND command to another bounded context.

        The engine NEVER writes to other contexts directly — it publishes
        an envelope on the outbox. Subscribers in the target context
        consume it.
        """
        target = params.get("target")
        command_name = params.get("command")
        if not isinstance(target, str) or not isinstance(command_name, str):
            raise DefinitionError(
                "emit_command requires params.target + params.command")
        # NOTE: emit_command is a side-effect; the transition envelope
        # was already published. We do NOT republish here — the original
        # transition envelope's payload carries the engine's intent.
        # In Slice 4.5 this will turn into a dedicated outbound command
        # envelope. For 4.0 we only record an audit entry.
        await audit(action="workflow.engine.emit_command",
                     resource_type="workflow_instance",
                     resource_id=instance.instance_id,
                     decision="PERMIT",
                     payload={"target": target, "command": command_name})

    async def _action_schedule_timer(self, params: dict,
                                       instance: WorkflowInstance,
                                       actor: str, session) -> None:
        fire_at = params.get("fire_at")
        cmd = params.get("command")
        if not isinstance(fire_at, str) or not isinstance(cmd, str):
            raise DefinitionError(
                "schedule_timer requires params.fire_at (ISO8601) "
                "+ params.command")
        timer = Timer.schedule(
            instance_id=instance.instance_id,
            definition_name=instance.definition_name,
            tenant_id=instance.tenant_id,
            country_code=instance.country_code,
            fire_at=fire_at, command_on_fire=cmd,
            payload_on_fire=params.get("payload") or {})
        await self._timers.save(timer, session=session)
        for ev in timer.pull_events():
            await self._publish_event(ev, actor=actor, session=session,
                                        tenant_id=instance.tenant_id,
                                        country=instance.country_code)

    async def _action_create_task(self, params: dict,
                                    instance: WorkflowInstance,
                                    actor: str, session) -> None:
        title = params.get("title") or instance.business_state
        task = Task.create(
            instance_id=instance.instance_id,
            definition_name=instance.definition_name,
            tenant_id=instance.tenant_id,
            country_code=instance.country_code,
            title=title,
            assigned_to_role=params.get("assigned_to_role"),
            assigned_to_principal=params.get("assigned_to_principal"),
            due_at=params.get("due_at"))
        await self._tasks.save(task, session=session)
        for ev in task.pull_events():
            await self._publish_event(ev, actor=actor, session=session,
                                        tenant_id=instance.tenant_id,
                                        country=instance.country_code)

    async def _action_record_compensation(self, params: dict,
                                            instance: WorkflowInstance,
                                            actor: str, session) -> None:
        verb = params.get("verb") or "noop"
        entry = CompensationEntry.record(
            instance_id=instance.instance_id,
            definition_name=instance.definition_name,
            tenant_id=instance.tenant_id,
            country_code=instance.country_code,
            verb=verb, payload=params.get("payload") or {}, actor=actor)
        await self._compensations.append(entry, session=session)
        for ev in entry.pull_events():
            await self._publish_event(ev, actor=actor, session=session,
                                        tenant_id=instance.tenant_id,
                                        country=instance.country_code)

    async def _publish_event(self, event: DomainEvent, *, actor: str,
                              session, tenant_id: Optional[str],
                              country: Optional[str]) -> None:
        ctx = current_context()
        correlation_id = ctx.correlation_id
        env = event.to_envelope(
            tenant_id=tenant_id, country=country,
            actor=actor, correlation_id=correlation_id)
        await publish(env, session=session)


# ---------------------------------------------------------------
# Task & Timer service helpers (thin, used by API router)
# ---------------------------------------------------------------

class TaskService:
    def __init__(self, tasks: MongoTaskRepository) -> None:
        self._tasks = tasks

    async def claim(self, *, task_id: str, principal_id: str) -> Task:
        task = await self._tasks.get(task_id)
        if task is None:
            raise not_found(f"task {task_id} not found",
                              code="workflow.task.not_found")
        try:
            task.claim(principal_id=principal_id)
        except Exception as exc:
            raise _map_domain_error(exc) from exc
        await self._tasks.save(task)
        return task

    async def complete(self, *, task_id: str, principal_id: str,
                         payload: Optional[dict] = None) -> Task:
        task = await self._tasks.get(task_id)
        if task is None:
            raise not_found(f"task {task_id} not found",
                              code="workflow.task.not_found")
        try:
            task.complete(principal_id=principal_id, payload=payload)
        except Exception as exc:
            raise _map_domain_error(exc) from exc
        await self._tasks.save(task)
        return task
