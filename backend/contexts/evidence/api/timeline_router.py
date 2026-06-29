"""Phase 3.7 router — timeline + custody + legal hold + supersession."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field

from contexts.evidence.application.timeline_service import (
    CustodyService,
    LegalHoldService,
    SupersessionService,
)
from contexts.evidence.adapters.mongo_timeline_repository import (
    MongoCustodyRepository,
    MongoLegalHoldRepository,
    MongoTimelineRepository,
)
from kernel.authorization.pep import enforce, require_auth
from kernel.persistence.context import ExecutionContext

router = APIRouter(prefix="/v1/evidence", tags=["evidence-timeline"])

_timeline: Optional[MongoTimelineRepository] = None
_custody_repo: Optional[MongoCustodyRepository] = None
_holds_repo: Optional[MongoLegalHoldRepository] = None
_custody_svc: Optional[CustodyService] = None
_holds_svc: Optional[LegalHoldService] = None
_supersession_svc: Optional[SupersessionService] = None


def configure_router(*, timeline_repo, custody_repo, holds_repo,
                     custody_svc, holds_svc, supersession_svc) -> None:
    global _timeline, _custody_repo, _holds_repo, _custody_svc, _holds_svc, _supersession_svc
    _timeline = timeline_repo
    _custody_repo = custody_repo
    _holds_repo = holds_repo
    _custody_svc = custody_svc
    _holds_svc = holds_svc
    _supersession_svc = supersession_svc


def _need(obj, name):
    if obj is None:
        raise RuntimeError(f"{name} not configured")
    return obj


class RecordCustodyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(..., min_length=2, max_length=64)
    action: str = Field(..., pattern=r"^(created|transferred|signed|accessed|exported|released)$")
    justification: str = Field(..., min_length=3, max_length=500)
    signature_kid: Optional[str] = Field(default=None, max_length=64)
    signature: Optional[str] = Field(default=None, max_length=512)


class ApplyLegalHoldRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_reference: str = Field(..., min_length=3, max_length=128)
    reason: str = Field(..., min_length=3, max_length=500)


class ReleaseLegalHoldRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    release_reason: str = Field(..., min_length=3, max_length=500)


@router.get("/items/{evidence_id}/timeline")
async def get_timeline(evidence_id: str,
                        _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("evidence.timeline.read",
                  resource={"resource_type": "timeline",
                            "resource_id": evidence_id})
    chain = await _need(_timeline, "timeline").chain(evidence_id)
    return {"evidence_id": evidence_id,
            "chain": [c.to_state() for c in chain]}


@router.get("/items/{evidence_id}/custody")
async def get_custody(evidence_id: str,
                       _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("evidence.custody.read",
                  resource={"resource_type": "custody",
                            "resource_id": evidence_id})
    chain = await _need(_custody_repo, "custody").chain(evidence_id)
    return {"evidence_id": evidence_id,
            "chain": [c.to_state() for c in chain]}


@router.post("/items/{evidence_id}/custody",
              status_code=status.HTTP_201_CREATED)
async def record_custody(evidence_id: str, payload: RecordCustodyRequest,
                           _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("evidence.custody.record",
                  resource={"resource_type": "custody",
                            "resource_id": evidence_id})
    return await _need(_custody_svc, "custody_svc").record_transfer(
        evidence_id=evidence_id, role=payload.role,
        action=payload.action, justification=payload.justification,
        signature_kid=payload.signature_kid, signature=payload.signature)


@router.get("/items/{evidence_id}/supersession-chain")
async def supersession_chain(evidence_id: str,
                              _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("evidence.timeline.read",
                  resource={"resource_type": "supersession",
                            "resource_id": evidence_id})
    links = await _need(_supersession_svc, "supersession").chain(evidence_id)
    return {"evidence_id": evidence_id,
            "chain": [link.to_dict() for link in links]}


@router.post("/items/{evidence_id}/legal-holds",
              status_code=status.HTTP_201_CREATED)
async def apply_legal_hold(evidence_id: str,
                             payload: ApplyLegalHoldRequest,
                             _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("evidence.legal_hold.apply",
                  resource={"resource_type": "legal_hold",
                            "resource_id": evidence_id})
    return await _need(_holds_svc, "holds_svc").apply(
        evidence_id=evidence_id,
        case_reference=payload.case_reference, reason=payload.reason)


@router.get("/items/{evidence_id}/legal-holds")
async def list_legal_holds(evidence_id: str,
                              _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("evidence.legal_hold.read",
                  resource={"resource_type": "legal_hold",
                            "resource_id": evidence_id})
    holds = await _need(_holds_repo, "holds").list_for_evidence(evidence_id)
    return {"evidence_id": evidence_id,
            "holds": [h.to_state() for h in holds]}


@router.get("/legal-holds/{hold_id}")
async def get_legal_hold(hold_id: str,
                            _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("evidence.legal_hold.read",
                  resource={"resource_type": "legal_hold",
                            "resource_id": hold_id})
    h = await _need(_holds_repo, "holds").get(hold_id)
    if not h:
        from kernel.errors.problem import not_found
        raise not_found(f"legal hold {hold_id} not found",
                          code="evidence.legal_hold.not_found")
    return h.to_state()


@router.post("/legal-holds/{hold_id}/release")
async def release_legal_hold(hold_id: str,
                                payload: ReleaseLegalHoldRequest,
                                _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("evidence.legal_hold.release",
                  resource={"resource_type": "legal_hold",
                            "resource_id": hold_id})
    return await _need(_holds_svc, "holds_svc").release(
        hold_id=hold_id, release_reason=payload.release_reason)
