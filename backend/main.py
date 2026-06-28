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
    logger.info("Phase 1A constitutional kernel + Identity admin surface ready")


@app.on_event("shutdown")
async def _shutdown() -> None:
    await stop_outbox_publisher()
    await stop_worker()
    client.close()
