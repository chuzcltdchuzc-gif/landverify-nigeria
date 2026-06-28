"""Policy Decision Point — pure decision function. Fail closed (ADR-002).

The PDP iterates registered policies in priority order. The first explicit
PERMIT or DENY wins. If no policy returns a decision, the engine default-
denies.

Decisions and denials are audited by the PEP (kernel.authorization.pep), so
this module stays pure and side-effect-free.
"""
from __future__ import annotations

import logging
from typing import Optional

from kernel.authorization.decisions import Decision
from kernel.authorization.policies import all_policies, register_default_policies
from kernel.persistence.context import ExecutionContext, current_context

logger = logging.getLogger("kernel.authorization.pdp")


def authorize(action: str, *, resource: Optional[dict] = None, env: Optional[dict] = None,
              ctx: Optional[ExecutionContext] = None) -> Decision:
    register_default_policies()
    ctx = ctx or current_context()
    resource = resource or {}
    env = env or {}
    for policy in all_policies():
        try:
            decision = policy.fn(ctx, action, resource, env)
        except Exception:
            logger.exception("policy %s crashed; treating as DENY for safety", policy.id)
            return Decision.deny(reason=f"policy {policy.id} crashed",
                                 policy_id=policy.id)
        if decision is not None:
            return decision
    return Decision.deny(reason="no policy granted access (default deny)",
                         policy_id="platform.default_deny")
