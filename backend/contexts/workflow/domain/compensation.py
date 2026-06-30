"""CompensationLog aggregate (Phase 4 — Slice 4.0).

A compensation entry records that the engine has scheduled (or
performed) a saga rollback step. The log is append-only and replayable;
slices 4.2+ will hook in concrete compensators (e.g. "release evidence
hold on inheritance cancellation"). For 4.0 the log just demonstrates
the pattern works.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from contexts.workflow.domain.events import DomainEvent
from contexts.workflow.domain.value_objects import new_compensation_id, now_iso

SCHEMA_VERSION_CURRENT = 1


@dataclass
class CompensationEntry:
    """One append-only saga compensation record."""

    compensation_id: str
    instance_id: str
    definition_name: str
    tenant_id: str
    country_code: str
    verb: str                            # the compensator verb (free-form for now)
    payload: dict
    recorded_at: str
    actor: str
    schema_version: int = SCHEMA_VERSION_CURRENT

    _events: list[DomainEvent] = field(default_factory=list,
                                        repr=False, compare=False)

    @classmethod
    def record(cls, *, instance_id: str, definition_name: str,
               tenant_id: str, country_code: str, verb: str,
               payload: dict, actor: str) -> "CompensationEntry":
        cid = new_compensation_id()
        entry = cls(compensation_id=cid, instance_id=instance_id,
                     definition_name=definition_name,
                     tenant_id=tenant_id, country_code=country_code,
                     verb=verb, payload=dict(payload),
                     recorded_at=now_iso(), actor=actor)
        entry._raise(DomainEvent(
            event_type="workflow.compensation.recorded",
            aggregate_id=cid,
            aggregate_version=1,
            aggregate_type="WorkflowCompensation",
            payload={"compensation_id": cid,
                      "instance_id": instance_id,
                      "definition_name": definition_name,
                      "verb": verb,
                      "actor": actor,
                      "payload": dict(payload)}))
        return entry

    def _raise(self, ev: DomainEvent) -> None:
        self._events.append(ev)

    def pull_events(self) -> list[DomainEvent]:
        out = list(self._events)
        self._events.clear()
        return out

    def to_state(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__
                if not k.startswith("_")}
