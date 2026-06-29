"""Phase 3.8 admin router — projection health, lag, replay, snapshot.

All endpoints are gated by ``kernel.projections.admin`` (super_admin
only — see ADR-0010 §5). The router never returns DTOs that contain
business state — only engine-owned cursor metadata.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import List, Optional

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict

from kernel.authorization.pep import enforce, require_auth
from kernel.errors.problem import not_found
from kernel.persistence.context import ExecutionContext
from kernel.projections import ProjectionEngine, current_engine

router = APIRouter(prefix="/v1/admin/projections", tags=["admin-projections"])


class ProjectionStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    version: int
    cursor_event_id: Optional[str] = None
    last_delivered_at: Optional[str] = None
    last_event_type: Optional[str] = None
    delivered_count: int
    lag_events: int
    rebuilding: bool
    last_snapshot_at: Optional[str] = None


class ProjectionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projections: List[ProjectionStatusResponse]


def _engine() -> ProjectionEngine:
    return current_engine()


@router.get("", response_model=ProjectionListResponse)
async def list_projections(
        _ctx: ExecutionContext = Depends(require_auth)) -> ProjectionListResponse:
    await enforce("kernel.projections.admin",
                  resource={"resource_type": "projection"})
    statuses = await _engine().health()
    return ProjectionListResponse(
        projections=[ProjectionStatusResponse(**asdict(s)) for s in statuses])


@router.get("/{name}", response_model=ProjectionStatusResponse)
async def get_projection(name: str,
                         _ctx: ExecutionContext = Depends(require_auth)
                         ) -> ProjectionStatusResponse:
    await enforce("kernel.projections.admin",
                  resource={"resource_type": "projection",
                            "resource_id": name})
    try:
        s = await _engine().status(name)
    except KeyError as exc:
        raise not_found(f"projection {name!r} not registered",
                        code="kernel.projection.not_found") from exc
    return ProjectionStatusResponse(**asdict(s))


@router.post("/{name}/replay", response_model=ProjectionStatusResponse,
             status_code=status.HTTP_200_OK)
async def replay_projection(name: str,
                            _ctx: ExecutionContext = Depends(require_auth)
                            ) -> ProjectionStatusResponse:
    await enforce("kernel.projections.admin",
                  resource={"resource_type": "projection",
                            "resource_id": name})
    try:
        s = await _engine().replay(name)
    except KeyError as exc:
        raise not_found(f"projection {name!r} not registered",
                        code="kernel.projection.not_found") from exc
    return ProjectionStatusResponse(**asdict(s))


@router.post("/{name}/snapshot", response_model=ProjectionStatusResponse,
             status_code=status.HTTP_200_OK)
async def snapshot_projection(name: str,
                              _ctx: ExecutionContext = Depends(require_auth)
                              ) -> ProjectionStatusResponse:
    await enforce("kernel.projections.admin",
                  resource={"resource_type": "projection",
                            "resource_id": name})
    try:
        await _engine().snapshot(name)
        s = await _engine().status(name)
    except KeyError as exc:
        raise not_found(f"projection {name!r} not registered",
                        code="kernel.projection.not_found") from exc
    return ProjectionStatusResponse(**asdict(s))
