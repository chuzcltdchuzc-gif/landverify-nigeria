"""Signed-URL adapter — issues short-lived URLs AND audits BEFORE returning.

The binding contract (Phase 3.1 §1) is that no signed URL leaves the
server without a corresponding `evidence_signed_url_audit` row being
persisted FIRST. This module is the only place that produces signed
URLs; routes call `SignedUrlPort.issue(...)` and never craft their own.

The current adapter is a development-grade signer: it produces a
URL of the form ``/api/v1/evidence/blobs/<key>?signature=<hmac>&exp=<epoch>``
that the FastAPI app exposes through a dedicated route (Phase 3.7 ships
the route — at 3.1 we only need the port + audit). The signature uses
HMAC-SHA-256 with a per-process secret loaded from
``EVIDENCE_SIGNING_SECRET`` (generated at first boot, persisted in Mongo).

When R2 ships, ``R2SignedUrlAdapter`` will replace this with a real
sigv4 pre-signed URL. The audit row format is identical regardless of
provider.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from contexts.evidence.ports.storage import (
    DEFAULT_SIGNED_URL_TTL_SECONDS,
    MAX_SIGNED_URL_TTL_SECONDS,
    SignedUrl,
    SignedUrlAuditCtx,
    StorageObjectKey,
)
from kernel.errors.problem import bad_request

SIGNED_URL_AUDIT_COLLECTION = "evidence_signed_url_audit"


class SignedUrlMotorAdapter:
    """Reference implementation of `SignedUrlPort`.

    Stores audit rows in Mongo and synchronously waits for the insert to
    complete BEFORE returning the URL. If the insert fails, the URL is
    never minted.
    """

    def __init__(self, *, db: AsyncIOMotorDatabase, secret: bytes,
                 base_url: str) -> None:
        self._db = db
        self._secret = secret
        self._base_url = base_url.rstrip("/")

    async def ensure_indexes(self) -> None:
        col = self._db[SIGNED_URL_AUDIT_COLLECTION]
        await col.create_index("evidence_id")
        await col.create_index("principal_id")
        await col.create_index([("tenant_id", 1), ("issued_at", -1)])
        await col.create_index("url_sha256", unique=True)

    async def issue(self, *, key: StorageObjectKey,
                    ttl_seconds: int = DEFAULT_SIGNED_URL_TTL_SECONDS,
                    audit: SignedUrlAuditCtx) -> SignedUrl:
        if ttl_seconds <= 0 or ttl_seconds > MAX_SIGNED_URL_TTL_SECONDS:
            raise bad_request(
                f"ttl_seconds must be in (0, {MAX_SIGNED_URL_TTL_SECONDS}]",
                code="evidence.signed_url.invalid_ttl")
        if audit.requested_ttl_seconds != ttl_seconds:
            # The caller is expected to clamp through `clamp_ttl` first.
            raise bad_request(
                "audit.requested_ttl_seconds must equal ttl_seconds",
                code="evidence.signed_url.audit_ttl_mismatch")

        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=ttl_seconds)
        # Per-issuance nonce makes every URL byte-unique even when issued
        # twice in the same second for the same key — required for
        # forensic dedup (`url_sha256` unique index in the audit collection).
        nonce = base64.urlsafe_b64encode(os.urandom(9)).rstrip(b"=").decode("ascii")
        path = f"/api/v1/evidence/blobs/{key.as_str()}"
        message = f"{path}|{int(expires.timestamp())}|{nonce}".encode("utf-8")
        sig = hmac.new(self._secret, message, hashlib.sha256).digest()
        sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode("ascii")
        url = (f"{self._base_url}{path}"
               f"?exp={int(expires.timestamp())}&n={nonce}&sig={sig_b64}")
        url_sha256 = hashlib.sha256(url.encode("utf-8")).hexdigest()

        audit_doc = {
            "audit_id": "sua_" + uuid.uuid4().hex,
            "evidence_id": audit.evidence_id,
            "tenant_id": audit.tenant_id,
            "country": audit.country,
            "principal_id": audit.principal_id,
            "principal_role": audit.principal_role,
            "action": audit.action,
            "object_key": key.as_str(),
            "ttl_seconds": ttl_seconds,
            "request_ip": audit.request_ip,
            "user_agent": audit.user_agent,
            "correlation_id": audit.correlation_id,
            "issued_at": now.isoformat(),
            "expires_at": expires.isoformat(),
            "url_sha256": url_sha256,
        }
        # Synchronous (awaited) insert: if this raises, the URL never leaves.
        try:
            await self._db[SIGNED_URL_AUDIT_COLLECTION].insert_one(audit_doc)
        except Exception:
            # Re-raise; the caller MUST NOT receive a URL.
            raise
        return SignedUrl(url=url, expires_at=expires,
                          audit_id=audit_doc["audit_id"],
                          url_sha256=url_sha256)

    @staticmethod
    def load_or_create_secret(*, env_var: str = "EVIDENCE_SIGNING_SECRET"
                               ) -> bytes:
        """Read the secret from env; if missing, generate and emit a
        warning. The production deploy MUST persist the secret in env
        (or a secret manager); regeneration invalidates outstanding
        signed URLs."""
        raw = os.environ.get(env_var)
        if raw:
            try:
                return base64.urlsafe_b64decode(raw + "==")
            except Exception:
                # Allow raw bytes if not base64
                return raw.encode("utf-8")
        import secrets
        return secrets.token_bytes(32)
