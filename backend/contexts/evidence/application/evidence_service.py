"""Evidence application service — Phase 3.4 + 3.5.

Thin orchestrator. Opens a Mongo session, drives aggregate commands,
persists state + raised events inside the SAME transaction
(transactional outbox), writes audit + metrics, returns DTO-shaped dicts.

Binding rules:
* NEVER puts business logic here. NEVER raises domain events directly.
* Binaries flow through ``StoragePort`` only; this service never touches
  raw bytes apart from passing the multipart stream through.
* Server hashes are authoritative. Client claims are forwarded to the
  aggregate which performs the equality check during ``verify_hash``.
* Sealing fans out per-item Object-Lock requests to the StoragePort
  BEFORE flipping the seal's status to ``worm_applied``.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Optional

from motor.motor_asyncio import AsyncIOMotorClient

from contexts.evidence.adapters.mongo_evidence_repository import (
    MongoEvidenceItemRepository,
    MongoSealRepository,
)
from contexts.evidence.domain.evidence_item import EvidenceItem
from contexts.evidence.domain.invariants import (
    ConcurrencyConflict,
    HashMismatchError,
    ImmutableFieldError,
    InvariantViolation,
    SealedItemError,
    TransitionError,
    WormViolationError,
)
from contexts.evidence.domain.seal import Seal
from contexts.evidence.domain.value_objects import (
    EvidenceKind,
    EvidenceStatus,
    EvidenceSourceSystem,
    Origin,
    SealStatus,
)
from contexts.evidence.ports.specifications import EvidenceItemSpec, SealSpec
from contexts.evidence.ports.storage import (
    DEFAULT_SIGNED_URL_TTL_SECONDS,
    MAX_SIGNED_URL_TTL_SECONDS,
    SignedUrlAuditCtx,
    StorageTier,
    canonical_key,
    clamp_ttl,
)
from kernel.audit import audit
from kernel.errors.problem import bad_request, conflict, forbidden, not_found
from kernel.events.outbox import publish
from kernel.observability.metrics import increment
from kernel.persistence.context import current_context

# Phase 3.5 default retention — 100 years from seal application.
# Phase 3.6 will plug in policy-driven retention.
DEFAULT_SEAL_RETENTION_DAYS = 365 * 100


PRIVILEGED_EVIDENCE_ROLES = frozenset({
    "super_admin", "surveyor_general", "compliance_officer",
    "government_observer",
})


def _map_domain_error(exc: Exception) -> Exception:
    if isinstance(exc, HashMismatchError):
        return conflict(str(exc), code="evidence.hash_mismatch")
    if isinstance(exc, SealedItemError):
        return conflict(str(exc), code="evidence.sealed_immutable")
    if isinstance(exc, WormViolationError):
        return conflict(str(exc), code="evidence.worm_violation")
    if isinstance(exc, ImmutableFieldError):
        return bad_request(str(exc), code="evidence.immutable_field")
    if isinstance(exc, TransitionError):
        return conflict(str(exc), code="evidence.invalid_transition")
    if isinstance(exc, ConcurrencyConflict):
        return conflict(str(exc), code="evidence.version_conflict")
    if isinstance(exc, InvariantViolation):
        return bad_request(str(exc), code="evidence.invariant_violation")
    return exc


class EvidenceCommandService:
    """Commands across EvidenceItem + Seal aggregates."""

    def __init__(self, *, client: AsyncIOMotorClient,
                 items_repo: MongoEvidenceItemRepository,
                 seals_repo: MongoSealRepository,
                 storage,
                 signed_urls) -> None:
        self._client = client
        self._items_repo = items_repo
        self._seals_repo = seals_repo
        self._storage = storage
        self._signed_urls = signed_urls

    # ---- Internal helpers ----------------------------------------------

    def _actor_is_privileged(self) -> bool:
        ctx = current_context()
        return bool(set(ctx.roles) & PRIVILEGED_EVIDENCE_ROLES)

    async def _publish_events(self, agg, session) -> None:
        ctx = current_context()
        tenant_id = getattr(agg, "tenant_id", None)
        country = getattr(agg, "country_code", None)
        for evt in agg.pull_events():
            env = evt.to_envelope(
                tenant_id=tenant_id, country=country,
                organization_id=ctx.organization_id,
                actor=ctx.principal_id, correlation_id=ctx.correlation_id,
            )
            await publish(env, session=session)
            await audit(
                action=evt.event_type,
                resource_type=evt.aggregate_type.lower(),
                resource_id=evt.aggregate_id, decision="EXECUTED",
                payload={"version": evt.aggregate_version},
            )
            await increment("evidence_event", labels={"event_type": evt.event_type})

    async def _with_session(self, fn):
        try:
            async with await self._client.start_session() as session:
                try:
                    async with session.start_transaction():
                        return await fn(session)
                except Exception:
                    raise
        except Exception as exc:  # noqa: BLE001
            if ("Transaction numbers" in str(exc)
                    or "replica set" in str(exc).lower()):
                return await fn(None)
            raise

    # ---- EvidenceItem commands -----------------------------------------

    async def initiate_upload(self, *, registry_id: str, kind: str,
                               media_type: str, max_size: int,
                               client_hash_claim: Optional[str] = None
                               ) -> dict:
        ctx = current_context()
        if max_size <= 0 or max_size > 10 * 1024 * 1024 * 1024:  # 10 GiB ceiling
            raise bad_request("max_size must be 0 < x <= 10GiB",
                              code="evidence.invalid_max_size")
        origin = Origin(source_system=EvidenceSourceSystem.NATIVE.value)

        async def _run(session):
            try:
                agg = EvidenceItem.create(
                    registry_id=registry_id,
                    tenant_id=ctx.tenant_id or "default",
                    country_code=ctx.country or "NG",
                    kind=kind, created_by=ctx.principal_id, origin=origin,
                    media_type=media_type, client_hash_claim=client_hash_claim,
                )
            except InvariantViolation as exc:
                raise _map_domain_error(exc) from exc

            # Pre-mint the storage key and open the multipart session.
            key = canonical_key(
                tier=StorageTier.PRIVATE,
                tenant_id=agg.tenant_id, evidence_id=agg.evidence_id,
                suffix="final",
            )
            try:
                handle = await self._storage.initiate_multipart(
                    key=key, media_type=media_type, max_size=max_size,
                )
            except Exception as exc:
                raise _map_domain_error(exc) from exc
            agg.attach_upload_session(upload_id=handle.upload_id,
                                       media_type=media_type)
            await self._items_repo.add(agg, session=session)
            return agg, handle, key

        agg, handle, key = await self._with_session(_run)
        return {
            "evidence_id": agg.evidence_id,
            "registry_id": agg.registry_id,
            "upload_id": handle.upload_id,
            "max_size": max_size,
            "storage_key": key.as_str(),
            "storage_provider": self._storage.provider_id,
            "status": agg.status,
            "version": agg.version,
        }

    async def upload_part(self, *, evidence_id: str, part_no: int,
                           body_iter: AsyncIterator[bytes]) -> dict:
        agg = await self._items_repo.get(evidence_id)
        if not agg:
            raise not_found(f"EvidenceItem {evidence_id} not found",
                            code="evidence.not_found")
        if agg.status != EvidenceStatus.PENDING_UPLOAD.value:
            raise conflict(
                f"upload_part requires PENDING_UPLOAD; current={agg.status}",
                code="evidence.invalid_transition")
        key = canonical_key(
            tier=StorageTier.PRIVATE,
            tenant_id=agg.tenant_id, evidence_id=agg.evidence_id,
            suffix="final",
            when=datetime.fromisoformat(agg.created_at),
        )
        # Re-materialize the multipart handle from persisted upload_id.
        from contexts.evidence.ports.storage import MultipartHandle
        handle = MultipartHandle(
            upload_id=agg.upload_id, key=key, max_size=10 * 1024 * 1024 * 1024,
            media_type=agg.media_type or "application/octet-stream",
        )
        receipt = await self._storage.upload_part(
            handle, part_no=part_no, stream=body_iter,
        )
        return {
            "evidence_id": evidence_id,
            "part_no": receipt.part_no,
            "size_bytes": receipt.size_bytes,
            "streamed_sha256": receipt.streamed_sha256,
        }

    async def complete_upload(self, *, evidence_id: str,
                               parts: list[dict]) -> dict:
        """Finalize multipart upload + mark aggregate as
        PENDING_VERIFICATION."""
        ctx = current_context()

        async def _run(session):
            agg = await self._items_repo.get(evidence_id)
            if not agg:
                raise not_found(f"EvidenceItem {evidence_id} not found",
                                code="evidence.not_found")
            prev_version = agg.version
            from contexts.evidence.ports.storage import MultipartHandle, PartReceipt
            key = canonical_key(
                tier=StorageTier.PRIVATE,
                tenant_id=agg.tenant_id, evidence_id=agg.evidence_id,
                suffix="final",
                when=datetime.fromisoformat(agg.created_at),
            )
            handle = MultipartHandle(
                upload_id=agg.upload_id, key=key,
                max_size=10 * 1024 * 1024 * 1024,
                media_type=agg.media_type or "application/octet-stream",
            )
            receipts = [PartReceipt(
                part_no=int(p["part_no"]), size_bytes=int(p["size_bytes"]),
                streamed_sha256=str(p["streamed_sha256"]),
            ) for p in parts]
            try:
                stored = await self._storage.complete_multipart(
                    handle, parts=receipts,
                )
            except Exception as exc:
                raise _map_domain_error(exc) from exc
            try:
                agg.mark_uploaded(
                    storage_locator=stored.key.as_str(),
                    storage_provider=stored.provider_id,
                    size_bytes=stored.size_bytes,
                    streamed_sha256=stored.streamed_sha256,
                    media_type=stored.media_type,
                    actor=ctx.principal_id,
                )
            except (InvariantViolation, TransitionError) as exc:
                raise _map_domain_error(exc) from exc
            await self._items_repo.replace(
                agg, expected_version=prev_version, session=session,
            )
            await self._publish_events(agg, session=session)
            return agg

        agg = await self._with_session(_run)
        return _project_item(agg, viewer_role=self._viewer_role_for_item(agg))

    async def verify(self, *, evidence_id: str) -> dict:
        """Independent read-back + hash verification."""
        ctx = current_context()
        hash_mismatch_to_raise: list[Exception] = []

        async def _run(session):
            agg = await self._items_repo.get(evidence_id)
            if not agg:
                raise not_found(f"EvidenceItem {evidence_id} not found",
                                code="evidence.not_found")
            if agg.status != EvidenceStatus.PENDING_VERIFICATION.value:
                raise conflict(
                    f"verify requires PENDING_VERIFICATION; "
                    f"current={agg.status}",
                    code="evidence.invalid_transition")
            # Read back from storage and hash independently.
            from contexts.evidence.ports.storage import StorageObjectKey
            locator = agg.storage_locator or ""
            parts = locator.split("/")
            if len(parts) < 7:
                raise conflict("invalid storage locator",
                                code="evidence.invalid_locator")
            tier_str, tenant_id, yyyy, mm, dd, ev_id, suffix = parts
            key = StorageObjectKey(
                tier=StorageTier(tier_str), tenant_id=tenant_id,
                yyyy=yyyy, mm=mm, dd=dd,
                evidence_id=ev_id, suffix=suffix,
            )
            h = hashlib.sha256()
            async for chunk in self._storage.open_for_streaming_hash(key):
                h.update(chunk)
            readback = h.hexdigest()

            prev_version = agg.version
            try:
                agg.verify_hash(readback_sha256=readback,
                                 actor=ctx.principal_id)
            except HashMismatchError as exc:
                # Persist the rollback + integrity event WITHIN the
                # transaction, then surface the 409 to the caller AFTER
                # the transaction commits.
                await self._items_repo.replace(
                    agg, expected_version=prev_version, session=session,
                )
                await self._publish_events(agg, session=session)
                hash_mismatch_to_raise.append(exc)
                return agg
            except (InvariantViolation, TransitionError) as exc:
                raise _map_domain_error(exc) from exc
            await self._items_repo.replace(
                agg, expected_version=prev_version, session=session,
            )
            await self._publish_events(agg, session=session)
            return agg

        agg = await self._with_session(_run)
        if hash_mismatch_to_raise:
            raise _map_domain_error(hash_mismatch_to_raise[0])
        return _project_item(agg, viewer_role=self._viewer_role_for_item(agg))

    async def issue_signed_url(self, *, evidence_id: str,
                                 action: str = "read",
                                 ttl_seconds: int = DEFAULT_SIGNED_URL_TTL_SECONDS
                                 ) -> dict:
        ctx = current_context()
        agg = await self._items_repo.get(evidence_id)
        if not agg:
            raise not_found(f"EvidenceItem {evidence_id} not found",
                            code="evidence.not_found")
        if not agg.storage_locator:
            raise conflict("evidence has no stored object yet",
                            code="evidence.no_storage_object")
        ttl = clamp_ttl(ttl_seconds, role=ctx.roles[0] if ctx.roles else "general_user")

        from contexts.evidence.ports.storage import StorageObjectKey
        parts = agg.storage_locator.split("/")
        tier_str, tenant_id, yyyy, mm, dd, ev_id, suffix = parts
        key = StorageObjectKey(
            tier=StorageTier(tier_str), tenant_id=tenant_id,
            yyyy=yyyy, mm=mm, dd=dd,
            evidence_id=ev_id, suffix=suffix,
        )
        audit_ctx = SignedUrlAuditCtx(
            principal_id=ctx.principal_id,
            principal_role=(ctx.roles[0] if ctx.roles else "general_user"),
            tenant_id=agg.tenant_id, country=agg.country_code,
            evidence_id=evidence_id, action=action,
            requested_ttl_seconds=ttl,
            request_ip=ctx.request_ip, user_agent=ctx.user_agent,
            correlation_id=ctx.correlation_id,
        )
        signed = await self._signed_urls.issue(
            key=key, ttl_seconds=ttl, audit=audit_ctx,
        )
        # Emit + persist a signed_url.issued event (outside the tx — the
        # audit row is already durable on the signed_urls side).
        agg.record_signed_url_issuance(
            principal_id=ctx.principal_id, action=action,
            ttl_seconds=ttl, url_sha256=signed.url_sha256,
        )
        for evt in agg.pull_events():
            env = evt.to_envelope(
                tenant_id=agg.tenant_id, country=agg.country_code,
                actor=ctx.principal_id, correlation_id=ctx.correlation_id,
            )
            await publish(env)
        return {
            "url": signed.url,
            "expires_at": signed.expires_at.isoformat(),
            "audit_id": signed.audit_id,
            "url_sha256": signed.url_sha256,
            "ttl_seconds": ttl,
        }

    # ---- Seal commands --------------------------------------------------

    async def create_seal(self, *, registry_id: str,
                            evidence_ids: list[str]) -> dict:
        ctx = current_context()
        if not evidence_ids:
            raise bad_request("evidence_ids must not be empty",
                              code="evidence.seal.empty_items")
        if len(set(evidence_ids)) != len(evidence_ids):
            raise bad_request("evidence_ids must be unique",
                              code="evidence.seal.duplicate_items")

        async def _run(session):
            items = await self._items_repo.get_many(evidence_ids)
            if len(items) != len(evidence_ids):
                missing = set(evidence_ids) - {i.evidence_id for i in items}
                raise not_found(
                    f"evidence not found or out-of-scope: {sorted(missing)}",
                    code="evidence.seal.items_missing")
            for it in items:
                if it.registry_id != registry_id:
                    raise bad_request(
                        f"evidence {it.evidence_id} belongs to "
                        f"{it.registry_id}, not {registry_id}",
                        code="evidence.seal.cross_registry")
                if it.status != EvidenceStatus.VERIFIED.value:
                    raise conflict(
                        f"evidence {it.evidence_id} not verified "
                        f"(status={it.status})",
                        code="evidence.seal.unverified_item")
            tenant_id = items[0].tenant_id
            country_code = items[0].country_code
            for it in items[1:]:
                if it.tenant_id != tenant_id or it.country_code != country_code:
                    raise bad_request(
                        "seal items must share tenant_id + country_code",
                        code="evidence.seal.cross_scope")
            retention_until = (
                datetime.now(timezone.utc) +
                timedelta(days=DEFAULT_SEAL_RETENTION_DAYS)
            ).isoformat()
            try:
                seal = Seal.create(
                    registry_id=registry_id, tenant_id=tenant_id,
                    country_code=country_code,
                    items=[{
                        "evidence_id": it.evidence_id,
                        "server_hash": it.server_hash,
                        "size_bytes": it.size_bytes,
                        "kind": it.kind,
                        "media_type": it.media_type,
                    } for it in items],
                    created_by=ctx.principal_id,
                    retention_until=retention_until,
                )
            except InvariantViolation as exc:
                raise _map_domain_error(exc) from exc
            await self._seals_repo.add(seal, session=session)
            # Attach each item to the seal (transitions to SEALED).
            for it in items:
                prev_v = it.version
                try:
                    it.attach_to_seal(seal_id=seal.seal_id,
                                       actor=ctx.principal_id,
                                       retention_until=retention_until)
                except (InvariantViolation, TransitionError) as exc:
                    raise _map_domain_error(exc) from exc
                await self._items_repo.replace(
                    it, expected_version=prev_v, session=session,
                )
            await self._publish_events(seal, session=session)
            return seal

        seal = await self._with_session(_run)
        return _project_seal(seal, viewer_role=self._viewer_role_for_seal(seal))

    async def apply_worm(self, *, seal_id: str) -> dict:
        ctx = current_context()

        async def _run(session):
            seal = await self._seals_repo.get(seal_id)
            if not seal:
                raise not_found(f"Seal {seal_id} not found",
                                code="evidence.seal.not_found")
            if seal.status == SealStatus.WORM_APPLIED.value:
                return seal
            if seal.status != SealStatus.CREATED.value:
                raise conflict(
                    f"apply_worm requires status=created; current={seal.status}",
                    code="evidence.invalid_transition")
            items = await self._items_repo.get_many(list(seal.evidence_ids))
            from contexts.evidence.ports.storage import StorageObjectKey
            retention_until = (
                datetime.fromisoformat(seal.retention_until)
                if seal.retention_until
                else datetime.now(timezone.utc) + timedelta(days=DEFAULT_SEAL_RETENTION_DAYS)
            )
            lock_results: list[dict] = []
            for it in items:
                if not it.storage_locator:
                    raise conflict(
                        f"evidence {it.evidence_id} has no storage object",
                        code="evidence.no_storage_object")
                parts = it.storage_locator.split("/")
                key = StorageObjectKey(
                    tier=StorageTier(parts[0]), tenant_id=parts[1],
                    yyyy=parts[2], mm=parts[3], dd=parts[4],
                    evidence_id=parts[5], suffix=parts[6],
                )
                try:
                    status = await self._storage.apply_object_lock(
                        key, retention_until=retention_until,
                        applied_by=ctx.principal_id,
                    )
                except Exception as exc:
                    raise _map_domain_error(exc) from exc
                lock_results.append({
                    "evidence_id": it.evidence_id,
                    "storage_locator": it.storage_locator,
                    "locked": status.locked,
                    "retention_until": (status.retention_until.isoformat()
                                         if status.retention_until else None),
                })
            prev_version = seal.version
            try:
                seal.apply_worm(actor=ctx.principal_id,
                                  lock_results=lock_results)
            except (InvariantViolation, TransitionError) as exc:
                raise _map_domain_error(exc) from exc
            await self._seals_repo.replace(
                seal, expected_version=prev_version, session=session,
            )
            await self._publish_events(seal, session=session)
            return seal

        seal = await self._with_session(_run)
        return _project_seal(seal, viewer_role=self._viewer_role_for_seal(seal))

    # ---- Viewer-role helpers -------------------------------------------

    def _viewer_role_for_item(self, agg: EvidenceItem) -> str:
        ctx = current_context()
        if set(ctx.roles) & PRIVILEGED_EVIDENCE_ROLES:
            return "privileged"
        if ctx.principal_id == agg.created_by:
            return "owner"
        return "public"

    def _viewer_role_for_seal(self, seal: Seal) -> str:
        ctx = current_context()
        if set(ctx.roles) & PRIVILEGED_EVIDENCE_ROLES:
            return "privileged"
        if ctx.principal_id == seal.created_by:
            return "owner"
        return "public"


class EvidenceQueryService:
    """Read-side service."""

    def __init__(self, *, items_repo: MongoEvidenceItemRepository,
                 seals_repo: MongoSealRepository) -> None:
        self._items_repo = items_repo
        self._seals_repo = seals_repo

    def _viewer_role_item(self, agg: EvidenceItem) -> str:
        ctx = current_context()
        if set(ctx.roles) & PRIVILEGED_EVIDENCE_ROLES:
            return "privileged"
        if ctx.principal_id == agg.created_by:
            return "owner"
        return "public"

    def _viewer_role_seal(self, seal: Seal) -> str:
        ctx = current_context()
        if set(ctx.roles) & PRIVILEGED_EVIDENCE_ROLES:
            return "privileged"
        if ctx.principal_id == seal.created_by:
            return "owner"
        return "public"

    async def get_item(self, evidence_id: str) -> dict:
        agg = await self._items_repo.get(evidence_id)
        if not agg:
            raise not_found(f"EvidenceItem {evidence_id} not found",
                            code="evidence.not_found")
        return _project_item(agg, viewer_role=self._viewer_role_item(agg))

    async def list_items(self, *, spec: EvidenceItemSpec,
                          limit: int = 50, skip: int = 0) -> dict:
        items = await self._items_repo.find(spec, limit=limit, skip=skip,
                                              sort=[("created_at", -1)])
        total = await self._items_repo.count(spec)
        projected = [_project_item(a, viewer_role=self._viewer_role_item(a))
                      for a in items]
        return {"items": projected, "total": total,
                "limit": limit, "skip": skip}

    async def get_seal(self, seal_id: str) -> dict:
        seal = await self._seals_repo.get(seal_id)
        if not seal:
            raise not_found(f"Seal {seal_id} not found",
                            code="evidence.seal.not_found")
        return _project_seal(seal, viewer_role=self._viewer_role_seal(seal))


# ---- Projections ---------------------------------------------------------

OWNER_ITEM_FIELDS = (
    "evidence_id", "registry_id", "kind", "status", "version",
    "media_type", "size_bytes", "storage_provider",
    "server_hash", "hash_algorithm", "hash_verified",
    "client_hash_claim", "seal_id", "sealed_at", "retention_until",
    "replaced_by", "replaced_at",
    "created_at", "created_by", "updated_at",
)

PRIVILEGED_ITEM_EXTRA = (
    "tenant_id", "country_code", "storage_locator",
    "server_hash_streamed", "upload_id", "schema_version", "origin",
    "updated_by",
)

PUBLIC_ITEM_FIELDS = (
    "evidence_id", "registry_id", "kind", "status",
    "hash_algorithm", "hash_verified", "seal_id",
    "created_at",
)


def _project_item(agg: EvidenceItem, *, viewer_role: str = "owner") -> dict:
    state = agg.to_state()
    if viewer_role == "public":
        keys = PUBLIC_ITEM_FIELDS
    elif viewer_role == "privileged":
        keys = OWNER_ITEM_FIELDS + PRIVILEGED_ITEM_EXTRA
    else:
        keys = OWNER_ITEM_FIELDS
    return {k: state.get(k) for k in keys}


OWNER_SEAL_FIELDS = (
    "seal_id", "registry_id", "status", "version",
    "evidence_ids", "merkle_root", "manifest_hash",
    "created_at", "created_by",
    "worm_applied_at", "retention_until", "anchor_batch_id",
)

PRIVILEGED_SEAL_EXTRA = (
    "tenant_id", "country_code", "manifest", "leaf_hashes",
    "schema_version", "archived_at",
)

PUBLIC_SEAL_FIELDS = (
    "seal_id", "registry_id", "status",
    "merkle_root", "manifest_hash", "created_at",
)


def _project_seal(seal: Seal, *, viewer_role: str = "owner") -> dict:
    state = seal.to_state()
    if viewer_role == "public":
        keys = PUBLIC_SEAL_FIELDS
    elif viewer_role == "privileged":
        keys = OWNER_SEAL_FIELDS + PRIVILEGED_SEAL_EXTRA
    else:
        keys = OWNER_SEAL_FIELDS
    return {k: state.get(k) for k in keys}
