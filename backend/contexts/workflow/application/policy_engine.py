"""Workflow Policy Engine (Phase 4 — Slice 4.1).

Loads WorkflowPolicy documents from disk (JSON) and/or in-memory and
resolves the *most specific* policy applicable to a running workflow
instance. Provides the generic answers the engine needs:

* ``may_transition(instance, command, ctx)`` — combines definition
  legality with policy overlay (allow / required_roles).
* ``required_evidence_kinds(instance, command)`` — evidence kinds the
  actor must supply (returned to caller; the engine itself does NOT
  reach into the Evidence context).
* ``required_consensus(instance, command)`` — opaque consensus tag.
* ``timeout_for(instance, state)`` — SLA seconds bound to a state.
* ``escalation_for(instance, state)`` — first escalation step + chain.
* ``retry_policy_for(instance)`` — RetryPolicy governing dispatcher.

Nothing in this module knows *anything* about consent, survey,
community, or inheritance business rules. Those live in future slices.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from contexts.workflow.domain.invariants import DefinitionError
from contexts.workflow.domain.policy import (
    RetryPolicy,
    StateSlaRule,
    TransitionRule,
    WorkflowPolicy,
)
from contexts.workflow.domain.workflow_instance import WorkflowInstance

logger = logging.getLogger("contexts.workflow.policy_engine")


class InMemoryPolicyRegistry:
    """Holds all loaded policies + resolves best-fit at runtime."""

    def __init__(self, policies: Optional[list[WorkflowPolicy]] = None) -> None:
        self._policies: list[WorkflowPolicy] = list(policies or [])

    def add(self, policy: WorkflowPolicy) -> None:
        self._policies.append(policy)

    def load_dir(self, directory: Path) -> None:
        d = Path(directory)
        if not d.exists():
            logger.info("workflow policies dir absent: %s", d)
            return
        for path in sorted(d.glob("*.json")):
            with path.open("r", encoding="utf-8") as fp:
                try:
                    doc = json.load(fp)
                except json.JSONDecodeError as exc:
                    raise DefinitionError(
                        f"malformed policy JSON {path.name}: {exc}") from exc
            self._policies.append(WorkflowPolicy.from_dict(doc))
        logger.info("loaded %d workflow policy document(s) from %s",
                    len(self._policies), d)

    def list_policies(self) -> list[WorkflowPolicy]:
        return list(self._policies)

    def resolve(self, *, workflow_name: str, workflow_version: int,
                country_code: str, tenant_id: str) -> Optional[WorkflowPolicy]:
        candidates = [p for p in self._policies
                      if p.applies_to(workflow_name=workflow_name,
                                        workflow_version=workflow_version,
                                        country_code=country_code,
                                        tenant_id=tenant_id)]
        if not candidates:
            return None
        candidates.sort(
            key=lambda p: (p.scope_specificity(), p.version), reverse=True)
        return candidates[0]


class PolicyEngine:
    """Answers generic policy questions for the engine."""

    def __init__(self, registry: InMemoryPolicyRegistry) -> None:
        self._registry = registry

    def policy_for(self,
                   instance: WorkflowInstance) -> Optional[WorkflowPolicy]:
        return self._registry.resolve(
            workflow_name=instance.definition_name,
            workflow_version=instance.definition_version,
            country_code=instance.country_code,
            tenant_id=instance.tenant_id)

    # ---- Transition legality overlay ---------------------------------

    def may_transition(self, *, instance: WorkflowInstance,
                       command: str, actor_roles: frozenset[str]
                       ) -> tuple[bool, Optional[str]]:
        """Return (allow, reason_if_denied).

        This layer ONLY overlays the policy's ``allow`` flag +
        ``required_roles`` gate onto whatever the definition already
        permits. If no policy rule applies, the engine falls through to
        the definition's own legality (i.e. this method returns
        ``(True, None)``).
        """
        p = self.policy_for(instance)
        if p is None:
            return (True, None)
        rule = p.rule_for(instance.business_state, command)
        if rule is None:
            return (True, None)
        if rule.allow is False:
            return (False, f"policy {p.policy_id} denies {command!r} in "
                            f"state {instance.business_state!r}")
        if rule.required_roles:
            if not (actor_roles & set(rule.required_roles)):
                return (False, f"policy {p.policy_id} requires one of "
                                f"{sorted(rule.required_roles)}")
        return (True, None)

    def required_evidence_kinds(self, *, instance: WorkflowInstance,
                                command: str) -> tuple[str, ...]:
        p = self.policy_for(instance)
        if p is None:
            return ()
        r = p.rule_for(instance.business_state, command)
        return r.required_evidence_kinds if r else ()

    def required_consensus(self, *, instance: WorkflowInstance,
                           command: str) -> Optional[str]:
        p = self.policy_for(instance)
        if p is None:
            return None
        r = p.rule_for(instance.business_state, command)
        return r.required_consensus if r else None

    # ---- SLA + escalation --------------------------------------------

    def sla_for_state(self, *, instance: WorkflowInstance,
                      state: str) -> Optional[StateSlaRule]:
        p = self.policy_for(instance)
        if p is None:
            return None
        return p.sla_for(state)

    def retry_policy_for(self,
                         instance: WorkflowInstance) -> RetryPolicy:
        p = self.policy_for(instance)
        return p.retry_policy if p else RetryPolicy()
