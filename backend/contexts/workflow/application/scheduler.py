"""Workflow background scheduler (Phase 4 — Slice 4.1).

A single async loop that periodically:

1. Fires any workflow timers whose ``fire_at <= now`` (SLA timers,
   escalation timers, definition-declared timers). Applies the timer's
   ``command_on_fire`` to the bound instance.
2. Advances SLA escalation chains after an SLA timer fires.
3. Runs ``CommandDispatcher.dispatch_once`` to attempt outbound
   command delivery (with retry + DLQ).
4. Runs ``NotificationDispatcher.dispatch_once`` to attempt
   notification delivery (with retry + DLQ).

The scheduler is idempotent and safe to interleave with foreground
traffic (all Mongo writes use optimistic concurrency).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from contexts.workflow.adapters.mongo_repositories import MongoTimerRepository
from contexts.workflow.application.command_dispatcher import CommandDispatcher
from contexts.workflow.application.engine import WorkflowEngine
from contexts.workflow.application.notification_dispatcher import (
    NotificationDispatcher,
)
from contexts.workflow.application.sla_engine import SlaEngine
from contexts.workflow.domain.value_objects import TimerState
from kernel.observability.metrics import increment
from kernel.persistence.context import ExecutionContext

logger = logging.getLogger("contexts.workflow.scheduler")


class WorkflowScheduler:
    """One background loop per process."""

    def __init__(self, *, engine: WorkflowEngine,
                 timers: MongoTimerRepository,
                 sla: Optional[SlaEngine] = None,
                 commands: Optional[CommandDispatcher] = None,
                 notifications: Optional[NotificationDispatcher] = None,
                 tick_seconds: float = 1.0,
                 clock: Optional[Callable[[], datetime]] = None) -> None:
        self._engine = engine
        self._timers = timers
        self._sla = sla
        self._commands = commands
        self._notifications = notifications
        self._tick_seconds = tick_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(),
                                           name="workflow-scheduler")

    async def stop(self) -> None:
        if not self.running():
            return
        self._stop.set()
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except asyncio.TimeoutError:
            self._task.cancel()
        self._task = None

    async def _loop(self) -> None:
        logger.info("WorkflowScheduler loop started (tick=%.2fs)",
                     self._tick_seconds)
        while not self._stop.is_set():
            try:
                await self.tick_once()
            except Exception as exc:  # noqa: BLE001
                logger.exception("scheduler tick error: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(),
                                        timeout=self._tick_seconds)
            except asyncio.TimeoutError:
                pass
        logger.info("WorkflowScheduler loop stopped")

    async def tick_once(self) -> dict:
        """One iteration; returns per-subsystem processed counts."""
        results = {"timers": 0, "commands": 0, "notifications": 0}
        # ---- Timers -----------------------------------------------------
        results["timers"] = await self._fire_due_timers()
        # ---- Command outbox --------------------------------------------
        if self._commands is not None:
            results["commands"] = await self._commands.dispatch_once()
        # ---- Notification outbox ---------------------------------------
        if self._notifications is not None:
            results["notifications"] = await \
                self._notifications.dispatch_once()
        return results

    async def _fire_due_timers(self, batch_size: int = 25) -> int:
        now_iso = self._clock().isoformat()
        # Direct query — must bypass tenant scoping (system context).
        # We use a super_admin execution context for the scheduler.
        cur = self._timers.collection.find(
            {"state": TimerState.SCHEDULED.value,
             "fire_at": {"$lte": now_iso}},
            {"_id": 0}).sort("fire_at", 1).limit(batch_size)
        fired = 0
        async for doc in cur:
            timer_id = doc.get("timer_id")
            if not timer_id:
                continue
            # Enter a super_admin system context for the timer fire.
            token = _push_system_context(tenant_id=doc.get("tenant_id"),
                                          country=doc.get("country_code"))
            try:
                await self._engine.fire_timer(timer_id=timer_id,
                                                actor="__scheduler__")
                fired += 1
                await increment("workflow_scheduler_timer_fired")
                # Advance SLA chain if this was an SLA-bound timer.
                if (self._sla is not None
                        and (doc.get("payload_on_fire") or {})
                        .get("_sla_state") is not None):
                    # Re-load fired timer + instance to allow chain
                    # advancement (its fire has already been persisted).
                    from contexts.workflow.domain.timer import Timer
                    fired_timer = Timer.from_state(doc)
                    fired_timer.state = TimerState.FIRED.value
                    instance = await self._engine._instances.get(
                        fired_timer.instance_id)
                    if instance is not None:
                        await self._sla.maybe_advance_chain(
                            fired_timer=fired_timer, instance=instance,
                            actor="__scheduler__",
                            publish_event=self._engine._publish_event)
            except Exception as exc:  # noqa: BLE001
                logger.warning("timer fire failed timer_id=%s: %s",
                                timer_id, exc)
            finally:
                _pop_system_context(token)
        return fired


# ---------------------------------------------------------------------------
# System-context helpers
# ---------------------------------------------------------------------------

def _push_system_context(*, tenant_id: Optional[str],
                          country: Optional[str]):
    """Push a super_admin ExecutionContext for scheduler-driven work.

    Scheduler code must bypass ordinary tenant scoping to load timers /
    apply commands across tenants; we do that by installing a
    ``super_admin`` role in the current context. This is *not* a
    privilege escalation — the scheduler NEVER exposes an endpoint.
    """
    from kernel.persistence.context import set_context
    ctx = ExecutionContext(
        principal_id="__scheduler__",
        roles=("super_admin",),
        tenant_id=tenant_id, country=country,
        correlation_id=f"scheduler::{tenant_id}::{country}")
    return set_context(ctx)


def _pop_system_context(token) -> None:
    from kernel.persistence.context import reset_context
    if token is not None:
        reset_context(token)
