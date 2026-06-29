"""Aquasavannah LandVault — FastAPI application assembly.

Mounts two layers side by side (Phase 1 sign-off, Decision 1a):

* **Phase 1 Platform Kernel + Identity context** under `/api/v1/...` —
  the constitutional foundation: JWT (RS256 + JWKS), PEP/PDP authorization,
  append-only audit, repository pattern, tenant + country scoping.

* **Legacy business routes** under `/api/...` — preserved unchanged so the
  existing application continues to operate during the progressive migration
  to the new architecture (no business features are migrated in Phase 1).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

# --- Legacy app (pre-Phase 1) --------------------------------------------
from core.config import CORS_ORIGINS
from core.database import client, db, ensure_indexes
from routers import (admin, attestations, auth, credits, dashboards, evidence,
                     institution, legal, notifications, observer, parcels,
                     payments, public, surveyor)
from services.jobs import seed_demo_data
from services.worker import start_worker, stop_worker
from webhooks import paystack as paystack_webhook
from webhooks import stripe as stripe_webhook

# --- Phase 1 Platform Kernel + Identity context --------------------------
from contexts.identity.adapters.mongo_service_and_delegation import (
    MongoDelegationRepository,
    MongoServiceAccountRepository,
)
from contexts.identity.adapters.mongo_session_repository import MongoSessionRepository
from contexts.identity.adapters.mongo_user_repository import MongoUserRepository
from contexts.identity.api import admin_router as identity_admin_router
from contexts.identity.api import auth_router as identity_auth_router
from contexts.identity.api import jwks_router as identity_jwks_router
from contexts.identity.application.admin_service import IdentityAdminService
from contexts.identity.application.auth_service import AuthService
from contexts.registry.adapters.mongo_allocator import MongoRegistryNumberAllocator
from contexts.registry.adapters.mongo_repository import MongoLandVaultRepository
from contexts.registry.api import router as registry_router
from contexts.registry.application import RegistryCommandService, RegistryQueryService
from contexts.registry.authorization import register_registry_policies
# Phase 3.1 — Evidence storage foundation (ports + adapters only at 3.1; the
# Evidence aggregate + API land at 3.4 per the binding step sequence).
from contexts.evidence.adapters.fs_worm_storage import LocalFsWormStorage
from contexts.evidence.adapters.mongo_evidence_repository import (
    MongoEvidenceItemRepository,
    MongoSealRepository,
)
from contexts.evidence.adapters.mongo_anchor_repository import (
    MongoAnchorBatchRepository,
    MongoEvidenceLockRepository,
    MongoIntegrityCheckRepository,
)
from contexts.evidence.adapters.ctlog_internal import CtlogInternalAdapter
from contexts.evidence.adapters.ots_v1 import OtsV1Adapter
from contexts.evidence.adapters.checkpoint_publishers import (
    build_publisher_from_env,
)
from contexts.evidence.adapters.signed_url_motor import SignedUrlMotorAdapter
from contexts.evidence.adapters.software_kms import SoftwareKmsAdapter
from contexts.evidence.api import router as evidence_router
from contexts.evidence.api import anchor_router as evidence_anchor_router
from contexts.evidence.application.anchor_saga import (
    AnchorSagaService,
    CtlogCheckpointer,
    IntegrityScheduler,
    start_anchor_saga,
    stop_anchor_saga,
)
from contexts.evidence.application.evidence_service import (
    EvidenceCommandService,
    EvidenceQueryService,
)
from contexts.evidence.authorization import register_evidence_policies
from kernel.audit import configure_audit_store
from kernel.authorization.pep import configure_pep
from kernel.authorization.policies import register_default_policies
from kernel.authorization.policy_library import register_demo_resource_policies
from kernel.errors import register_problem_handlers
from kernel.events import (
    configure_outbox,
    start_outbox_publisher,
    stop_outbox_publisher,
    subscribe,
)
from kernel.observability.metrics import configure_metrics, increment
from kernel.security.jwt import JwtIssuer, JwtVerifier
from kernel.security.keys import KeyStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("landvault")

app = FastAPI(title="Aquasavannah LandVault")
register_problem_handlers(app)

# All API endpoints live under /api/*
api = APIRouter(prefix="/api")
api.include_router(public.router)
api.include_router(auth.router)
api.include_router(parcels.router)
api.include_router(evidence.router)
api.include_router(attestations.router)
api.include_router(surveyor.router)
api.include_router(credits.router)
api.include_router(dashboards.router)
api.include_router(payments.router)
api.include_router(admin.router)
api.include_router(legal.router)
api.include_router(institution.router)
api.include_router(observer.router)
api.include_router(notifications.router)

# Phase 1 — Identity context endpoints live under /api/v1/auth/* and JWKS
# is published at /api/.well-known/jwks.json (RFC 7517 endpoint, prefixed
# with /api so it routes through the same ingress as everything else).
api.include_router(identity_auth_router.router)
api.include_router(identity_admin_router.router)
api.include_router(identity_jwks_router.router)

# Phase 2 — Registry bounded context endpoints live under /api/v1/registry/*
api.include_router(registry_router.router)

# Phase 3.4 / 3.5 — Evidence bounded context endpoints under /api/v1/evidence/*
api.include_router(evidence_router.router)
api.include_router(evidence_anchor_router.router)

app.include_router(api)

# Webhooks register their own absolute /api/webhook/* paths.
app.include_router(stripe_webhook.router)
app.include_router(paystack_webhook.router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup() -> None:
    await ensure_indexes()
    await seed_demo_data()
    await start_worker()

    # --- Phase 1 Platform Kernel boot ------------------------------------
    keystore = KeyStore(db)
    await keystore.ensure_active_key()
    jwt_issuer = JwtIssuer(keystore)
    jwt_verifier = JwtVerifier(keystore)
    configure_pep(jwt_verifier)
    configure_audit_store(db)
    configure_metrics(db)
    configure_outbox(db)
    register_default_policies()
    register_demo_resource_policies()
    register_registry_policies()
    register_evidence_policies()

    # Audit-event metric subscriber — every domain event bumps a counter.
    async def _audit_event_counter(env) -> None:
        await increment("audit_event_count", labels={"event_type": env.event_type})
    subscribe("*", _audit_event_counter)

    await start_outbox_publisher()

    user_repo = MongoUserRepository(db)
    session_repo = MongoSessionRepository(db)
    service_account_repo = MongoServiceAccountRepository(db)
    delegation_repo = MongoDelegationRepository(db)
    await user_repo.ensure_indexes()
    await session_repo.ensure_indexes()
    await service_account_repo.ensure_indexes()
    await delegation_repo.ensure_indexes()

    auth_service = AuthService(users=user_repo, sessions=session_repo,
                               jwt_issuer=jwt_issuer)
    admin_service = IdentityAdminService(
        users=user_repo, service_accounts=service_account_repo,
        delegations=delegation_repo,
    )
    identity_auth_router.configure_router(auth_service)
    identity_admin_router.configure_admin_router(admin_service, user_repo)
    identity_jwks_router.configure_router(keystore)

    # --- Phase 2 Registry context boot -----------------------------------
    landvault_repo = MongoLandVaultRepository(db)
    allocator = MongoRegistryNumberAllocator(db)
    await landvault_repo.ensure_indexes()
    await allocator.ensure_indexes()
    registry_command = RegistryCommandService(
        client=client, repo=landvault_repo, allocator=allocator)
    registry_query = RegistryQueryService(repo=landvault_repo)
    registry_router.configure_router(registry_command, registry_query)
    # Legacy `/api/parcels` writes are delegated to the Registry (Phase 2A §2).
    from contexts.registry.legacy_adapter import configure_legacy_adapter
    configure_legacy_adapter(registry_command)

    # --- Phase 3.1 Evidence storage foundation --------------------------
    # Storage adapter: LocalFs WORM (dev). Production swaps to R2 via the
    # same StoragePort contract.
    import os as _os
    evidence_root = _os.environ.get("EVIDENCE_FS_ROOT", "/tmp/aqua-evidence")
    evidence_storage = LocalFsWormStorage(root_dir=evidence_root)
    # Signed-URL adapter writes the audit row BEFORE returning the URL
    # (ADR-0003 §3.7). The base URL is derived from CORS_ORIGINS at runtime.
    signing_secret = SignedUrlMotorAdapter.load_or_create_secret()
    signed_url_base = (
        _os.environ.get("EVIDENCE_SIGNED_URL_BASE")
        or (CORS_ORIGINS[0] if CORS_ORIGINS else "http://localhost:8001")
    )
    evidence_signed_urls = SignedUrlMotorAdapter(
        db=db, secret=signing_secret, base_url=signed_url_base,
    )
    await evidence_signed_urls.ensure_indexes()
    # Expose for downstream Phase 3.4+ wiring (composition-root pattern).
    app.state.evidence_storage = evidence_storage
    app.state.evidence_signed_urls = evidence_signed_urls

    # --- Phase 3.2 Evidence PII encryption ------------------------------
    # Domain depends only on EncryptionPort; SoftwareKmsAdapter is the
    # first concrete adapter. Production swaps to AWS KMS / Vault / HSM
    # without touching domain code.
    evidence_kms = SoftwareKmsAdapter(db=db)
    await evidence_kms.ensure_indexes()
    app.state.evidence_kms = evidence_kms

    # --- Phase 3.4 + 3.5 Evidence aggregate + Sealing -------------------
    items_repo = MongoEvidenceItemRepository(db)
    seals_repo = MongoSealRepository(db)
    await items_repo.ensure_indexes()
    await seals_repo.ensure_indexes()
    evidence_command = EvidenceCommandService(
        client=client, items_repo=items_repo, seals_repo=seals_repo,
        storage=evidence_storage, signed_urls=evidence_signed_urls,
    )
    evidence_query = EvidenceQueryService(
        items_repo=items_repo, seals_repo=seals_repo,
    )
    evidence_router.configure_router(evidence_command, evidence_query)
    app.state.evidence_items_repo = items_repo
    app.state.evidence_seals_repo = seals_repo

    # --- Phase 3.6 Anchoring + Integrity + Locking ----------------------
    locks_repo = MongoEvidenceLockRepository(db)
    integrity_repo = MongoIntegrityCheckRepository(db)
    anchor_repo = MongoAnchorBatchRepository(db)
    ctlog_adapter = CtlogInternalAdapter(db)
    ots_adapter = OtsV1Adapter(db)
    checkpoint_publisher = build_publisher_from_env()
    await locks_repo.ensure_indexes()
    await integrity_repo.ensure_indexes()
    await anchor_repo.ensure_indexes()
    await ctlog_adapter.ensure_indexes()
    await ots_adapter.ensure_indexes()
    anchor_adapters = {ctlog_adapter.provider_id: ctlog_adapter,
                        ots_adapter.provider_id: ots_adapter}
    anchor_saga = AnchorSagaService(
        client=client, db=db, batches=anchor_repo, locks=locks_repo,
        integrity=integrity_repo, adapters=anchor_adapters,
        publisher=checkpoint_publisher)
    integrity_scheduler = IntegrityScheduler(
        db=db, integrity=integrity_repo, storage=evidence_storage)
    ctlog_checkpointer = CtlogCheckpointer(
        ctlog=ctlog_adapter, publisher=checkpoint_publisher,
        signing_secret=_os.environ.get(
            "EVIDENCE_CTLOG_SIGNING_SECRET", "dev-signing-secret").encode())
    evidence_anchor_router.configure_router(
        saga=anchor_saga, locks=locks_repo, integrity=integrity_repo,
        anchor=anchor_repo, integrity_scheduler=integrity_scheduler,
        ctlog=ctlog_adapter)
    app.state.evidence_locks_repo = locks_repo
    app.state.evidence_integrity_repo = integrity_repo
    app.state.evidence_anchor_repo = anchor_repo
    app.state.anchor_saga = anchor_saga
    app.state.integrity_scheduler = integrity_scheduler
    app.state.ctlog_checkpointer = ctlog_checkpointer
    # Launch background loops (batcher + confirmer + integrity + checkpointer).
    if _os.environ.get("EVIDENCE_ANCHOR_SAGA_ENABLED", "1") != "0":
        await start_anchor_saga(anchor_saga, integrity_scheduler,
                                  ctlog_checkpointer)

    logger.info("Phase 1A constitutional kernel + Identity admin surface ready")
    logger.info("Phase 2A Registry bounded context ready at /api/v1/registry/*")
    logger.info("Phase 3.1 Evidence storage foundation ready "
                "(provider=%s, fs_root=%s)",
                evidence_storage.provider_id, evidence_root)
    logger.info("Phase 3.2 Evidence PII encryption ready (kms=%s)",
                evidence_kms.kms_id)
    logger.info("Phase 3.4 + 3.5 Evidence aggregate + Sealing ready at /api/v1/evidence/*")
    logger.info("Phase 3.6 Anchoring + Integrity + Locking ready at /api/v1/evidence/anchor-batches/* + /locks/* + /integrity-checks/* + /ctlog/*")


@app.on_event("shutdown")
async def _shutdown() -> None:
    await stop_anchor_saga()
    await stop_outbox_publisher()
    await stop_worker()
    client.close()
