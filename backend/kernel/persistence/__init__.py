"""Persistence subsystem — ExecutionContext, Repository base, Specifications, Unit of Work.

ADR-002/003/007 compliance: every persistence operation flows through a
repository scoped to the current authenticated ExecutionContext. Controllers
never touch the database. Client-supplied tenant/country values are ignored
for scoping and treated as attack signals.
"""
from kernel.persistence.context import ExecutionContext, current_context, set_context  # noqa: F401
