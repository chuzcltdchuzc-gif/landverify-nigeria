"""StoragePort + SignedUrlPort + value objects for Phase 3.1.

These two ports cover the storage foundation for the Evidence context:

* `StoragePort` is the universal interface for evidence binaries. It is
  responsible for the 2-tier bucket model (public for derivatives that
  the platform explicitly publishes; private for everything else),
  multipart streaming uploads, server-side encryption at rest, WORM
  object-lock primitives, and the read-back stream that the server-side
  hashing pipeline (ADR-0004 / Phase 3.5) consumes.

* `SignedUrlPort` is the universal interface for issuing short-lived
  pre-signed URLs. It MUST synchronously write an audit record to the
  `evidence_signed_url_audit` collection BEFORE returning the URL. The
  port deliberately couples issuance and audit so adapters cannot ship a
  URL without leaving a forensic trail.

Binding invariants encoded here (compile-time):
* `Tier.PUBLIC` and `Tier.PRIVATE` are exhaustive — no third tier.
* `WORM_MODE_COMPLIANCE` is the only legal mode for sealed evidence;
  governance mode is rejected by `apply_object_lock`.
* `MAX_SIGNED_URL_TTL_SECONDS` is platform-wide (1 hour); per-role caps
  are tighter (`SignedUrlAuditCtx.requested_ttl_seconds`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import AsyncIterator, Awaitable, Callable, Optional, Protocol


# ---- Value objects -------------------------------------------------------

class StorageTier(str, Enum):
    """Phase 3.1 §1 — strict 2-tier storage."""
    PUBLIC = "public"
    PRIVATE = "private"


class StorageProviderId(str, Enum):
    LOCAL_FS_WORM = "local_fs_worm"
    R2 = "r2"


WORM_MODE_COMPLIANCE = "compliance"
MAX_SIGNED_URL_TTL_SECONDS = 3600          # 1h hard cap
DEFAULT_SIGNED_URL_TTL_SECONDS = 300       # 5min default


@dataclass(frozen=True)
class StorageObjectKey:
    """Canonical object key — never a raw path.

    Layout: ``<tier>/<tenant>/<yyyy>/<mm>/<dd>/<evidence_id>/<part_or_final>``

    The composition root creates these via :func:`canonical_key`. Callers
    NEVER assemble paths themselves; the storage adapter is the only
    place that knows how to translate a `StorageObjectKey` into a
    filesystem path or an S3 object name.
    """
    tier: StorageTier
    tenant_id: str
    yyyy: str
    mm: str
    dd: str
    evidence_id: str
    suffix: str  # "final" | "part-0001" | … | "manifest"

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("storage key tenant_id must not be empty")
        if not self.evidence_id:
            raise ValueError("storage key evidence_id must not be empty")
        # YYYY/MM/DD basic validation
        if (len(self.yyyy) != 4 or not self.yyyy.isdigit()
                or len(self.mm) != 2 or not self.mm.isdigit()
                or len(self.dd) != 2 or not self.dd.isdigit()):
            raise ValueError(
                f"invalid date components: {self.yyyy}/{self.mm}/{self.dd}")
        if not self.suffix or "/" in self.suffix:
            raise ValueError(f"invalid object suffix: {self.suffix!r}")

    def as_str(self) -> str:
        return (f"{self.tier.value}/{self.tenant_id}/{self.yyyy}/"
                f"{self.mm}/{self.dd}/{self.evidence_id}/{self.suffix}")


def canonical_key(*, tier: StorageTier, tenant_id: str,
                  evidence_id: str, suffix: str,
                  when: Optional[datetime] = None) -> StorageObjectKey:
    from datetime import datetime as _dt, timezone as _tz
    t = when or _dt.now(_tz.utc)
    return StorageObjectKey(
        tier=tier, tenant_id=tenant_id,
        yyyy=f"{t.year:04d}", mm=f"{t.month:02d}", dd=f"{t.day:02d}",
        evidence_id=evidence_id, suffix=suffix,
    )


@dataclass(frozen=True)
class MultipartHandle:
    """Opaque, adapter-defined session identifier for an in-progress upload."""
    upload_id: str
    key: StorageObjectKey
    max_size: int
    media_type: str


@dataclass(frozen=True)
class PartReceipt:
    """Returned by `StoragePort.upload_part`. Carries the server-streamed
    SHA-256 of the part bytes (foundation for ADR-0004 server-side hashing)."""
    part_no: int
    size_bytes: int
    streamed_sha256: str


@dataclass(frozen=True)
class StoredObject:
    """Returned by `StoragePort.complete_multipart`. Carries the running
    SHA-256 hash that the server computed across all parts as the bytes
    were written (this is the "streamed-during-write" pass of ADR-0004)."""
    key: StorageObjectKey
    provider_id: str
    size_bytes: int
    streamed_sha256: str
    media_type: str


@dataclass(frozen=True)
class ObjectLockStatus:
    locked: bool
    mode: Optional[str]
    retention_until: Optional[datetime]
    applied_at: Optional[datetime]
    applied_by: Optional[str]


@dataclass(frozen=True)
class SignedUrlAuditCtx:
    """Mandatory audit context — every `issue` call carries this.

    Adapters MUST persist these fields to `evidence_signed_url_audit`
    BEFORE handing the URL back to the caller.
    """
    principal_id: str
    principal_role: str
    tenant_id: str
    country: str
    evidence_id: str
    action: str          # "read" | "verify" | "export"
    requested_ttl_seconds: int
    request_ip: Optional[str] = None
    user_agent: Optional[str] = None
    correlation_id: Optional[str] = None


@dataclass(frozen=True)
class SignedUrl:
    url: str
    expires_at: datetime
    audit_id: str
    url_sha256: str


# ---- Protocols -----------------------------------------------------------

# Type alias for the verify_callback used during remediation moves
# (defined here so adapters and the saga share one signature).
VerifyCallback = Callable[[bytes], Awaitable[None]]


class StoragePort(Protocol):
    """Universal binary-storage interface.

    Implementations: ``adapters/fs_worm_storage.py`` (LocalFs WORM, dev),
    ``adapters/r2_storage.py`` (Cloudflare R2, production).
    """
    provider_id: str

    # --- multipart streaming upload --------------------------------------

    async def initiate_multipart(self, *, key: StorageObjectKey,
                                 media_type: str, max_size: int
                                 ) -> MultipartHandle: ...

    async def upload_part(self, handle: MultipartHandle, *, part_no: int,
                          stream: AsyncIterator[bytes]) -> PartReceipt: ...

    async def complete_multipart(self, handle: MultipartHandle, *,
                                 parts: list[PartReceipt]
                                 ) -> StoredObject: ...

    async def abort_multipart(self, handle: MultipartHandle) -> None: ...

    # --- read-back streaming hash (ADR-0004) -----------------------------

    async def open_for_streaming_hash(self, key: StorageObjectKey
                                       ) -> AsyncIterator[bytes]:
        """Yields plaintext bytes from the stored object, in chunks.

        Used by the server-side hashing pipeline to do an INDEPENDENT
        read-back pass. The plaintext-side requirement is binding even
        when the bytes are envelope-encrypted at rest — the adapter
        decrypts on the fly using the encryption port (wired by the
        composition root).
        """
        ...

    # --- WORM (object-lock) ---------------------------------------------

    async def apply_object_lock(self, key: StorageObjectKey, *,
                                retention_until: datetime,
                                mode: str = WORM_MODE_COMPLIANCE,
                                applied_by: str) -> ObjectLockStatus: ...

    async def extend_object_lock(self, key: StorageObjectKey, *,
                                 retention_until: datetime,
                                 extended_by: str) -> ObjectLockStatus: ...

    async def lock_status(self, key: StorageObjectKey) -> ObjectLockStatus: ...

    # --- remediation (verify-then-cutover) ------------------------------

    async def move(self, *, src: StorageObjectKey, dst: StorageObjectKey,
                   verify_callback: VerifyCallback) -> StoredObject:
        """Copy bytes from `src` to `dst` while streaming them through
        `verify_callback` (which typically updates a running SHA-256).
        The source object is NEVER deleted by this method — that
        decision belongs to the remediation saga after an independent
        read-back verifies the destination."""
        ...


class SignedUrlPort(Protocol):
    """Issues short-lived signed URLs and writes the audit row BEFORE
    handing the URL back to the caller. Adapters that ship the URL
    before persisting the audit are non-compliant."""

    async def issue(self, *, key: StorageObjectKey,
                    ttl_seconds: int = DEFAULT_SIGNED_URL_TTL_SECONDS,
                    audit: SignedUrlAuditCtx) -> SignedUrl: ...


# ---- Helpers (port-level guards) ----------------------------------------

def clamp_ttl(requested: int, *, role: str) -> int:
    """Clamp a requested TTL by the platform cap + per-role tier."""
    if requested < 30:
        requested = 30
    if requested > MAX_SIGNED_URL_TTL_SECONDS:
        requested = MAX_SIGNED_URL_TTL_SECONDS
    # Per-role tier caps. Governance roles can issue longer-lived URLs
    # for batch downloads; operational roles are deliberately short.
    role_cap = {
        "super_admin": 3600,
        "compliance_officer": 1800,
        "surveyor_general": 1800,
        "government_observer": 1800,
        "licensed_surveyor": 900,
        "surveyor": 600,
        "surveyor_partner": 600,
        "field_agent": 300,
        "community_validator": 300,
        "general_user": 300,
    }.get(role, 300)
    return min(requested, role_cap)
