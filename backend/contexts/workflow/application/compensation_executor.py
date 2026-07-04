"""CompensationExecutor — real saga compensation (Phase 4 — Slice 4.1).

Iterates a workflow instance's recorded compensations in reverse order
and executes the corresponding compensator verb. Slice 4.0 only
*recorded* compensations. Slice 4.1 adds *execution*.

Verb catalogue (generic — no business logic):
* ``noop`` — no-op; records that the step was walked (default).
* ``emit_command`` — enqueue a corrective CommandEnvelope
  ``params = {target: ..., command: ..., payload: ...}``.
* ``record_audit`` — write an audit trail entry
  ``params = {message: ...}``.

The executor NEVER deletes data; sagas emit corrective events, they
do NOT roll back state (constitutional guarantee).
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable, Optional

from contexts.workflow.adapters.mongo_repositories import (
    MongoCompensationRepository,
)
from contexts.workflow.application.command_dispatcher import CommandDispatcher
from contexts.workflow.domain.compensation import CompensationEntry
from contexts.workflow.domain.workflow_instance import WorkflowInstance
from kernel.audit import audit
from kernel.observability.metrics import increment

logger = logging.getLogger("contexts.workflow.compensation_executor")


class CompensationExecutor:

    def __init__(self, *, repository: MongoCompensationRepository,
                 dispatcher: Optional[CommandDispatcher] = None) -> None:
        self._repo = repository
        self._dispatcher = dispatcher
        self._verb_handlers: dict[str,
                                    Callable[[dict, WorkflowInstance,
                                              str],
                                             Awaitable[None]]] = {
            "noop": self._verb_noop,
            "emit_command": self._verb_emit_command,
            "record_audit": self._verb_record_audit,
        }

    def register_verb(self, verb: str,
                      handler: Callable[[dict, WorkflowInstance,
                                          str], Awaitable[None]]) -> None:
        self._verb_handlers[verb] = handler

    async def execute_all_for(self, *, instance: WorkflowInstance,
                              actor: str,
                              reason: str) -> list[CompensationEntry]:
        entries = await self._repo.list_for_instance(instance.instance_id)
        # Execute in REVERSE (LIFO) — a saga compensates its most-recent
        # step first.
        for entry in reversed(entries):
            handler = self._verb_handlers.get(entry.verb, self._verb_unknown)
            try:
                await handler(entry.payload, instance, actor)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "compensation verb=%s FAILED for instance=%s: %s",
                    entry.verb, instance.instance_id, exc)
                await audit(action="workflow.compensation.failed",
                             resource_type="workflow_compensation",
                             resource_id=entry.compensation_id,
                             decision="PERMIT",
                             payload={"error": str(exc),
                                      "verb": entry.verb,
                                      "reason": reason})
                await increment("workflow_compensation_failed",
                                  labels={"verb": entry.verb})
                continue
            await audit(action="workflow.compensation.executed",
                         resource_type="workflow_compensation",
                         resource_id=entry.compensation_id,
                         decision="PERMIT",
                         payload={"verb": entry.verb,
                                  "instance_id": instance.instance_id,
                                  "reason": reason})
            await increment("workflow_compensation_executed",
                              labels={"verb": entry.verb})
        return entries

    # ---- verb handlers ---------------------------------------------

    async def _verb_noop(self, payload: dict, instance: WorkflowInstance,
                          actor: str) -> None:
        return

    async def _verb_emit_command(self, payload: dict,
                                   instance: WorkflowInstance,
                                   actor: str) -> None:
        if self._dispatcher is None:
            logger.warning(
                "compensation emit_command: no CommandDispatcher wired")
            return
        target = payload.get("target")
        cmd = payload.get("command")
        if not (isinstance(target, str) and isinstance(cmd, str)):
            raise ValueError(
                "compensation emit_command requires payload.target + "
                "payload.command")
        await self._dispatcher.enqueue(
            instance=instance, target_context=target,
            command_name=cmd, payload=payload.get("payload") or {})

    async def _verb_record_audit(self, payload: dict,
                                   instance: WorkflowInstance,
                                   actor: str) -> None:
        message = payload.get("message") or "compensation record_audit"
        await audit(action="workflow.compensation.record_audit",
                     resource_type="workflow_instance",
                     resource_id=instance.instance_id,
                     decision="PERMIT",
                     payload={"message": str(message)})

    async def _verb_unknown(self, payload: dict,
                              instance: WorkflowInstance,
                              actor: str) -> None:
        raise ValueError(
            f"compensation verb not registered: "
            f"instance={instance.instance_id} payload={payload!r}")
