"""FastAPI router for the Evidence context — ``/api/v1/evidence/*``.

Phase 3.4 + 3.5 surface:

* POST   /items                           — initiate multipart upload
* PUT    /items/{id}/parts/{part_no}      — stream a part
* POST   /items/{id}/complete             — finalize multipart
* POST   /items/{id}/verify               — read-back + hash verification
* GET    /items/{id}                      — read metadata (role-projected)
* GET    /items                           — list (scoped by ExecutionContext)
* POST   /items/{id}/signed-url           — issue short-lived signed URL
* POST   /seals                           — create immutable seal
* POST   /seals/{id}/apply-worm           — flip the WORM gate
* GET    /seals/{id}                      — read manifest (role-projected)
"""
from __future__ import annotations

from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, Path, Query, Request, status

from contexts.evidence.api.dtos import (
    ApplySealWormRequest,
    CompleteEvidenceUploadRequest,
    CreateSealRequest,
    EvidenceItemListResponse,
    EvidenceItemResponse,
    InitiateEvidenceUploadRequest,
    InitiateEvidenceUploadResponse,
    IssueSignedUrlRequest,
    SealResponse,
    SignedUrlResponse,
)
from contexts.evidence.application.evidence_service import (
    EvidenceCommandService,
    EvidenceQueryService,
)
from contexts.evidence.ports.specifications import (
    ByRegistry,
    ByStatus,
    EvidenceItemSpec,
)
from kernel.authorization.pep import enforce, require_auth
from kernel.persistence.context import ExecutionContext

router = APIRouter(prefix="/v1/evidence", tags=["evidence"])

_command: Optional[EvidenceCommandService] = None
_query: Optional[EvidenceQueryService] = None


def configure_router(command: EvidenceCommandService,
                     query: EvidenceQueryService) -> None:
    global _command, _query
    _command = command
    _query = query


def _cmd() -> EvidenceCommandService:
    if _command is None:
        raise RuntimeError("evidence command service not configured")
    return _command


def _qry() -> EvidenceQueryService:
    if _query is None:
        raise RuntimeError("evidence query service not configured")
    return _query


# ---- EvidenceItem endpoints -------------------------------------------------

@router.post("/items", status_code=status.HTTP_201_CREATED,
             response_model=InitiateEvidenceUploadResponse)
async def initiate_upload(payload: InitiateEvidenceUploadRequest,
                           _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("evidence.item.upload.initiate",
                  resource={"resource_type": "evidence_item"})
    body = payload.model_dump()
    body["kind"] = body["kind"].value if hasattr(body["kind"], "value") else body["kind"]
    return await _cmd().initiate_upload(**body)


async def _body_iter(request: Request) -> AsyncIterator[bytes]:
    async for chunk in request.stream():
        if chunk:
            yield chunk


@router.put("/items/{evidence_id}/parts/{part_no}")
async def upload_part(request: Request,
                      evidence_id: str = Path(...),
                      part_no: int = Path(..., ge=1, le=10_000),
                      _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("evidence.item.upload.complete",
                  resource={"resource_type": "evidence_item",
                            "resource_id": evidence_id})
    return await _cmd().upload_part(
        evidence_id=evidence_id, part_no=part_no,
        body_iter=_body_iter(request),
    )


@router.post("/items/{evidence_id}/complete",
              response_model=EvidenceItemResponse)
async def complete_upload(evidence_id: str,
                           payload: CompleteEvidenceUploadRequest,
                           _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("evidence.item.upload.complete",
                  resource={"resource_type": "evidence_item",
                            "resource_id": evidence_id})
    return await _cmd().complete_upload(
        evidence_id=evidence_id,
        parts=[p.model_dump() for p in payload.parts],
    )


@router.post("/items/{evidence_id}/verify",
              response_model=EvidenceItemResponse)
async def verify_evidence(evidence_id: str,
                           _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("evidence.item.verify",
                  resource={"resource_type": "evidence_item",
                            "resource_id": evidence_id})
    return await _cmd().verify(evidence_id=evidence_id)


@router.get("/items/{evidence_id}", response_model=EvidenceItemResponse)
async def get_evidence(evidence_id: str,
                        _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("evidence.item.read",
                  resource={"resource_type": "evidence_item",
                            "resource_id": evidence_id})
    return await _qry().get_item(evidence_id)


@router.get("/items", response_model=EvidenceItemListResponse)
async def list_evidence(
    registry_id: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    skip: int = Query(default=0, ge=0),
    _ctx: ExecutionContext = Depends(require_auth),
):
    await enforce("evidence.item.list",
                  resource={"resource_type": "evidence_item"})
    spec = EvidenceItemSpec()
    if registry_id:
        spec = spec.and_(ByRegistry(registry_id))
    if status_filter:
        spec = spec.and_(ByStatus(status_filter))
    return await _qry().list_items(spec=spec, limit=limit, skip=skip)


@router.post("/items/{evidence_id}/signed-url",
              response_model=SignedUrlResponse)
async def issue_signed_url(evidence_id: str,
                            payload: IssueSignedUrlRequest,
                            _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("evidence.item.read.signed_url",
                  resource={"resource_type": "evidence_item",
                            "resource_id": evidence_id})
    return await _cmd().issue_signed_url(
        evidence_id=evidence_id,
        action=payload.action,
        ttl_seconds=payload.ttl_seconds,
    )


# ---- Seal endpoints -----------------------------------------------------

@router.post("/seals", status_code=status.HTTP_201_CREATED,
              response_model=SealResponse)
async def create_seal(payload: CreateSealRequest,
                       _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("evidence.seal.create",
                  resource={"resource_type": "evidence_seal"})
    return await _cmd().create_seal(
        registry_id=payload.registry_id,
        evidence_ids=payload.evidence_ids,
    )


@router.post("/seals/{seal_id}/apply-worm",
              response_model=SealResponse)
async def apply_seal_worm(seal_id: str,
                           payload: ApplySealWormRequest,
                           _ctx: ExecutionContext = Depends(require_auth)):
    _ = payload  # body intentionally empty
    await enforce("evidence.seal.apply_worm",
                  resource={"resource_type": "evidence_seal",
                            "resource_id": seal_id})
    return await _cmd().apply_worm(seal_id=seal_id)


@router.get("/seals/{seal_id}", response_model=SealResponse)
async def get_seal(seal_id: str,
                    _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("evidence.seal.read",
                  resource={"resource_type": "evidence_seal",
                            "resource_id": seal_id})
    return await _qry().get_seal(seal_id)
