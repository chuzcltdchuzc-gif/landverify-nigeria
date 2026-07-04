"""WorkflowPolicy value object (Phase 4 — Slice 4.1).

A WorkflowPolicy is *content, not code*. It carries jurisdiction /
country / regional overrides + dynamic transition rules + SLA +
escalation config that the engine applies at runtime. Business slices
CONSUME policy via configuration; they NEVER embed policy or
escalation logic (ADR-0022).

Policies are:
* Immutable, versioned JSON documents.
* Keyed by ``(workflow_name, version, country_code, tenant_id)``. A
  policy with wider scope (empty country / empty tenant) is a fallback.
* Loaded at boot (from JSON on disk) AND consulted at runtime for the
  ``mayTransition`` / ``requiredEvidence`` / ``requiredRoles`` /
  ``requiredConsensus`` / ``timeout`` / ``escalation`` decisions.

Nothing in this module reaches into any business bounded context.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from contexts.workflow.domain.invariants import DefinitionError


@dataclass(frozen=True)
class TransitionRule:
    """A single transition rule overlaid on top of the definition.

    ``allow`` — whether the (from_state, command) transition is permitted
                for this policy scope (default: inherit from definition).
    ``required_roles`` — actor must hold at least one of these roles.
    ``required_evidence_kinds`` — list of evidence kinds that must exist.
    ``required_consensus`` — minimum consensus count / ratio (opaque, for
                             a future business slice to interpret).
    """
    from_state: str
    command: str
    allow: Optional[bool] = None
    required_roles: tuple[str, ...] = ()
    required_evidence_kinds: tuple[str, ...] = ()
    required_consensus: Optional[str] = None


@dataclass(frozen=True)
class StateSlaRule:
    """SLA + escalation rule bound to a state entry.

    ``timeout_seconds`` — engine schedules a timer this many seconds
                          after state entry; on fire it applies
                          ``escalation_command`` (if provided).
    ``escalation_chain`` — ordered list of (delay_seconds, command)
                           tuples applied in order; each fire schedules
                           the next.
    """
    state: str
    timeout_seconds: Optional[int] = None
    escalation_command: Optional[str] = None
    escalation_chain: tuple[tuple[int, str], ...] = ()


@dataclass(frozen=True)
class RetryPolicy:
    """Retry configuration for engine-internal command dispatch."""
    max_attempts: int = 5
    initial_backoff_seconds: int = 1
    max_backoff_seconds: int = 60
    backoff_multiplier: float = 2.0

    def backoff_for(self, attempt: int) -> int:
        """Deterministic exponential backoff (no jitter — replay-safe)."""
        if attempt < 1:
            return 0
        cur = float(self.initial_backoff_seconds)
        for _ in range(attempt - 1):
            cur *= self.backoff_multiplier
            if cur >= self.max_backoff_seconds:
                cur = float(self.max_backoff_seconds)
                break
        return int(cur)


@dataclass(frozen=True)
class WorkflowPolicy:
    """Immutable, jurisdiction-scoped workflow policy."""

    policy_id: str
    workflow_name: str
    workflow_version: Optional[int]        # None = applies to any version
    country_code: Optional[str]            # None = all countries
    tenant_id: Optional[str]               # None = all tenants
    version: int                           # policy version, monotonic
    description: str = ""
    transition_rules: tuple[TransitionRule, ...] = ()
    sla_rules: tuple[StateSlaRule, ...] = ()
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)

    # ---- Factory ------------------------------------------------------

    @classmethod
    def from_dict(cls, doc: dict) -> "WorkflowPolicy":
        if not isinstance(doc, dict):
            raise DefinitionError("workflow policy must be a JSON object")
        pid = doc.get("policy_id")
        wname = doc.get("workflow_name")
        pver = doc.get("version")
        if not isinstance(pid, str) or not pid:
            raise DefinitionError("policy.policy_id must be a non-empty string")
        if not isinstance(wname, str) or not wname:
            raise DefinitionError("policy.workflow_name must be a non-empty string")
        if not isinstance(pver, int) or pver < 1:
            raise DefinitionError("policy.version must be int >= 1")
        rules_raw = doc.get("transition_rules") or []
        if not isinstance(rules_raw, list):
            raise DefinitionError("policy.transition_rules must be an array")
        rules: list[TransitionRule] = []
        for r in rules_raw:
            if not isinstance(r, dict):
                raise DefinitionError("transition_rule must be an object")
            rules.append(TransitionRule(
                from_state=str(r["from"]),
                command=str(r["command"]),
                allow=r.get("allow"),
                required_roles=tuple(r.get("required_roles") or ()),
                required_evidence_kinds=tuple(
                    r.get("required_evidence_kinds") or ()),
                required_consensus=r.get("required_consensus"),
            ))
        sla_raw = doc.get("sla_rules") or []
        slas: list[StateSlaRule] = []
        for s in sla_raw:
            chain_raw = s.get("escalation_chain") or []
            chain = tuple(
                (int(step[0]), str(step[1])) for step in chain_raw
                if isinstance(step, (list, tuple)) and len(step) == 2)
            slas.append(StateSlaRule(
                state=str(s["state"]),
                timeout_seconds=(int(s["timeout_seconds"])
                                  if s.get("timeout_seconds") is not None
                                  else None),
                escalation_command=s.get("escalation_command"),
                escalation_chain=chain,
            ))
        retry_raw = doc.get("retry_policy") or {}
        retry = RetryPolicy(
            max_attempts=int(retry_raw.get("max_attempts", 5)),
            initial_backoff_seconds=int(
                retry_raw.get("initial_backoff_seconds", 1)),
            max_backoff_seconds=int(
                retry_raw.get("max_backoff_seconds", 60)),
            backoff_multiplier=float(
                retry_raw.get("backoff_multiplier", 2.0)),
        )
        return cls(
            policy_id=pid,
            workflow_name=wname,
            workflow_version=doc.get("workflow_version"),
            country_code=doc.get("country_code"),
            tenant_id=doc.get("tenant_id"),
            version=pver,
            description=str(doc.get("description", "")),
            transition_rules=tuple(rules),
            sla_rules=tuple(slas),
            retry_policy=retry,
        )

    # ---- Queries ------------------------------------------------------

    def rule_for(self, from_state: str,
                 command: str) -> Optional[TransitionRule]:
        for r in self.transition_rules:
            if r.from_state == from_state and r.command == command:
                return r
        return None

    def sla_for(self, state: str) -> Optional[StateSlaRule]:
        for s in self.sla_rules:
            if s.state == state:
                return s
        return None

    def scope_specificity(self) -> int:
        """Higher = more specific. Used to pick the best-fit policy."""
        n = 0
        if self.workflow_version is not None:
            n += 1
        if self.country_code:
            n += 2
        if self.tenant_id:
            n += 4
        return n

    def applies_to(self, *, workflow_name: str, workflow_version: int,
                   country_code: str, tenant_id: str) -> bool:
        if self.workflow_name != workflow_name:
            return False
        if (self.workflow_version is not None
                and self.workflow_version != workflow_version):
            return False
        if self.country_code and self.country_code != country_code:
            return False
        if self.tenant_id and self.tenant_id != tenant_id:
            return False
        return True
