"""CheckpointPublisherPort — publishes signed CT-log tree heads.

Per ADR-0008 §5.2 + §15 Decision 1.

* Dev default: local-FS exporter (writes JSON files under
  ``${EVIDENCE_CHECKPOINT_DIR}``).
* Production: R2 Public, IPFS, or both via fan-out — operator chooses
  via ``EVIDENCE_CHECKPOINT_PUBLISHERS`` env (csv).
* The core domain depends ONLY on this Protocol. Adding a destination
  is purely additive — new adapter file, new env entry, no domain
  change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol


@dataclass(frozen=True)
class TreeHead:
    head_seq: int          # monotonic head sequence
    tree_size: int         # total leaves at this head
    root_hash: str         # sha256 hex of the tree
    timestamp: str         # ISO8601
    publisher_id: str      # publishing platform id, e.g. "ctlog_internal"
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"head_seq": self.head_seq, "tree_size": self.tree_size,
                "root_hash": self.root_hash, "timestamp": self.timestamp,
                "publisher_id": self.publisher_id, "extra": self.extra}


@dataclass(frozen=True)
class CheckpointRef:
    publisher_id: str
    head_seq: int
    locator: str           # e.g. file path, R2 key, IPFS CID
    signature: str         # base64-encoded signature over canonical head JSON
    signature_kid: str     # JWKS key id
    published_at: str


class CheckpointPublisherPort(Protocol):
    publisher_id: str

    async def publish_checkpoint(self, *, head: TreeHead,
                                   signature: str,
                                   signature_kid: str) -> CheckpointRef: ...

    async def fetch_checkpoint(self,
                                 head_seq: int
                                 ) -> Optional[CheckpointRef]: ...
