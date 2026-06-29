"""AnchorPort — abstraction over an external transparency-log provider.

Per ADR-0008 §5.1. Adapters (`ctlog_internal`, `ots_v1`) implement this
Protocol. The saga depends only on this interface.

Idempotency contract:
* `request_anchor(batch_id, root)` MUST be idempotent over the
  ``(batch_id, root)`` pair — repeat calls return the same
  ``provider_request_id``.
* `poll_confirmation(request)` reports one of the four states below;
  callers handle backoff/DLQ based on the state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol


class AnchorState(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED_TRANSIENT = "failed_transient"
    FAILED_PERMANENT = "failed_permanent"


@dataclass(frozen=True)
class AnchorRequest:
    provider_id: str
    batch_id: str
    root: str
    provider_request_id: str
    submitted_at: str
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AnchorPollResult:
    state: str  # AnchorState value
    detail: Optional[str] = None
    provider_response: Optional[dict] = None


@dataclass(frozen=True)
class InclusionProof:
    """Per-seal inclusion proof material. Bytes are provider-specific."""
    provider_id: str
    seal_id: str
    leaf_hash: str
    proof_blob: dict  # JSON-safe representation of the proof bytes
    checkpoint_ref: Optional[str] = None


class AnchorPort(Protocol):
    provider_id: str

    async def request_anchor(self, *, batch_id: str,
                              root: str) -> AnchorRequest: ...

    async def poll_confirmation(self,
                                  request: AnchorRequest
                                  ) -> AnchorPollResult: ...

    async def fetch_inclusion_proof(self, request: AnchorRequest,
                                      leaf_hash: str
                                      ) -> InclusionProof: ...
