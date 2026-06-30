"""WorkflowDefinition aggregate (Phase 4 — Slice 4.0).

A WorkflowDefinition is an immutable, versioned JSON document that
describes a state graph. It is loaded once at boot by DefinitionLoader
and never mutated at runtime — operationally a new version is shipped
by adding a new ``<name>.v<n>.json`` to the contract package.

Constitutional rules (ADR-0019 §C-19.x):
* Definitions are content, not code. No business logic in the engine.
* The DSL vocabulary is intentionally tiny: states, transitions,
  on_enter actions (``emit_command`` / ``schedule_timer`` / ``create_task``
  / ``record_compensation`` / ``spawn``).
* Cyclical ``spawn`` graphs are rejected at load time.
* Unknown command, unknown state, unknown action verb → DefinitionError.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from contexts.workflow.domain.invariants import DefinitionError
from contexts.workflow.domain.value_objects import StateTransition

# Vocabulary the engine recognises. New verbs require a new ADR + bump.
_ALLOWED_ACTION_VERBS = frozenset({
    "emit_command",
    "schedule_timer",
    "create_task",
    "record_compensation",
    "spawn",
})


@dataclass(frozen=True)
class Action:
    """A single on_enter action declared in a WorkflowDefinition.

    Action verbs are bound to engine primitives — the engine never
    interprets arbitrary expressions, only fixed verbs with frozen
    parameter shapes. See ADR-0019 §C-19.1 / §C-19.6.
    """
    verb: str            # one of _ALLOWED_ACTION_VERBS
    params: dict         # frozen JSON parameter object

    def __post_init__(self) -> None:
        if self.verb not in _ALLOWED_ACTION_VERBS:
            raise DefinitionError(
                f"unknown action verb {self.verb!r}; allowed: "
                f"{sorted(_ALLOWED_ACTION_VERBS)}")


@dataclass(frozen=True)
class State:
    name: str
    on_enter: tuple[Action, ...] = ()
    is_terminal: bool = False


@dataclass(frozen=True)
class WorkflowDefinition:
    """Immutable workflow specification."""

    name: str                                   # e.g. "echo.v1"
    version: int                                # numeric, monotonic per name
    initial_state: str
    states: dict[str, State]                    # name -> State
    transitions: tuple[StateTransition, ...]    # legal moves
    description: str = ""

    # ---------------------------------------------------------------
    # Construction & validation
    # ---------------------------------------------------------------

    @classmethod
    def from_dict(cls, doc: dict) -> "WorkflowDefinition":
        """Build a WorkflowDefinition from a frozen JSON doc.

        Raises DefinitionError on any structural problem.
        """
        if not isinstance(doc, dict):
            raise DefinitionError("workflow definition must be a JSON object")

        name = doc.get("name")
        version = doc.get("version")
        initial_state = doc.get("initial_state")
        raw_states = doc.get("states")
        raw_transitions = doc.get("transitions") or []
        description = doc.get("description", "")

        if not isinstance(name, str) or not name:
            raise DefinitionError("definition.name must be a non-empty string")
        if not isinstance(version, int) or version < 1:
            raise DefinitionError("definition.version must be int >= 1")
        if not isinstance(initial_state, str) or not initial_state:
            raise DefinitionError("definition.initial_state must be a string")
        if not isinstance(raw_states, dict) or not raw_states:
            raise DefinitionError("definition.states must be a non-empty object")
        if not isinstance(raw_transitions, list):
            raise DefinitionError("definition.transitions must be an array")

        # Build states.
        states: dict[str, State] = {}
        for sname, sdoc in raw_states.items():
            if not isinstance(sname, str) or not sname:
                raise DefinitionError(f"state name must be non-empty string; got {sname!r}")
            if not isinstance(sdoc, dict):
                raise DefinitionError(f"state {sname!r} must be an object")
            is_terminal = bool(sdoc.get("terminal"))
            actions_raw = sdoc.get("on_enter") or []
            if not isinstance(actions_raw, list):
                raise DefinitionError(
                    f"state {sname!r}.on_enter must be an array")
            actions: list[Action] = []
            for a in actions_raw:
                if not isinstance(a, dict) or "verb" not in a:
                    raise DefinitionError(
                        f"state {sname!r}.on_enter entries require 'verb'")
                actions.append(Action(verb=a["verb"], params=dict(a.get("params") or {})))
            states[sname] = State(name=sname,
                                   on_enter=tuple(actions),
                                   is_terminal=is_terminal)

        if initial_state not in states:
            raise DefinitionError(
                f"initial_state {initial_state!r} is not declared in states")

        # Build transitions.
        transitions: list[StateTransition] = []
        for t in raw_transitions:
            if not isinstance(t, dict):
                raise DefinitionError("each transition must be an object")
            fr, cmd, to = t.get("from"), t.get("command"), t.get("to")
            if fr not in states:
                raise DefinitionError(
                    f"transition.from {fr!r} not declared in states")
            if to not in states:
                raise DefinitionError(
                    f"transition.to {to!r} not declared in states")
            if not isinstance(cmd, str) or not cmd:
                raise DefinitionError(
                    f"transition.command must be a non-empty string; got {cmd!r}")
            transitions.append(StateTransition(from_state=fr, command=cmd, to_state=to))

        defn = cls(name=name, version=version,
                   initial_state=initial_state,
                   states=states,
                   transitions=tuple(transitions),
                   description=description if isinstance(description, str) else "")
        _assert_no_spawn_cycle(defn)
        return defn

    # ---------------------------------------------------------------
    # Queries
    # ---------------------------------------------------------------

    def is_terminal(self, state_name: str) -> bool:
        if state_name not in self.states:
            return False
        return self.states[state_name].is_terminal

    def legal_target(self, current_state: str, command: str) -> Optional[str]:
        """Return target state if (current_state, command) is a declared
        transition; ``None`` otherwise."""
        for t in self.transitions:
            if t.from_state == current_state and t.command == command:
                return t.to_state
        return None

    def known_commands(self, current_state: str) -> list[str]:
        return sorted({t.command for t in self.transitions
                       if t.from_state == current_state})

    def on_enter(self, state_name: str) -> tuple[Action, ...]:
        if state_name not in self.states:
            return ()
        return self.states[state_name].on_enter

    def qualified_name(self) -> str:
        return f"{self.name}@v{self.version}"


def _assert_no_spawn_cycle(defn: WorkflowDefinition) -> None:
    """Reject definitions whose ``spawn`` actions reference themselves
    directly. Cross-definition cycles are caught at registry load time
    by DefinitionLoader (multiple definitions known at once).
    """
    for state in defn.states.values():
        for action in state.on_enter:
            if action.verb != "spawn":
                continue
            target = action.params.get("definition")
            if not isinstance(target, str):
                raise DefinitionError(
                    f"spawn action in state {state.name!r} requires "
                    "params.definition (string)")
            if target == defn.name:
                raise DefinitionError(
                    f"spawn cycle: definition {defn.name!r} spawns itself")
