"""LocalFs WORM storage adapter (Phase 3.1, dev).

Production deployments use the R2 adapter; this one is for local
development and for the test suite. It implements the full StoragePort
contract including WORM Object-Lock emulation:

* Object lock = file `chmod 0o400` + a sidecar `<obj>.lock.json` with
  retention_until, mode, applied_at, applied_by.
* The adapter REFUSES to delete or overwrite any object whose sidecar
  lock is unexpired, regardless of the OS permission bits. The
  refusal is the binding behaviour; the chmod is belt-and-braces.
* Multipart parts live alongside the final file under
  `<obj_dir>/parts/`; `complete_multipart` concatenates them
  deterministically (by part_no) into `<obj_dir>/final`.

Server-streamed SHA-256 is computed during every `upload_part` and
again on `complete_multipart`. The streamed digest is returned in
`StoredObject.streamed_sha256` — this is the "streamed-during-write"
pass of ADR-0004; the read-back pass uses `open_for_streaming_hash`.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Optional

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
from kernel.errors.problem import bad_request, conflict, forbidden, not_found

CHUNK_SIZE = 1024 * 1024  # 1 MiB streaming chunks


class WormViolationError(Exception):
    """Raised when an attempted operation would mutate a WORM-locked object."""


class LocalFsWormStorage:
    """Dev-friendly StoragePort implementation.

    The composition root injects `root_dir`. Tests use a per-test tmp
    path; the running server uses ``EVIDENCE_FS_ROOT`` from env (defaults
    to ``/var/lib/aquasavannah/evidence`` in production, ``/tmp/aqua-
    evidence`` in dev).
    """

    provider_id = StorageProviderId.LOCAL_FS_WORM.value

    def __init__(self, *, root_dir: str) -> None:
        self._root = Path(root_dir)
        self._root.mkdir(parents=True, exist_ok=True)

    # ---- internal path helpers ----------------------------------------

    def _obj_dir(self, key: StorageObjectKey) -> Path:
        # key.as_str() includes tier; we sandbox under the tier so we
        # can give Public a different mount/bucket later.
        return self._root / key.as_str().rstrip(f"/{key.suffix}").rstrip("/")

    def _final_path(self, key: StorageObjectKey) -> Path:
        return self._root / key.as_str()

    def _lock_path(self, key: StorageObjectKey) -> Path:
        return Path(str(self._final_path(key)) + ".lock.json")

    def _parts_dir(self, handle: MultipartHandle) -> Path:
        return self._obj_dir(handle.key) / f".parts.{handle.upload_id}"

    # ---- multipart ----------------------------------------------------

    async def initiate_multipart(self, *, key: StorageObjectKey,
                                 media_type: str, max_size: int
                                 ) -> MultipartHandle:
        if max_size <= 0:
            raise bad_request("max_size must be positive",
                              code="evidence.storage.invalid_max_size")
        # If the final exists and is locked we cannot accept any new upload
        # to the same key — that would attempt to overwrite WORM bytes.
        if self._final_path(key).exists() and self._is_locked_now(key):
            raise WormViolationError(
                f"object {key.as_str()} is WORM-locked")
        upload_id = uuid.uuid4().hex
        handle = MultipartHandle(upload_id=upload_id, key=key,
                                  max_size=max_size, media_type=media_type)
        self._parts_dir(handle).mkdir(parents=True, exist_ok=True)
        return handle

    async def upload_part(self, handle: MultipartHandle, *, part_no: int,
                          stream: AsyncIterator[bytes]) -> PartReceipt:
        if part_no < 1 or part_no > 10_000:
            raise bad_request("part_no out of range (1..10000)",
                              code="evidence.storage.invalid_part_no")
        h = hashlib.sha256()
        size = 0
        part_path = self._parts_dir(handle) / f"part-{part_no:05d}.bin"
        # Stream to disk while updating the running hash. NEVER buffer
        # the whole body — large evidence files can be 100s of MB.
        loop = asyncio.get_event_loop()
        with part_path.open("wb") as f:
            async for chunk in stream:
                if not chunk:
                    continue
                size += len(chunk)
                if size > handle.max_size:
                    f.close()
                    part_path.unlink(missing_ok=True)
                    raise bad_request(
                        f"part exceeds max_size {handle.max_size}",
                        code="evidence.storage.part_too_large")
                h.update(chunk)
                # Mongo motor calls are awaitable; file IO is sync. We
                # offload to the default executor periodically so we
                # don't block the loop on very large parts.
                await loop.run_in_executor(None, f.write, chunk)
        return PartReceipt(part_no=part_no, size_bytes=size,
                            streamed_sha256=h.hexdigest())

    async def complete_multipart(self, handle: MultipartHandle, *,
                                 parts: list[PartReceipt]) -> StoredObject:
        if not parts:
            raise bad_request("at least one part is required",
                              code="evidence.storage.empty_multipart")
        if self._final_path(handle.key).exists() and self._is_locked_now(handle.key):
            raise WormViolationError(
                f"object {handle.key.as_str()} is WORM-locked")
        # Concatenate by part_no order; recompute running SHA-256 to
        # produce the canonical "streamed-during-write" digest of the
        # final object (independent of any individual part's claim).
        sorted_parts = sorted(parts, key=lambda p: p.part_no)
        h = hashlib.sha256()
        total = 0
        final_path = self._final_path(handle.key)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        with final_path.open("wb") as out:
            for p in sorted_parts:
                part_file = self._parts_dir(handle) / f"part-{p.part_no:05d}.bin"
                if not part_file.exists():
                    raise bad_request(
                        f"part {p.part_no} missing on disk",
                        code="evidence.storage.part_missing")
                with part_file.open("rb") as src:
                    while True:
                        chunk = src.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        h.update(chunk)
                        total += len(chunk)
                        out.write(chunk)
        # Best-effort cleanup of part files. Failure to delete is OK.
        try:
            for f in self._parts_dir(handle).iterdir():
                f.unlink(missing_ok=True)
            self._parts_dir(handle).rmdir()
        except OSError:
            pass
        return StoredObject(
            key=handle.key, provider_id=self.provider_id,
            size_bytes=total, streamed_sha256=h.hexdigest(),
            media_type=handle.media_type,
        )

    async def abort_multipart(self, handle: MultipartHandle) -> None:
        parts_dir = self._parts_dir(handle)
        if not parts_dir.exists():
            return
        for f in parts_dir.iterdir():
            try:
                f.unlink()
            except OSError:
                pass
        try:
            parts_dir.rmdir()
        except OSError:
            pass

    # ---- read-back stream (ADR-0004) ----------------------------------

    async def open_for_streaming_hash(self, key: StorageObjectKey
                                       ) -> AsyncIterator[bytes]:
        final = self._final_path(key)
        if not final.exists():
            raise not_found(f"object {key.as_str()} not found",
                            code="evidence.storage.not_found")
        loop = asyncio.get_event_loop()
        # Reopen the file (independent read pass — the upload pass closed it).
        with final.open("rb") as f:
            while True:
                chunk = await loop.run_in_executor(None, f.read, CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk

    # ---- WORM ---------------------------------------------------------

    def _is_locked_now(self, key: StorageObjectKey) -> bool:
        lock_path = self._lock_path(key)
        if not lock_path.exists():
            return False
        try:
            doc = json.loads(lock_path.read_text())
            until = datetime.fromisoformat(doc["retention_until"])
            return until > datetime.now(timezone.utc)
        except Exception:
            return True  # safer to err on the side of "locked"

    async def apply_object_lock(self, key: StorageObjectKey, *,
                                retention_until: datetime,
                                mode: str = WORM_MODE_COMPLIANCE,
                                applied_by: str) -> ObjectLockStatus:
        if mode != WORM_MODE_COMPLIANCE:
            # Platform invariant: only compliance mode is accepted. See
            # ADR-0006 (legal hold + remediation).
            raise forbidden(
                "evidence storage rejects governance-mode object locks",
                code="evidence.storage.invalid_worm_mode")
        final = self._final_path(key)
        if not final.exists():
            raise not_found(
                f"cannot lock missing object {key.as_str()}",
                code="evidence.storage.not_found")
        doc = {
            "key": key.as_str(),
            "mode": mode,
            "retention_until": retention_until.isoformat(),
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "applied_by": applied_by,
        }
        self._lock_path(key).write_text(json.dumps(doc, sort_keys=True))
        # Make the file read-only on disk. The lock sidecar is the
        # authoritative check; chmod is belt-and-braces.
        try:
            os.chmod(final, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        except OSError:
            pass
        return await self.lock_status(key)

    async def extend_object_lock(self, key: StorageObjectKey, *,
                                 retention_until: datetime,
                                 extended_by: str) -> ObjectLockStatus:
        lock_path = self._lock_path(key)
        if not lock_path.exists():
            raise conflict(
                "cannot extend lock that does not exist",
                code="evidence.storage.lock_missing")
        doc = json.loads(lock_path.read_text())
        old = datetime.fromisoformat(doc["retention_until"])
        if retention_until <= old:
            raise bad_request(
                "extend_object_lock requires a later retention_until",
                code="evidence.storage.retention_not_extended")
        doc["retention_until"] = retention_until.isoformat()
        doc["last_extended_at"] = datetime.now(timezone.utc).isoformat()
        doc["last_extended_by"] = extended_by
        lock_path.write_text(json.dumps(doc, sort_keys=True))
        return await self.lock_status(key)

    async def lock_status(self, key: StorageObjectKey) -> ObjectLockStatus:
        lock_path = self._lock_path(key)
        if not lock_path.exists():
            return ObjectLockStatus(locked=False, mode=None,
                                    retention_until=None,
                                    applied_at=None, applied_by=None)
        doc = json.loads(lock_path.read_text())
        until = datetime.fromisoformat(doc["retention_until"])
        applied = datetime.fromisoformat(doc["applied_at"])
        now = datetime.now(timezone.utc)
        return ObjectLockStatus(
            locked=until > now, mode=doc.get("mode"),
            retention_until=until, applied_at=applied,
            applied_by=doc.get("applied_by"),
        )

    # ---- remediation move (no source delete) --------------------------

    async def move(self, *, src: StorageObjectKey, dst: StorageObjectKey,
                   verify_callback: VerifyCallback) -> StoredObject:
        src_path = self._final_path(src)
        if not src_path.exists():
            raise not_found(f"source {src.as_str()} not found",
                            code="evidence.storage.not_found")
        if self._final_path(dst).exists():
            raise conflict(f"destination {dst.as_str()} already exists",
                            code="evidence.storage.dst_exists")
        dst_path = self._final_path(dst)
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        size = 0
        loop = asyncio.get_event_loop()
        with src_path.open("rb") as fr, dst_path.open("wb") as fw:
            while True:
                chunk = await loop.run_in_executor(None, fr.read, CHUNK_SIZE)
                if not chunk:
                    break
                # Stream the bytes through the saga's verify callback so it
                # can update its independent running hash.
                await verify_callback(chunk)
                h.update(chunk)
                size += len(chunk)
                await loop.run_in_executor(None, fw.write, chunk)
        # Source is intentionally LEFT IN PLACE — the saga is responsible
        # for the verify-then-cutover decision (ADR-0006).
        return StoredObject(
            key=dst, provider_id=self.provider_id,
            size_bytes=size, streamed_sha256=h.hexdigest(),
            media_type="application/octet-stream",
        )
