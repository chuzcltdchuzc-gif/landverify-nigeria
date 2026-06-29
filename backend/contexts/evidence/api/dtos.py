"""Per-role Pydantic DTOs for the Evidence API (Phase 3.4 + 3.5).

All input models use ``model_config = {"extra": "forbid"}`` to defeat
mass-assignment. Server-owned fields (evidence_id, tenant_id,
country_code, server_hash, server_hash_streamed, version, audit) are NOT
in any input model — clients can never set them.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from contexts.evidence.domain.value_objects import EvidenceKind


# ---- Upload session ------------------------------------------------------

class InitiateEvidenceUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registry_id: str = Field(..., min_length=4, max_length=64)
    kind: EvidenceKind
    media_type: str = Field(..., min_length=3, max_length=128)
    max_size: int = Field(..., gt=0, le=10 * 1024 * 1024 * 1024)
    client_hash_claim: Optional[str] = Field(
        default=None, pattern=r"^[a-f0-9]{64}$")


class InitiateEvidenceUploadResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    evidence_id: str
    registry_id: str
    upload_id: str
    max_size: int
    storage_key: str
    storage_provider: str
    status: str
    version: int


class CompletePartReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    part_no: int = Field(..., ge=1, le=10_000)
    size_bytes: int = Field(..., ge=0)
    streamed_sha256: str = Field(..., pattern=r"^[a-f0-9]{64}$")


class CompleteEvidenceUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parts: list[CompletePartReceipt] = Field(..., min_length=1, max_length=10_000)


class EvidenceItemResponse(BaseModel):
    """Per-role projected response — projection happens upstream."""
    model_config = ConfigDict(extra="allow")
    evidence_id: str
    registry_id: str
    status: str


class EvidenceItemListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[dict]
    total: int
    limit: int
    skip: int


# ---- Signed URL ----------------------------------------------------------

class IssueSignedUrlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(default="read", pattern=r"^(read|verify|export)$")
    ttl_seconds: int = Field(default=300, ge=30, le=3600)


class SignedUrlResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    expires_at: str
    audit_id: str
    url_sha256: str
    ttl_seconds: int


# ---- Seal ----------------------------------------------------------------

class CreateSealRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registry_id: str = Field(..., min_length=4, max_length=64)
    evidence_ids: list[str] = Field(..., min_length=1, max_length=500)


class SealResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    seal_id: str
    registry_id: str
    status: str
    merkle_root: str
    manifest_hash: str


class ApplySealWormRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # No body fields — apply_worm uses the seal's frozen manifest.
