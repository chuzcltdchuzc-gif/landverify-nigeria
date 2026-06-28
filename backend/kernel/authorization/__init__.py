"""Authorization Engine — PEP / PDP / PIP / PAP (ADR-002).

Components:
    * PEP  — FastAPI dependency that intercepts every request, builds the
             ExecutionContext from a verified JWT, calls the PDP.
    * PDP  — Pure decision function. Evaluates RBAC + ABAC + tenant/country
             isolation + delegation. Fails closed.
    * PIP  — Attribute providers (resource attributes are passed in;
             principal attributes come from the JWT claims).
    * PAP  — Policy registry (in-code for Phase 1; PRD says this will move
             to Administration domain in a later phase).

Public surface:
    * `require_auth()`  — FastAPI dep that returns the ExecutionContext or 401
    * `authorize(...)`  — Programmatic permit/deny check returning a Decision
    * `register_policy(...)` — Append-only policy registration at startup
"""
from kernel.authorization.decisions import Decision, Obligation  # noqa: F401
from kernel.authorization.pdp import authorize  # noqa: F401
from kernel.authorization.pep import current_context_dep, require_auth, require_role  # noqa: F401
from kernel.authorization.policies import register_policy  # noqa: F401
