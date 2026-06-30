"""Saga composer (Phase 4 — Slice 4.0).

Interprets the ``spawn`` action verb declared by workflow definitions.
In Slice 4.0 the composer is a scaffold: it validates the spawn
declaration against the loaded definition registry and records an
audit + metric. Concrete spawn execution (for_each fan-out + join
semantics) lands in Slice 4.5 once the consent/inheritance contexts are
present.

This module exists so that:
* Foundation tests can verify the engine integrates with a composer
  shape that won't change later.
* The cycle-detection logic enforced at load time has a runtime peer
  that refuses to spawn unloaded definitions.
"""
from __future__ import annotations

import logging
from typing import Optional

from contexts.workflow.domain.invariants import DefinitionError
from contexts.workflow.domain.workflow_definition import WorkflowDefinition
from contexts.workflow.domain.workflow_instance import WorkflowInstance
from contexts.workflow.ports.repository import DefinitionLoader
from kernel.audit import audit
from kernel.observability.metrics import increment

logger = logging.getLogger("contexts.workflow.saga_composer")


class SagaComposer:
    """Stateless interpreter of ``spawn`` declarations.

    Slice 4.0 implements the SHAPE only: validates the target
    definition is registered and audits the intent. Real fan-out
    execution arrives in Slice 4.5.
    """

    def __init__(self, definitions: DefinitionLoader) -> None:
        self._definitions = definitions

    async def handle_spawn(self, *, params: dict,
                             instance: WorkflowInstance,
                             actor: str) -> Optional[str]:
        target = params.get("definition")
        if not isinstance(target, str) or not target:
            raise DefinitionError(
                "spawn action requires params.definition (string)")
        # ``definition`` may be either ``name`` or ``name@vN``.
        name, _, version_str = target.partition("@")
        version = None
        if version_str.startswith("v"):
            try:
                version = int(version_str[1:])
            except ValueError:
                raise DefinitionError(
                    f"spawn target {target!r} has malformed version") from None
        defn: Optional[WorkflowDefinition] = self._definitions.get(name, version)
        if defn is None:
            raise DefinitionError(
                f"spawn target {target!r} not registered in loader")
        # Slice 4.0 records intent only; concrete fan-out lands in 4.5.
        await audit(action="workflow.saga.spawn_recorded",
                     resource_type="workflow_instance",
                     resource_id=instance.instance_id,
                     decision="PERMIT",
                     payload={"target": defn.qualified_name(),
                              "for_each": params.get("for_each"),
                              "join_on_terminal": params.get("join_on_terminal")})
        await increment("workflow_saga_spawn_recorded",
                          labels={"target": defn.name})
        logger.info("SagaComposer recorded spawn intent: instance=%s target=%s",
                     instance.instance_id, defn.qualified_name())
        return defn.qualified_name()
