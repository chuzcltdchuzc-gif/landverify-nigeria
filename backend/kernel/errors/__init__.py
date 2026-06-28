"""Errors subsystem — RFC 7807 problem+json (binding API standard, ADR-006)."""
from kernel.errors.problem import (  # noqa: F401
    Problem,
    ProblemException,
    register_problem_handlers,
)
