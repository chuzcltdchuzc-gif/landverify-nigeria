"""CommandDispatcher — real ``emit_command`` execution (Phase 4 — Slice 4.1).

Replaces the Slice 4.0 audit-only stub with a durable, retriable outbox
of outbound engine commands. Each call to ``enqueue`` inserts a
CommandEnvelope in the SAME Mongo transaction as the workflow state
write. A background dispatch loop (see ``scheduler.py``) later calls
``dispatch_once`` to attempt delivery via a registered handler.

Constitutional rules:
* The engine NEVER writes to another bounded context directly. The
  dispatcher publishes envelopes onto our own collection; downstream
  contexts pull them (a future slice will register handlers).
* Retry is deterministic (exponential backoff from RetryPolicy;
  no jitter — replay-safe).
* On exhaustion, the envelope moves to ``dead_lettered`` and stays
  there for operator inspection.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

from contexts.workflow.adapters.slice41_repositories import MongoCommandOutbox
from contexts.workflow.domain.command_envelope import (
    CommandEnvelope,
    CommandStatus,
)
from contexts.workflow.domain.policy import RetryPolicy
from contexts.workflow.domain.workflow_instance import WorkflowInstance
from kernel.audit import audit
from kernel.observability.metrics import increment

logger = logging.getLogger("contexts.workflow.command_dispatcher")

# Signature: async fn(target_context, command_name, payload) -> None
# Raise Exception to force retry / DLQ.
CommandHandler = Callable[[str, str, dict], Awaitable[None]]


class NullCommandHandler:
    """No-op handler used when no downstream context has registered.

    Slice 4.1 delivers the *infrastructure* (queue + retry + DLQ). Real
    downstream handlers land in later business slices. Until then this
    handler simply marks the delivery as SUCCESSFUL, so the queue does
    not grow unbounded on smoke traffic. Set ``fail_all=True`` to
    simulate downstream failure in tests.
    """

    def __init__(self, fail_all: bool = False,
                 fail_matching: Optional[Callable[[str, str, dict], bool]] = None
                 ) -> None:
        self.fail_all = fail_all
        self.fail_matching = fail_matching
        self.calls: list[tuple[str, str, dict]] = []

    async def __call__(self, target: str, command: str, payload: dict) -> None:
        self.calls.append((target, command, dict(payload)))
        if self.fail_all:
            raise RuntimeError(
                "NullCommandHandler forced failure (test mode)")
        if self.fail_matching and self.fail_matching(target, command, payload):
            raise RuntimeError(
                f"NullCommandHandler forced failure for "
                f"{target}.{command}")


class CommandDispatcher:
    """Enqueue + attempt delivery for CommandEnvelopes."""

    def __init__(self, *, outbox: MongoCommandOutbox,
                 handler: Optional[CommandHandler] = None,
                 default_retry: Optional[RetryPolicy] = None,
                 clock: Optional[Callable[[], datetime]] = None) -> None:
        self._outbox = outbox
        self._handler = handler or NullCommandHandler()
        self._default_retry = default_retry or RetryPolicy()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def set_handler(self, handler: CommandHandler) -> None:
        self._handler = handler

    async def enqueue(self, *, instance: WorkflowInstance,
                      target_context: str, command_name: str,
                      payload: Optional[dict] = None,
                      retry_policy: Optional[RetryPolicy] = None,
                      session=None) -> CommandEnvelope:
        rp = retry_policy or self._default_retry
        envelope = CommandEnvelope.create(
            instance_id=instance.instance_id,
            definition_name=instance.definition_name,
            tenant_id=instance.tenant_id,
            country_code=instance.country_code,
            target_context=target_context,
            command_name=command_name,
            payload=payload,
            max_attempts=rp.max_attempts)
        await self._outbox.save(envelope, session=session)
        await audit(action="workflow.command.enqueued",
                     resource_type="workflow_command_envelope",
                     resource_id=envelope.command_id,
                     decision="PERMIT",
                     payload={"instance_id": instance.instance_id,
                              "target": target_context,
                              "command": command_name})
        await increment("workflow_command_enqueued",
                          labels={"target": target_context,
                                  "command": command_name})
        return envelope

    async def dispatch_once(self, *,
                            retry_policy: Optional[RetryPolicy] = None,
                            batch_size: int = 25) -> int:
        """Attempt delivery for one batch of ready envelopes.

        Returns the number of envelopes processed. Deterministic per
        wall-clock ``now`` argument (via ``self._clock``).
        """
        rp = retry_policy or self._default_retry
        now = self._clock()
        batch = await self._outbox.claim_next_batch(
            now_iso=now.isoformat(), limit=batch_size)
        processed = 0
        for envelope in batch:
            envelope.mark_in_flight()
            await self._outbox.save(envelope)
            try:
                await self._handler(envelope.target_context,
                                     envelope.command_name,
                                     envelope.payload)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "command dispatch failed target=%s command=%s "
                    "instance=%s attempts=%d/%d error=%s",
                    envelope.target_context, envelope.command_name,
                    envelope.instance_id, envelope.attempts + 1,
                    envelope.max_attempts, exc)
                backoff = rp.backoff_for(envelope.attempts + 1)
                next_at = (now + timedelta(seconds=backoff)).isoformat()
                envelope.mark_failed(error=str(exc), next_attempt_at=next_at)
                await self._outbox.save(envelope)
                if envelope.status == CommandStatus.DEAD_LETTERED.value:
                    await increment("workflow_command_dead_lettered",
                                      labels={"target": envelope.target_context,
                                              "command": envelope.command_name})
                    await audit(
                        action="workflow.command.dead_lettered",
                        resource_type="workflow_command_envelope",
                        resource_id=envelope.command_id,
                        decision="PERMIT",
                        payload={"error": str(exc),
                                 "attempts": envelope.attempts,
                                 "target": envelope.target_context,
                                 "command": envelope.command_name})
                else:
                    await increment("workflow_command_retry",
                                      labels={"target": envelope.target_context,
                                              "command": envelope.command_name})
            else:
                envelope.mark_delivered()
                await self._outbox.save(envelope)
                await increment("workflow_command_delivered",
                                  labels={"target": envelope.target_context,
                                          "command": envelope.command_name})
                await audit(action="workflow.command.delivered",
                             resource_type="workflow_command_envelope",
                             resource_id=envelope.command_id,
                             decision="PERMIT",
                             payload={"target": envelope.target_context,
                                      "command": envelope.command_name})
            processed += 1
        return processed
