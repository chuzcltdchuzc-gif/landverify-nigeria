"""RFC 7807 problem+json canonical error model (binding, API Standards §7).

No stack traces or internal identifiers leak. Every problem response carries
a stable error code and the request correlation id for support tooling.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass, field
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("kernel.errors")

PROBLEM_BASE = "https://aquasavannah.landvault/problems"


@dataclass
class Problem:
    """RFC 7807 problem document."""
    title: str
    status: int
    code: str
    detail: Optional[str] = None
    type: str = ""
    instance: Optional[str] = None
    correlation_id: Optional[str] = None
    extras: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.type:
            self.type = f"{PROBLEM_BASE}/{self.code}"

    def to_dict(self) -> dict:
        d = asdict(self)
        extras = d.pop("extras") or {}
        d = {k: v for k, v in d.items() if v is not None}
        d.update(extras)
        return d


class ProblemException(Exception):
    """Raise to short-circuit a request with an RFC 7807 response."""

    def __init__(self, problem: Problem) -> None:
        super().__init__(problem.title)
        self.problem = problem


# Canonical problem factories ------------------------------------------------

def unauthenticated(detail: Optional[str] = None, code: str = "auth.unauthenticated") -> ProblemException:
    return ProblemException(Problem(title="Not authenticated", status=401, code=code, detail=detail))


def forbidden(detail: Optional[str] = None, code: str = "auth.forbidden") -> ProblemException:
    return ProblemException(Problem(title="Forbidden", status=403, code=code, detail=detail))


def not_found(detail: Optional[str] = None, code: str = "common.not_found") -> ProblemException:
    return ProblemException(Problem(title="Resource not found", status=404, code=code, detail=detail))


def conflict(detail: Optional[str] = None, code: str = "common.conflict") -> ProblemException:
    return ProblemException(Problem(title="Conflict", status=409, code=code, detail=detail))


def bad_request(detail: Optional[str] = None, code: str = "common.bad_request",
                extras: Optional[dict] = None) -> ProblemException:
    p = Problem(title="Bad request", status=400, code=code, detail=detail)
    if extras:
        p.extras.update(extras)
    return ProblemException(p)


def register_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemException)
    async def _handle(request: Request, exc: ProblemException) -> JSONResponse:
        prob = exc.problem
        if prob.correlation_id is None:
            prob.correlation_id = getattr(request.state, "correlation_id", None) or str(uuid.uuid4())
        if prob.instance is None:
            prob.instance = str(request.url.path)
        return JSONResponse(status_code=prob.status, content=prob.to_dict(),
                            media_type="application/problem+json")
