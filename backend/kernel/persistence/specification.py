"""Repository Specification pattern (Section 2.4).

Business services express data needs through Specifications, not raw Mongo
queries. Repositories own the translation. This makes the data layer
portable, testable, and provably tenant-scoped.

Specifications compose:
    spec = ActiveUsersSpecification().and_(UsersByCountrySpecification("NG"))
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Specification:
    """Base specification. Concrete subclasses populate `clauses`.

    The clauses are an internal "intent" representation. The repository
    adapter translates them into a Mongo filter.
    """
    clauses: tuple[tuple[str, Any], ...] = field(default_factory=tuple)

    def and_(self, other: "Specification") -> "Specification":
        return Specification(clauses=self.clauses + other.clauses)

    def to_mongo_filter(self) -> dict:
        """Translate clauses to a Mongo filter. Only the repository should call this."""
        flt: dict[str, Any] = {}
        for op, value in self.clauses:
            if op.startswith("eq:"):
                flt[op[3:]] = value
            elif op.startswith("in:"):
                flt[op[3:]] = {"$in": list(value)}
            elif op.startswith("ne:"):
                flt[op[3:]] = {"$ne": value}
        return flt
