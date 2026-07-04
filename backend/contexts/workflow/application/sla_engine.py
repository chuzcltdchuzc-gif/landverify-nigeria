"""SLA + Escalation engine (Phase 4 — Slice 4.1).

When a workflow instance enters a state that has a policy SLA rule
attached, the engine schedules an SLA timer (via the existing Timer
aggregate). On fire, the timer applies the policy's
``escalation_command`` (or the first step in ``escalation_chain``) to
the instance and — if a chain is present — schedules the next step's
timer.

No new event_types are introduced: every SLA event flows through the
existing ``workflow.timer.scheduled`` / ``workflow.timer.fired`` /
``workflow.instance.transitioned`` envelopes.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from contexts.workflow.adapters.mongo_repositories import MongoTimerRepository
from contexts.workflow.application.policy_engine import PolicyEngine
from contexts.workflow.domain.policy import StateSlaRule
from contexts.workflow.domain.timer import Timer
from contexts.workflow.domain.workflow_instance import WorkflowInstance
from kernel.observability.metrics import increment

logger = logging.getLogger("contexts.workflow.sla_engine")


class SlaEngine:
    """Schedules SLA / escalation timers driven by WorkflowPolicy."""

    def __init__(self, *, policy_engine: PolicyEngine,
                 timers: MongoTimerRepository,
                 clock: Optional[Callable[[], datetime]] = None) -> None:
        self._policy = policy_engine
        self._timers = timers
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def maybe_schedule_for_entry(self, *,
                                         instance: WorkflowInstance,
                                         actor: str,
                                         session=None,
                                         publish_event=None
                                         ) -> Optional[Timer]:
        """Called by the engine after a state transition (or initial
        state entry). If the entered state has an SLA rule, schedule a
        timer that fires with the escalation command.
        """
        sla = self._policy.sla_for_state(instance=instance,
                                          state=instance.business_state)
        if sla is None or sla.timeout_seconds is None:
            return None
        return await self._schedule(instance=instance, sla=sla,
                                     chain_index=0, actor=actor,
                                     session=session,
                                     publish_event=publish_event)

    async def maybe_advance_chain(self, *, fired_timer: Timer,
                                    instance: WorkflowInstance,
                                    actor: str,
                                    publish_event=None) -> Optional[Timer]:
        """After a fired escalation timer's command is applied, schedule
        the next chain step if one exists.

        We embed the chain_index in the timer's ``payload_on_fire`` so
        the follow-up scheduling is deterministic and replay-safe.
        """
        p = fired_timer.payload_on_fire or {}
        if p.get("_sla_chain_step") is None:
            return None
        chain_index = int(p["_sla_chain_step"])
        state = p.get("_sla_state")
        if not state:
            return None
        # Re-resolve policy at fire time — policies may have advanced.
        sla = self._policy.sla_for_state(instance=instance, state=state)
        if sla is None:
            return None
        next_index = chain_index + 1
        if next_index >= len(sla.escalation_chain):
            return None
        return await self._schedule(instance=instance, sla=sla,
                                     chain_index=next_index, actor=actor,
                                     session=None, publish_event=publish_event)

    async def _schedule(self, *, instance: WorkflowInstance,
                          sla: StateSlaRule, chain_index: int, actor: str,
                          session, publish_event) -> Timer:
        if chain_index == 0:
            delay = sla.timeout_seconds or 0
            command = sla.escalation_command or (
                sla.escalation_chain[0][1]
                if sla.escalation_chain else "sla_escalate")
        else:
            delay, command = sla.escalation_chain[chain_index - 1]
        fire_at = (self._clock() + timedelta(seconds=int(delay))).isoformat()
        timer = Timer.schedule(
            instance_id=instance.instance_id,
            definition_name=instance.definition_name,
            tenant_id=instance.tenant_id,
            country_code=instance.country_code,
            fire_at=fire_at, command_on_fire=command,
            payload_on_fire={"_sla_state": sla.state,
                              "_sla_chain_step": chain_index,
                              "_sla_actor": actor})
        await self._timers.save(timer, session=session)
        if publish_event is not None:
            for ev in timer.pull_events():
                await publish_event(ev, actor=actor, session=session,
                                     tenant_id=instance.tenant_id,
                                     country=instance.country_code)
        await increment("workflow_sla_scheduled",
                          labels={"state": sla.state,
                                  "step": str(chain_index)})
        logger.info(
            "SLA timer scheduled instance=%s state=%s step=%d "
            "fire_at=%s command=%s",
            instance.instance_id, sla.state, chain_index, fire_at, command)
        return timer
