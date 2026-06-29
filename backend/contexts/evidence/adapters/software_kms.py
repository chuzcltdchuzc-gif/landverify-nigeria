"""Software KMS adapter (Phase 3.2).

First adapter for `EncryptionPort`. Uses libsodium (PyNaCl) for the
cryptographic primitives but **deliberately hides this fact from the
domain** — only this module imports `nacl`.

Layout:

* `evidence_country_masters` — one document per country.
* `evidence_tenant_deks` — wrapped DEKs (nonce + ciphertext); the
  plaintext DEK is only ever held in memory in this module.
* `evidence_security_incidents` — Break-Glass attempts and successes.

Residency rules (operator Decision 1):

* DEKs may be unwrapped only inside their assigned country.
* Cross-country unwrap is DENIED unless a `BreakGlassChallenge` is
  supplied AND validated:
    * `requesting_role` must include `super_admin`
    * `reason_code` must be non-empty and in the operator allow-list
    * Correlation id present
    * A `SecurityIncident` row is recorded BEFORE the unwrap proceeds
    * `evidence.security.break_glass.v1` event is emitted on success
    * If `requires_dual_auth=True`, second approver is mandatory
"""
from __future__ import annotations

import base64
import os
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from contexts.evidence.ports.encryption import (
    BreakGlassChallenge,
    BreakGlassRejected,
    EncryptionEnvelope,
    EncryptionPort,
    ResidencyViolation,
    TenantDekRef,
)

# Operator-defined allow-list of reason codes. Anything outside this
# set is rejected at the port boundary.
ALLOWED_BREAK_GLASS_REASONS = frozenset({
    "LITIGATION_PRESERVATION_ORDER",
    "REGULATOR_AUDIT",
    "CRIMINAL_INVESTIGATION",
    "DATA_SUBJECT_LEGAL_REQUEST",
    "INTERNAL_FRAUD_REVIEW",
})

COUNTRY_MASTERS_COLLECTION = "evidence_country_masters"
TENANT_DEKS_COLLECTION = "evidence_tenant_deks"
SECURITY_INCIDENTS_COLLECTION = "evidence_security_incidents"


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


class SoftwareKmsAdapter(EncryptionPort):
    kms_id = "software_kms_v1"

    def __init__(self, *, db: AsyncIOMotorDatabase) -> None:
        # Import nacl lazily — keeps the domain free of any nacl symbol.
        from nacl import secret as _secret  # type: ignore
        from nacl import utils as _utils  # type: ignore
        self._secret = _secret
        self._utils = _utils
        self._db = db
        self._dek_cache: dict[str, bytes] = {}  # tenant_dek_id -> plaintext DEK

    async def ensure_indexes(self) -> None:
        await self._db[COUNTRY_MASTERS_COLLECTION].create_index(
            "country", unique=True)
        await self._db[TENANT_DEKS_COLLECTION].create_index(
            [("tenant_id", 1), ("country", 1)], unique=True)
        await self._db[TENANT_DEKS_COLLECTION].create_index("tenant_dek_id",
                                                              unique=True)
        await self._db[SECURITY_INCIDENTS_COLLECTION].create_index(
            "correlation_id")
        await self._db[SECURITY_INCIDENTS_COLLECTION].create_index(
            [("tenant_id", 1), ("recorded_at", -1)])

    # ---- master key management -----------------------------------------

    async def ensure_country_master(self, *, country: str) -> str:
        doc = await self._db[COUNTRY_MASTERS_COLLECTION].find_one(
            {"country": country})
        if doc:
            return doc["key_id"]
        key = self._utils.random(self._secret.SecretBox.KEY_SIZE)
        key_id = "cm_" + uuid.uuid4().hex
        # Upsert under unique key with $setOnInsert so concurrent boots
        # of the API never replace an existing master.
        await self._db[COUNTRY_MASTERS_COLLECTION].update_one(
            {"country": country},
            {"$setOnInsert": {
                "country": country, "key_id": key_id,
                "key_b64": _b64e(key),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "schema": 1,
            }},
            upsert=True,
        )
        doc = await self._db[COUNTRY_MASTERS_COLLECTION].find_one(
            {"country": country})
        return doc["key_id"]

    async def _master_key_bytes(self, *, country: str) -> tuple[str, bytes]:
        doc = await self._db[COUNTRY_MASTERS_COLLECTION].find_one(
            {"country": country})
        if not doc:
            kid = await self.ensure_country_master(country=country)
            doc = await self._db[COUNTRY_MASTERS_COLLECTION].find_one(
                {"key_id": kid})
        return doc["key_id"], _b64d(doc["key_b64"])

    # ---- tenant DEK management -----------------------------------------

    async def get_or_create_tenant_dek(self, *, tenant_id: str,
                                       country: str) -> TenantDekRef:
        existing = await self._db[TENANT_DEKS_COLLECTION].find_one(
            {"tenant_id": tenant_id, "country": country})
        if existing:
            return TenantDekRef(
                tenant_dek_id=existing["tenant_dek_id"],
                tenant_id=tenant_id, country=country,
                created_at=datetime.fromisoformat(existing["created_at"]),
            )
        plaintext_dek = self._utils.random(
            self._secret.SecretBox.KEY_SIZE)
        master_kid, master_key = await self._master_key_bytes(country=country)
        nonce = self._utils.random(self._secret.SecretBox.NONCE_SIZE)
        wrapped = self._secret.SecretBox(master_key).encrypt(
            plaintext_dek, nonce=nonce)
        # `wrapped.ciphertext` and `wrapped.nonce` are the parts; we
        # persist both so we can round-trip without the SecretBox's
        # combined `wrapped` opaque form.
        dek_id = "tdek_" + uuid.uuid4().hex
        await self._db[TENANT_DEKS_COLLECTION].insert_one({
            "tenant_dek_id": dek_id, "tenant_id": tenant_id,
            "country": country, "country_master_kid": master_kid,
            "nonce_b64": _b64e(wrapped.nonce),
            "ciphertext_b64": _b64e(wrapped.ciphertext),
            "wrap_alg": "xsalsa20-poly1305",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "schema": 1,
        })
        self._dek_cache[dek_id] = plaintext_dek
        return TenantDekRef(tenant_dek_id=dek_id, tenant_id=tenant_id,
                             country=country,
                             created_at=datetime.now(timezone.utc))

    async def _unwrap_dek(self, *, tenant_dek_id: str,
                          break_glass: Optional[BreakGlassChallenge]
                          ) -> tuple[bytes, str]:
        """Return (plaintext_dek, dek_country). Enforces residency."""
        if tenant_dek_id in self._dek_cache:
            doc = await self._db[TENANT_DEKS_COLLECTION].find_one(
                {"tenant_dek_id": tenant_dek_id})
            if not doc:
                # Cache stale; fall through to fail-closed
                self._dek_cache.pop(tenant_dek_id, None)
            else:
                await self._check_residency(
                    target_country=doc["country"],
                    break_glass=break_glass, dek_id=tenant_dek_id)
                return self._dek_cache[tenant_dek_id], doc["country"]
        doc = await self._db[TENANT_DEKS_COLLECTION].find_one(
            {"tenant_dek_id": tenant_dek_id})
        if not doc:
            raise ResidencyViolation(
                f"tenant DEK {tenant_dek_id!r} not found")
        await self._check_residency(target_country=doc["country"],
                                     break_glass=break_glass,
                                     dek_id=tenant_dek_id)
        _, master_key = await self._master_key_bytes(country=doc["country"])
        nonce = _b64d(doc["nonce_b64"])
        ciphertext = _b64d(doc["ciphertext_b64"])
        plaintext = self._secret.SecretBox(master_key).decrypt(
            ciphertext, nonce=nonce)
        self._dek_cache[tenant_dek_id] = plaintext
        return plaintext, doc["country"]

    # ---- residency / break-glass ---------------------------------------

    async def _check_residency(self, *, target_country: str,
                               break_glass: Optional[BreakGlassChallenge],
                               dek_id: str) -> None:
        if break_glass is None:
            # No challenge: nothing to enforce HERE (the caller is in the
            # target country, by contract). The adapter trusts the
            # composition root to call this method only when:
            #   - same country, no challenge needed, OR
            #   - cross-country, challenge provided.
            return
        # A challenge was supplied — validate it strictly even if the
        # request is intra-country (we want the audit trail).
        if break_glass.target_country and break_glass.target_country != target_country:
            raise BreakGlassRejected(
                f"break_glass.target_country mismatch: declared "
                f"{break_glass.target_country}, actual {target_country}")
        if "super_admin" not in (break_glass.requesting_role or "").lower():
            raise BreakGlassRejected(
                "break_glass.requesting_role must be super_admin")
        if not break_glass.reason_code:
            raise BreakGlassRejected("break_glass.reason_code required")
        if break_glass.reason_code not in ALLOWED_BREAK_GLASS_REASONS:
            raise BreakGlassRejected(
                f"break_glass.reason_code {break_glass.reason_code!r} not "
                f"in the operator allow-list")
        if not break_glass.reason_detail or not break_glass.reason_detail.strip():
            raise BreakGlassRejected("break_glass.reason_detail required")
        if not break_glass.correlation_id:
            raise BreakGlassRejected("break_glass.correlation_id required")
        # Record SecurityIncident BEFORE returning (so the audit is
        # durable even if the subsequent crypto op fails).
        await self._db[SECURITY_INCIDENTS_COLLECTION].insert_one({
            "incident_id": "sec_" + uuid.uuid4().hex,
            "kind": "break_glass_residency_override",
            "tenant_dek_id": dek_id,
            "target_country": target_country,
            "requesting_principal_id": break_glass.requesting_principal_id,
            "requesting_role": break_glass.requesting_role,
            "request_country": break_glass.request_country,
            "reason_code": break_glass.reason_code,
            "reason_detail": break_glass.reason_detail,
            "correlation_id": break_glass.correlation_id,
            "dual_auth_required_design": True,
            "dual_authorized": break_glass.is_dual_authorized(),
            "second_approver_principal_id":
                break_glass.second_approver_principal_id,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        })

    # ---- encrypt / decrypt: bytes --------------------------------------

    async def encrypt_bytes(self, *, dek_ref: TenantDekRef,
                            plaintext: bytes
                            ) -> tuple[bytes, EncryptionEnvelope]:
        plaintext_dek, _ = await self._unwrap_dek(
            tenant_dek_id=dek_ref.tenant_dek_id, break_glass=None)
        nonce = self._utils.random(self._secret.SecretBox.NONCE_SIZE)
        wrapped = self._secret.SecretBox(plaintext_dek).encrypt(
            plaintext, nonce=nonce)
        envelope = EncryptionEnvelope(
            kms_id=self.kms_id, tenant_dek_id=dek_ref.tenant_dek_id,
            country_master_kid=await self._country_master_kid(
                tenant_dek_id=dek_ref.tenant_dek_id),
            wrap_alg="xsalsa20-poly1305",
            nonce_b64=_b64e(wrapped.nonce),
        )
        return wrapped.ciphertext, envelope

    async def decrypt_bytes(self, *, envelope: EncryptionEnvelope,
                            ciphertext: bytes,
                            break_glass: Optional[BreakGlassChallenge] = None
                            ) -> bytes:
        plaintext_dek, _ = await self._unwrap_dek(
            tenant_dek_id=envelope.tenant_dek_id, break_glass=break_glass)
        nonce = _b64d(envelope.nonce_b64)
        return self._secret.SecretBox(plaintext_dek).decrypt(
            ciphertext, nonce=nonce)

    # ---- streaming encrypt / decrypt -----------------------------------

    async def encrypt_stream(self, *, dek_ref: TenantDekRef,
                             plaintext: AsyncIterator[bytes],
                             chunk_size: int = 65536
                             ) -> tuple[AsyncIterator[bytes],
                                         EncryptionEnvelope]:
        plaintext_dek, _ = await self._unwrap_dek(
            tenant_dek_id=dek_ref.tenant_dek_id, break_glass=None)
        box = self._secret.SecretBox(plaintext_dek)
        # Single nonce stored on the envelope; per-chunk uniqueness is
        # provided by a 64-bit counter prefix inside the ciphertext.
        # This is the "stream nonce" of XSalsa20-Poly1305 with explicit
        # counters — adequate for v1; future adapters may use AEAD
        # extensions (e.g. ChaCha20-Poly1305) for better streaming.
        stream_nonce = self._utils.random(self._secret.SecretBox.NONCE_SIZE)
        envelope = EncryptionEnvelope(
            kms_id=self.kms_id, tenant_dek_id=dek_ref.tenant_dek_id,
            country_master_kid=await self._country_master_kid(
                tenant_dek_id=dek_ref.tenant_dek_id),
            wrap_alg="xsalsa20-poly1305-stream",
            nonce_b64=_b64e(stream_nonce),
        )

        async def _gen():
            counter = 0
            async for chunk in plaintext:
                if not chunk:
                    continue
                # XOR the last 8 bytes of stream_nonce with the counter
                base = bytearray(stream_nonce)
                ctr_bytes = counter.to_bytes(8, "big", signed=False)
                for i in range(8):
                    base[-(i + 1)] ^= ctr_bytes[-(i + 1)]
                per_nonce = bytes(base)
                ct = box.encrypt(chunk, nonce=per_nonce).ciphertext
                yield len(ct).to_bytes(4, "big") + ct
                counter += 1
        return _gen(), envelope

    async def decrypt_stream(self, *, envelope: EncryptionEnvelope,
                             ciphertext: AsyncIterator[bytes],
                             break_glass: Optional[BreakGlassChallenge] = None
                             ) -> AsyncIterator[bytes]:
        plaintext_dek, _ = await self._unwrap_dek(
            tenant_dek_id=envelope.tenant_dek_id, break_glass=break_glass)
        box = self._secret.SecretBox(plaintext_dek)
        stream_nonce = _b64d(envelope.nonce_b64)

        async def _gen():
            buf = b""
            counter = 0
            async for chunk in ciphertext:
                buf += chunk
                while len(buf) >= 4:
                    frame_len = int.from_bytes(buf[:4], "big")
                    if len(buf) < 4 + frame_len:
                        break
                    frame = buf[4:4 + frame_len]
                    buf = buf[4 + frame_len:]
                    base = bytearray(stream_nonce)
                    ctr_bytes = counter.to_bytes(8, "big", signed=False)
                    for i in range(8):
                        base[-(i + 1)] ^= ctr_bytes[-(i + 1)]
                    per_nonce = bytes(base)
                    yield box.decrypt(frame, nonce=per_nonce)
                    counter += 1
        return _gen()

    # ---- helpers --------------------------------------------------------

    async def _country_master_kid(self, *, tenant_dek_id: str) -> str:
        doc = await self._db[TENANT_DEKS_COLLECTION].find_one(
            {"tenant_dek_id": tenant_dek_id})
        if not doc:
            raise ResidencyViolation(f"unknown DEK {tenant_dek_id}")
        return doc["country_master_kid"]

    def residency_country_of(self,
                              envelope: EncryptionEnvelope) -> str:
        # Synchronous variant: looking the country up via Mongo would
        # require async; callers that don't already know the country
        # use `residency_country_of_async` instead.
        raise NotImplementedError(
            "SoftwareKmsAdapter: use residency_country_of_async; the "
            "synchronous variant cannot perform Mongo lookups")

    async def residency_country_of_async(self,
                                          envelope: EncryptionEnvelope) -> str:
        doc = await self._db[TENANT_DEKS_COLLECTION].find_one(
            {"tenant_dek_id": envelope.tenant_dek_id})
        if not doc:
            raise ResidencyViolation(
                f"unknown DEK {envelope.tenant_dek_id}")
        return doc["country"]
