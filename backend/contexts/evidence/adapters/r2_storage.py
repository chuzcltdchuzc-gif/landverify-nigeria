"""Cloudflare R2 storage adapter — Phase 3.1 production skeleton.

This adapter is **port-clean**: it implements the same `StoragePort`
contract as ``LocalFsWormStorage``. The methods are intentionally
stubbed with ``NotImplementedError`` and a clear remediation message
so that the production wiring can swap providers without changing any
caller code — the actual S3-sigv4 / R2 calls land when operator
credentials and the bucket are available.

Operator setup (when ready):
    * Set ``R2_ACCOUNT_ID``, ``R2_ACCESS_KEY_ID``, ``R2_SECRET_ACCESS_KEY``
      and ``R2_BUCKET_PRIVATE`` / ``R2_BUCKET_PUBLIC`` in backend/.env.
    * Cloudflare R2 lacks native S3 Object Lock — the adapter emulates
      WORM via bucket versioning + a delete-protection lifecycle keyed
      on ``x-amz-meta-worm-until``.
    * Replace each `NotImplementedError` body with the corresponding
      `aioboto3` / `aiohttp` call.

DO NOT delete this file. It is the only place that owns the production
storage contract and serves as a compile-time guarantee that the port
is swappable.
"""
from __future__ import annotations

from datetime import datetime
from typing import AsyncIterator

from contexts.evidence.ports.storage import (
    MultipartHandle,
    ObjectLockStatus,
    PartReceipt,
    StorageObjectKey,
    StorageProviderId,
    StoredObject,
    VerifyCallback,
    WORM_MODE_COMPLIANCE,
)


def _stub(method: str) -> NotImplementedError:
    return NotImplementedError(
        f"R2StorageAdapter.{method} is a Phase-3.1 port skeleton — the "
        "concrete S3-sigv4 implementation lands when operator R2 "
        "credentials (R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
        "R2_SECRET_ACCESS_KEY, R2_BUCKET_PRIVATE) are configured. "
        "Use LocalFsWormStorage for dev/test."
    )


class R2StorageAdapter:
    provider_id = StorageProviderId.R2.value

    def __init__(self, *, account_id: str, access_key_id: str,
                 secret_access_key: str, bucket_private: str,
                 bucket_public: str | None = None) -> None:
        self.account_id = account_id
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.bucket_private = bucket_private
        self.bucket_public = bucket_public

    async def initiate_multipart(self, *, key: StorageObjectKey,
                                 media_type: str, max_size: int
                                 ) -> MultipartHandle:
        raise _stub("initiate_multipart")

    async def upload_part(self, handle: MultipartHandle, *, part_no: int,
                          stream: AsyncIterator[bytes]) -> PartReceipt:
        raise _stub("upload_part")

    async def complete_multipart(self, handle: MultipartHandle, *,
                                 parts: list[PartReceipt]) -> StoredObject:
        raise _stub("complete_multipart")

    async def abort_multipart(self, handle: MultipartHandle) -> None:
        raise _stub("abort_multipart")

    async def open_for_streaming_hash(self, key: StorageObjectKey
                                       ) -> AsyncIterator[bytes]:
        raise _stub("open_for_streaming_hash")
        yield b""  # pragma: no cover  (makes the type checker happy)

    async def apply_object_lock(self, key: StorageObjectKey, *,
                                retention_until: datetime,
                                mode: str = WORM_MODE_COMPLIANCE,
                                applied_by: str) -> ObjectLockStatus:
        raise _stub("apply_object_lock")

    async def extend_object_lock(self, key: StorageObjectKey, *,
                                 retention_until: datetime,
                                 extended_by: str) -> ObjectLockStatus:
        raise _stub("extend_object_lock")

    async def lock_status(self, key: StorageObjectKey) -> ObjectLockStatus:
        raise _stub("lock_status")

    async def move(self, *, src: StorageObjectKey, dst: StorageObjectKey,
                   verify_callback: VerifyCallback) -> StoredObject:
        raise _stub("move")
