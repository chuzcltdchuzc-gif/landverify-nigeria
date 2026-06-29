"""EncryptionPort — Phase 3.2 cryptographic abstraction.

The domain depends ONLY on this Protocol. No application or domain
code may import `nacl` directly; concrete adapters (Software KMS,
AWS KMS, Azure Key Vault, GCP KMS, HashiCorp Vault, HSM, Government
PKI) plug in here.

Binding rules (Phase 3.2 operator directives §1 + §4):

* Per-tenant DEK wrapped by per-country master. DEKs never persist in
  plaintext.
* Cross-country DEK unwrap is **DENIED BY DEFAULT**. Override requires
  the Break-Glass procedure (`BreakGlassChallenge` + super_admin +
  explicit reason + immutable audit + `SecurityIncident` event).
* Dual-authorization design: every unwrap exposes a
  `requires_dual_auth` flag; the Software adapter accepts a single
  approval initially (stubbed) so the API contract is ready for the
  two-person rule when operators wire in the second approver.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator, Optional, Protocol


# ---- Value objects ------------------------------------------------------

@dataclass(frozen=True)
class TenantDekRef:
    """Opaque pointer to a tenant DEK. Plaintext key never leaves the
    adapter; the application carries only this reference + the envelope."""
    tenant_dek_id: str
    tenant_id: str
    country: str
    created_at: datetime


@dataclass(frozen=True)
class EncryptionEnvelope:
    """The exact metadata persisted next to every encrypted field/object.

    Stored verbatim on the EvidenceItem aggregate (Phase 3.4) and on any
    field-level encrypted scalar (Phase 3.2 §2). Adapters MUST round-trip
    this envelope identically across encrypt/decrypt.
    """
    kms_id: str                       # "software_kms_v1" | "aws_kms_v1" | ...
    tenant_dek_id: str
    country_master_kid: str
    wrap_alg: str                     # "xsalsa20-poly1305"
    nonce_b64: str                    # base64url nonce used by the DEK
    schema: int = 1

    def to_dict(self) -> dict:
        return {
            "kms_id": self.kms_id,
            "tenant_dek_id": self.tenant_dek_id,
            "country_master_kid": self.country_master_kid,
            "wrap_alg": self.wrap_alg,
            "nonce_b64": self.nonce_b64,
            "schema": self.schema,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EncryptionEnvelope":
        return cls(
            kms_id=d["kms_id"], tenant_dek_id=d["tenant_dek_id"],
            country_master_kid=d["country_master_kid"],
            wrap_alg=d["wrap_alg"], nonce_b64=d["nonce_b64"],
            schema=int(d.get("schema", 1)),
        )


@dataclass(frozen=True)
class BreakGlassChallenge:
    """Mandatory context for any cross-country unwrap (residency override).

    All fields are recorded in an immutable audit + `SecurityIncident`
    event. The Software adapter accepts a single `approver_principal_id`
    today; production adapters MUST enforce that
    `requires_dual_auth=True` requests carry a second, distinct
    `second_approver_principal_id` and `second_approver_signature`.
    """
    requesting_principal_id: str
    requesting_role: str               # must include super_admin
    request_country: str               # principal's country
    target_country: str                # DEK country
    reason_code: str                   # operator-defined enum (LITIGATION, REGULATOR_ORDER, …)
    reason_detail: str                 # free text, recorded verbatim
    correlation_id: str
    second_approver_principal_id: Optional[str] = None
    second_approver_signature: Optional[str] = None

    def is_dual_authorized(self) -> bool:
        return bool(self.second_approver_principal_id
                    and self.second_approver_signature)


# ---- Protocol -----------------------------------------------------------

class EncryptionPort(Protocol):
    """Universal envelope-encryption interface."""

    kms_id: str

    # ----- key management ------------------------------------------------

    async def ensure_country_master(self, *, country: str) -> str:
        """Idempotent. Returns the master `key_id` for `country`. Generates
        on first use; never replaces an existing master."""
        ...

    async def get_or_create_tenant_dek(self, *, tenant_id: str,
                                       country: str) -> TenantDekRef: ...

    # ----- encrypt / decrypt --------------------------------------------

    async def encrypt_bytes(self, *, dek_ref: TenantDekRef,
                            plaintext: bytes) -> tuple[bytes, EncryptionEnvelope]:
        """Encrypt a single bytes blob (used for field-level scalar PII)."""
        ...

    async def decrypt_bytes(self, *, envelope: EncryptionEnvelope,
                            ciphertext: bytes,
                            break_glass: Optional[BreakGlassChallenge] = None
                            ) -> bytes:
        """Decrypt a single bytes blob.

        Cross-country requests (caller's country != envelope country)
        MUST supply a valid `break_glass`; otherwise the call is
        denied + audited as a residency violation.
        """
        ...

    async def encrypt_stream(self, *, dek_ref: TenantDekRef,
                             plaintext: AsyncIterator[bytes],
                             chunk_size: int = 65536
                             ) -> tuple[AsyncIterator[bytes],
                                         EncryptionEnvelope]:
        """Streaming encryption for binaries (used by Phase 3.5 sealing).

        Returns the ciphertext iterator + the envelope. The envelope
        nonce covers the entire stream — chunks are sequentially
        encrypted under the same DEK with a deterministic per-chunk
        counter prepended internally.
        """
        ...

    async def decrypt_stream(self, *, envelope: EncryptionEnvelope,
                             ciphertext: AsyncIterator[bytes],
                             break_glass: Optional[BreakGlassChallenge] = None
                             ) -> AsyncIterator[bytes]: ...

    # ----- residency / break-glass --------------------------------------

    def residency_country_of(self, envelope: EncryptionEnvelope) -> str:
        """Return the country whose master key wraps the DEK referenced
        by `envelope`. Used by the application service to compare against
        the caller's ExecutionContext.country before invoking decrypt."""
        ...


# ---- Errors -------------------------------------------------------------

class ResidencyViolation(Exception):
    """Raised when a cross-country unwrap is attempted without a valid
    Break-Glass challenge (or with an insufficient one)."""


class BreakGlassRejected(Exception):
    """Raised when a Break-Glass challenge fails validation
    (missing reason, wrong role, dual-auth required but absent)."""
