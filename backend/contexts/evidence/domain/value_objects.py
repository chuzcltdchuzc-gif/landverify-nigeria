"""Evidence domain value objects + enums (Phase 3.4).

Each value object validates its own invariants at construction. Once
constructed they are immutable. Module deliberately depends only on
stdlib so the domain stays infrastructure-agnostic.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

# ---- Identifiers ---------------------------------------------------------

_EVIDENCE_ID_RE = re.compile(r"^evd_[a-f0-9]{32}$")
_SEAL_ID_RE = re.compile(r"^sea_[a-f0-9]{32}$")
_REGISTRY_ID_RE = re.compile(r"^reg_[a-f0-9]{32}$")
_HEX_RE = re.compile(r"^[a-f0-9]{64}$")


def new_evidence_id() -> str:
    return "evd_" + uuid.uuid4().hex


def new_seal_id() -> str:
    return "sea_" + uuid.uuid4().hex


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- Enums ---------------------------------------------------------------

class EvidenceKind(str, Enum):
    DOCUMENT = "document"
    PHOTO = "photo"
    VIDEO = "video"
    AUDIO = "audio"
    SIGNED_DOC = "signed_doc"
    FIELD_CAPTURE_BUNDLE = "field_capture_bundle"


class EvidenceStatus(str, Enum):
    PENDING_UPLOAD = "pending_upload"
    PENDING_VERIFICATION = "pending_verification"
    VERIFIED = "verified"
    SEALED = "sealed"
    ARCHIVED_REPLACED = "archived_replaced"


class SealStatus(str, Enum):
    CREATED = "created"
    WORM_APPLIED = "worm_applied"
    ARCHIVED = "archived"


# Statuses after which the EvidenceItem becomes immutable to ordinary edits.
SEALED_LIKE_STATUSES = frozenset({
    EvidenceStatus.SEALED.value,
    EvidenceStatus.ARCHIVED_REPLACED.value,
})


# ---- Provenance ----------------------------------------------------------

class EvidenceSourceSystem(str, Enum):
    NATIVE = "native"
    LEGACY_REMEDIATION = "legacy_remediation"
    OFFLINE_CAPTURE = "offline_capture"


@dataclass(frozen=True)
class Origin:
    """Immutable provenance — never rewritten after first persist."""
    source_system: str
    source_id: Optional[str] = None
    import_batch: Optional[str] = None

    def __post_init__(self) -> None:
        if self.source_system not in {s.value for s in EvidenceSourceSystem}:
            raise ValueError(
                f"invalid origin.source_system: {self.source_system!r}")

    def to_dict(self) -> dict:
        return {
            "source_system": self.source_system,
            "source_id": self.source_id,
            "import_batch": self.import_batch,
        }


# ---- Hash + media type ---------------------------------------------------

@dataclass(frozen=True)
class ContentHash:
    """SHA-256 hex digest. The platform supports SHA-256 only in v1."""
    value: str
    algorithm: str = "SHA-256"

    def __post_init__(self) -> None:
        if self.algorithm != "SHA-256":
            raise ValueError(
                f"only SHA-256 supported in v1; got {self.algorithm!r}")
        if not _HEX_RE.match(self.value):
            raise ValueError(f"invalid SHA-256 hex digest: {self.value!r}")


# ---- Merkle root ---------------------------------------------------------

def compute_merkle_root(leaves: list[str]) -> str:
    """Canonical merkle root over SHA-256 hex-encoded leaves.

    Phase 3.5: the seal manifest's merkle_root is computed over the
    sorted list of evidence server_hashes. Sorting makes the result
    deterministic regardless of the order in which the operator
    selected items into the seal. Single-leaf seals return the leaf
    unchanged. Odd-leaf levels duplicate the last node — the standard
    bitcoin-style canonical merkle.
    """
    if not leaves:
        raise ValueError("merkle root requires at least one leaf")
    for leaf in leaves:
        if not _HEX_RE.match(leaf):
            raise ValueError(f"merkle leaf not SHA-256 hex: {leaf!r}")
    nodes = sorted(leaves)
    if len(nodes) == 1:
        return nodes[0]
    while len(nodes) > 1:
        new_level: list[str] = []
        for i in range(0, len(nodes), 2):
            a = nodes[i]
            b = nodes[i + 1] if i + 1 < len(nodes) else nodes[i]
            new_level.append(hashlib.sha256((a + b).encode("ascii")).hexdigest())
        nodes = new_level
    return nodes[0]


def canonical_json_hash(doc: dict) -> str:
    """Deterministic sha256 hex of a canonical JSON encoding of `doc`."""
    encoded = json.dumps(doc, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
