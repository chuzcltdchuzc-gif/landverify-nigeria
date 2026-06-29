"""Phase 3.6 API DTOs."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from contexts.evidence.domain.integrity_check import IntegrityTrigger


# ---- Anchor batch -------------------------------------------------------

class AnchorBatchResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    batch_id: str
    provider_id: str
    state: str
    merkle_root: str


class ReplayAnchorBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(..., min_length=1, max_length=500)


class InclusionProofBundleResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    seal_id: str
    proofs: list[dict]  # one per provider


# ---- Locks --------------------------------------------------------------

class EvidenceLockResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    lock_id: str
    evidence_id: str
    seal_id: str
    storage_provider: str
    mode: str
    retention_until: str
    applied_at: str
    applied_by: str


class EvidenceLockListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    locks: list[dict]


class ExtendLockRetentionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_until: str = Field(..., min_length=8, max_length=64)
    reason: str = Field(..., min_length=3, max_length=500)


# ---- Integrity ----------------------------------------------------------

class TriggerIntegrityCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str = Field(..., min_length=4, max_length=64)
    trigger: IntegrityTrigger = IntegrityTrigger.ON_DEMAND


class IntegrityCheckResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    check_id: str
    evidence_id: str
    outcome: str
    triggered_by: str


class IntegrityChainResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str
    chain: list[dict]


# ---- CT-log -------------------------------------------------------------

class CtlogCheckpointResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    head_seq: int
    tree_size: int
    root_hash: str
    published_at: str
    signature_kid: str
