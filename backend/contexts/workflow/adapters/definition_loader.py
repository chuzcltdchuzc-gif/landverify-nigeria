"""Definition Loader adapter (Phase 4 — Slice 4.0).

Loads frozen JSON workflow definitions from disk. Layout:
``contracts/v1/workflow_definitions/<name>.v<version>.json``.

Constitutional rule (ADR-0019 §C-19.1): definitions are content, not
code. A malformed definition causes the engine to refuse to boot
(``DefinitionError`` propagates from ``from_dict()``).

Cross-definition spawn cycle detection runs once all definitions are
loaded.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from contexts.workflow.domain.invariants import DefinitionError
from contexts.workflow.domain.workflow_definition import WorkflowDefinition

logger = logging.getLogger("contexts.workflow.adapters.definition_loader")


class FsDefinitionLoader:
    """Default loader: reads from a directory of JSON files."""

    def __init__(self, definitions_dir: Path) -> None:
        self._dir = Path(definitions_dir)
        self._by_qualified: dict[str, WorkflowDefinition] = {}
        self._latest_by_name: dict[str, WorkflowDefinition] = {}

    def load(self) -> None:
        self._by_qualified.clear()
        self._latest_by_name.clear()
        if not self._dir.exists():
            logger.warning("workflow definitions dir missing: %s", self._dir)
            return
        for path in sorted(self._dir.glob("*.json")):
            with path.open("r", encoding="utf-8") as fp:
                try:
                    doc = json.load(fp)
                except json.JSONDecodeError as exc:
                    raise DefinitionError(
                        f"malformed JSON in {path.name}: {exc}") from exc
            defn = WorkflowDefinition.from_dict(doc)
            key = f"{defn.name}@v{defn.version}"
            if key in self._by_qualified:
                raise DefinitionError(f"duplicate definition {key} on disk")
            self._by_qualified[key] = defn
            cur_latest = self._latest_by_name.get(defn.name)
            if cur_latest is None or defn.version > cur_latest.version:
                self._latest_by_name[defn.name] = defn
        self._assert_no_cross_definition_cycle()
        logger.info("loaded %d workflow definition(s) from %s",
                    len(self._by_qualified), self._dir)

    def list_definitions(self) -> list[WorkflowDefinition]:
        return sorted(self._by_qualified.values(),
                       key=lambda d: (d.name, d.version))

    def get(self, name: str,
            version: Optional[int] = None) -> Optional[WorkflowDefinition]:
        if version is not None:
            return self._by_qualified.get(f"{name}@v{version}")
        return self._latest_by_name.get(name)

    # ---------------------------------------------------------------
    # Cycle detection across definitions.
    # ---------------------------------------------------------------

    def _assert_no_cross_definition_cycle(self) -> None:
        """A → B → A spawn graphs are rejected (RB-5 mitigation)."""
        graph: dict[str, set[str]] = {}
        for defn in self._latest_by_name.values():
            targets: set[str] = set()
            for state in defn.states.values():
                for action in state.on_enter:
                    if action.verb != "spawn":
                        continue
                    target = action.params.get("definition")
                    if isinstance(target, str):
                        # ``spawn`` may carry a version-qualified or bare name.
                        target_name = target.split("@", 1)[0]
                        targets.add(target_name)
            graph[defn.name] = targets

        # Iterative DFS.
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {n: WHITE for n in graph}

        def visit(node: str, stack: list[str]) -> None:
            color[node] = GRAY
            stack.append(node)
            for neighbour in graph.get(node, ()):
                if neighbour not in color:
                    continue
                if color[neighbour] == GRAY:
                    cycle = " -> ".join(stack + [neighbour])
                    raise DefinitionError(
                        f"spawn cycle detected across definitions: {cycle}")
                if color[neighbour] == WHITE:
                    visit(neighbour, stack)
            color[node] = BLACK
            stack.pop()

        for node in list(graph.keys()):
            if color[node] == WHITE:
                visit(node, [])


class InMemoryDefinitionLoader:
    """In-memory loader for tests."""

    def __init__(self, definitions: list[WorkflowDefinition]) -> None:
        self._by_qualified: dict[str, WorkflowDefinition] = {}
        self._latest_by_name: dict[str, WorkflowDefinition] = {}
        for defn in definitions:
            key = f"{defn.name}@v{defn.version}"
            if key in self._by_qualified:
                raise DefinitionError(f"duplicate definition {key}")
            self._by_qualified[key] = defn
            cur = self._latest_by_name.get(defn.name)
            if cur is None or defn.version > cur.version:
                self._latest_by_name[defn.name] = defn

    def list_definitions(self) -> list[WorkflowDefinition]:
        return sorted(self._by_qualified.values(),
                       key=lambda d: (d.name, d.version))

    def get(self, name: str,
            version: Optional[int] = None) -> Optional[WorkflowDefinition]:
        if version is not None:
            return self._by_qualified.get(f"{name}@v{version}")
        return self._latest_by_name.get(name)
