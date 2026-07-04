"""ChildLink aggregate (Phase 4 — Slice 4.1).

Records a parent/child relationship between two ``WorkflowInstance``
aggregates created by a ``spawn`` action. The child instance is a real,
independent WorkflowInstance persisted through the standard
``MongoWorkflowInstanceRepository``. The ChildLink connects the two
so that:

* The parent can query which children exist.
* A ``join_on_terminal`` semantics is expressible: parent waits for all
  children to reach a terminal lifecycle before it may complete its
  own state.

No business logic is encoded here.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from contexts.workflow.domain.value_objects import now_iso


def new_child_link_id() -> str:
    return "wfcl_" + uuid.uuid4().hex


@dataclass
class ChildLink:
    """A single parent → child link."""

    link_id: str
    parent_instance_id: str
    child_instance_id: str
    parent_definition_name: str
    child_definition_name: str
    tenant_id: str
    country_code: str
    key: str                       # correlation key from for_each item
    join_on_terminal: bool
    created_at: str
    child_terminal: bool = False
    child_terminal_at: Optional[str] = None
    version: int = 1

    @classmethod
    def create(cls, *, parent_instance_id: str, child_instance_id: str,
               parent_definition_name: str, child_definition_name: str,
               tenant_id: str, country_code: str, key: str,
               join_on_terminal: bool,
               link_id: Optional[str] = None) -> "ChildLink":
        return cls(
            link_id=link_id or new_child_link_id(),
            parent_instance_id=parent_instance_id,
            child_instance_id=child_instance_id,
            parent_definition_name=parent_definition_name,
            child_definition_name=child_definition_name,
            tenant_id=tenant_id, country_code=country_code,
            key=key, join_on_terminal=join_on_terminal,
            created_at=now_iso())

    @classmethod
    def from_state(cls, state: dict) -> "ChildLink":
        clean = {k: v for k, v in state.items()
                 if k in cls.__dataclass_fields__ and not k.startswith("_")}
        return cls(**clean)

    def mark_child_terminal(self) -> None:
        self.child_terminal = True
        self.child_terminal_at = now_iso()
        self.version += 1

    def to_state(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__
                if not k.startswith("_")}
