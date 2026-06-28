"""Registry value objects + canonical enums.

Each value object validates its own invariants at construction. Once
constructed, they are immutable (`frozen=True`).
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

# ---- Identifiers ---------------------------------------------------------

_PARCEL_NUMBER_RE = re.compile(
    r"^[A-Z0-9]{2,16}-[A-Z0-9]{2,16}-[A-Z0-9]{2,16}-[A-Z]{3}-\d{6}$"
)


def new_registry_id() -> str:
    """Generate a new immutable internal registry identifier."""
    return "reg_" + uuid.uuid4().hex


@dataclass(frozen=True)
class ParcelNumber:
    """Canonical public reference: STATE-LGA-WARD-PROPTYPE-NNNNNN."""
    value: str

    def __post_init__(self) -> None:
        if not _PARCEL_NUMBER_RE.match(self.value):
            raise ValueError(
                f"invalid parcel_number {self.value!r}; expected "
                "STATE-LGA-WARD-PROPTYPE-NNNNNN (PROPTYPE 3 letters, "
                "sequence 6 digits)"
            )

    @property
    def sequence_key(self) -> str:
        """Composite key for the allocator counter (everything before the sequence)."""
        return "-".join(self.value.split("-")[:-1])

    @property
    def sequence_number(self) -> int:
        return int(self.value.split("-")[-1])

    def __str__(self) -> str:
        return self.value


# ---- Enumerations --------------------------------------------------------

class PropertyType(str, Enum):
    RESIDENTIAL = "RES"
    COMMERCIAL = "COM"
    FARM = "FRM"
    MARKET = "MKT"
    SHOP = "SHP"
    SETTLEMENT = "STL"
    KIOSK = "KSK"
    GOVERNMENT = "GOV"
    INSTITUTIONAL = "INS"


class OwnershipType(str, Enum):
    INDIVIDUAL = "individual"
    FAMILY = "family"
    JOINT = "joint"
    COMMUNITY = "community"
    TRUST = "trust"
    CORPORATE = "corporate"
    GOVERNMENT = "government"
    INSTITUTIONAL = "institutional"


class LandVaultStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    SURVEY_ASSIGNED = "survey_assigned"
    SURVEY_IN_PROGRESS = "survey_in_progress"
    SURVEY_COMPLETE = "survey_complete"
    DOCUMENTATION_COMPLETE = "documentation_complete"
    PENDING = "pending"
    APPROVED = "approved"
    APPROVED_LOCKED = "approved_locked"
    CERTIFICATE_READY = "certificate_ready"
    CERTIFICATE_ISSUED = "certificate_issued"
    REJECTED = "rejected"
    DISPUTED = "disputed"
    TRANSFERRED = "transferred"
    FROZEN = "frozen"
    ARCHIVED = "archived"


# Statuses that lock owner-side mutation (Phase 2 Spec §3.3, mirrors
# `kernel.authorization.policy_library.LOCKED_STATES`).
LOCKED_STATUSES: frozenset[str] = frozenset({
    LandVaultStatus.APPROVED_LOCKED.value,
    LandVaultStatus.CERTIFICATE_ISSUED.value,
    LandVaultStatus.ARCHIVED.value,
})

EVIDENCE_SEALED_LOCK = "evidence_sealed"  # invariant: dynamic flag, not a status


# ---- Geometry ------------------------------------------------------------

@dataclass(frozen=True)
class Geometry:
    """GeoJSON Polygon (WGS84). Validated; `2dsphere`-indexed on persistence."""
    type: str
    coordinates: list

    def __post_init__(self) -> None:
        if self.type != "Polygon":
            raise ValueError("registry geometry must be GeoJSON Polygon")
        if not isinstance(self.coordinates, list) or not self.coordinates:
            raise ValueError("polygon coordinates must be a non-empty list of rings")
        for ring in self.coordinates:
            if not isinstance(ring, list) or len(ring) < 4:
                raise ValueError("polygon ring must have at least 4 positions")
            for pt in ring:
                if (not isinstance(pt, (list, tuple)) or len(pt) < 2
                        or not all(isinstance(c, (int, float)) for c in pt[:2])):
                    raise ValueError("polygon point must be [lon, lat]")
                lon, lat = pt[0], pt[1]
                if not (-180.0 <= lon <= 180.0) or not (-90.0 <= lat <= 90.0):
                    raise ValueError(f"polygon coordinate out of range: {pt!r}")
            if ring[0] != ring[-1]:
                raise ValueError("polygon ring must be closed (first==last)")

    def to_dict(self) -> dict:
        return {"type": self.type, "coordinates": self.coordinates}


# ---- Provenance ----------------------------------------------------------

class SourceSystem(str, Enum):
    LAND_PARCEL = "LandParcel"           # legacy
    LAND_VAULT_PARCEL = "LandVaultParcel"  # legacy
    NATIVE = "native"                    # created in the canonical registry


@dataclass(frozen=True)
class Origin:
    """Immutable provenance — never rewritten after first migration/creation."""
    source_system: str
    source_id: Optional[str] = None
    import_batch: Optional[str] = None

    def __post_init__(self) -> None:
        if self.source_system not in {s.value for s in SourceSystem}:
            raise ValueError(f"invalid origin.source_system: {self.source_system!r}")

    def to_dict(self) -> dict:
        return {
            "source_system": self.source_system,
            "source_id": self.source_id,
            "import_batch": self.import_batch,
        }


# ---- Ownership snapshot (append-only history element) -------------------

@dataclass(frozen=True)
class OwnershipSnapshot:
    """An entry in the append-only OwnershipHistory.

    Per Phase 2A architectural authorization §3: ownership events represent
    LEGAL ownership changes, not ordinary profile edits.
    """
    ownership_type: str
    owner_name: str
    recorded_at: str
    recorded_by: Optional[str] = None
    reason: Optional[str] = None
    representative_name: Optional[str] = None
    representative_authority: Optional[str] = None
    family_head: Optional[str] = None

    def __post_init__(self) -> None:
        if self.ownership_type not in {o.value for o in OwnershipType}:
            raise ValueError(f"invalid ownership_type: {self.ownership_type!r}")
        if not self.owner_name or not self.owner_name.strip():
            raise ValueError("owner_name must not be empty")

    def to_dict(self) -> dict:
        return {k: v for k, v in {
            "ownership_type": self.ownership_type,
            "owner_name": self.owner_name,
            "recorded_at": self.recorded_at,
            "recorded_by": self.recorded_by,
            "reason": self.reason,
            "representative_name": self.representative_name,
            "representative_authority": self.representative_authority,
            "family_head": self.family_head,
        }.items() if v is not None}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
