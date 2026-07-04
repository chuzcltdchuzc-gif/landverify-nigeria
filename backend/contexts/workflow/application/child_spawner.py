"""ChildSpawner — real ``spawn`` fan-out execution (Phase 4 — Slice 4.1).

Replaces the Slice 4.0 audit-only stub. Given a ``spawn`` action with a
``definition`` target and (optionally) a ``for_each`` array of items,
starts a real child WorkflowInstance per item and records a
``ChildLink`` in the child registry.

Constitutional rules:
* No new event types are introduced — children raise the standard
  ``workflow.instance.started`` event already in the contract.
* Parent-child linkage is server-internal (``workflow_child_registry``)
  and never leaks into the public contract.
* Cyclical spawn graphs remain rejected at definition load time
  (Slice 4.0 FsDefinitionLoader).
* ``join_on_terminal`` is available for future business slices but not
  enforced by the engine (parent flow control stays with the
  definition author).
"""
from __future__ import annotations

import logging
from typing import Optional

from contexts.workflow.adapters.slice41_repositories import MongoChildRegistry
from contexts.workflow.domain.child_link import ChildLink
from contexts.workflow.domain.invariants import DefinitionError
from contexts.workflow.domain.workflow_definition import WorkflowDefinition
from contexts.workflow.domain.workflow_instance import WorkflowInstance
from contexts.workflow.ports.repository import DefinitionLoader
from kernel.audit import audit
from kernel.observability.metrics import increment

logger = logging.getLogger("contexts.workflow.child_spawner")


class ChildSpawner:
    """Interprets ``spawn`` declarations into real child instances."""

    def __init__(self, *, definitions: DefinitionLoader,
                 registry: MongoChildRegistry) -> None:
        self._definitions = definitions
        self._registry = registry

    async def spawn(self, *, params: dict, parent: WorkflowInstance,
                    actor: str, session,
                    engine_starter) -> list[ChildLink]:
        """Perform the spawn.

        ``engine_starter`` is a coroutine ``(defn, payload, correlation,
        parent, session) -> WorkflowInstance`` provided by the engine so
        this module does not import the engine (avoids a cycle).
        """
        target = params.get("definition")
        if not isinstance(target, str) or not target:
            raise DefinitionError(
                "spawn action requires params.definition (string)")
        name, _, version_str = target.partition("@")
        version: Optional[int] = None
        if version_str.startswith("v"):
            try:
                version = int(version_str[1:])
            except ValueError:
                raise DefinitionError(
                    f"spawn target {target!r} malformed version") from None
        defn: Optional[WorkflowDefinition] = self._definitions.get(name, version)
        if defn is None:
            raise DefinitionError(
                f"spawn target {target!r} not registered")

        for_each = params.get("for_each")
        join = bool(params.get("join_on_terminal", False))
        items: list[dict]
        if for_each is None:
            items = [{"key": "0",
                       "payload": dict(params.get("payload") or {})}]
        elif isinstance(for_each, list):
            items = []
            for i, entry in enumerate(for_each):
                if isinstance(entry, dict):
                    key = str(entry.get("key", i))
                    payload = dict(entry.get("payload") or {})
                else:
                    key = str(i)
                    payload = {"item": entry}
                items.append({"key": key, "payload": payload})
        else:
            raise DefinitionError(
                "spawn params.for_each must be an array or absent")

        links: list[ChildLink] = []
        for item in items:
            child_correlation = (parent.correlation_id
                                  or parent.instance_id) + "::" + item["key"]
            child = await engine_starter(defn=defn,
                                          payload=item["payload"],
                                          correlation=child_correlation,
                                          parent=parent,
                                          session=session)
            link = ChildLink.create(
                parent_instance_id=parent.instance_id,
                child_instance_id=child.instance_id,
                parent_definition_name=parent.definition_name,
                child_definition_name=defn.name,
                tenant_id=parent.tenant_id,
                country_code=parent.country_code,
                key=item["key"],
                join_on_terminal=join)
            await self._registry.save(link, session=session)
            links.append(link)
        await audit(action="workflow.spawn.executed",
                     resource_type="workflow_instance",
                     resource_id=parent.instance_id,
                     decision="PERMIT",
                     payload={"target": defn.qualified_name(),
                              "count": len(links),
                              "join_on_terminal": join})
        await increment("workflow_spawn_children",
                          labels={"target": defn.name,
                                  "count": str(len(links))})
        logger.info("ChildSpawner spawned %d child(ren) target=%s parent=%s",
                     len(links), defn.qualified_name(), parent.instance_id)
        return links

    async def list_children(self,
                            parent_instance_id: str) -> list[ChildLink]:
        return await self._registry.list_children(parent_instance_id)

    async def on_child_terminal(self,
                                 child_instance_id: str) -> Optional[ChildLink]:
        link = await self._registry.find_by_child(child_instance_id)
        if link is None or link.child_terminal:
            return link
        link.mark_child_terminal()
        await self._registry.save(link)
        return link
