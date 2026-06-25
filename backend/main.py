"""Aquasavannah LandVault — FastAPI application assembly.

This module is intentionally *thin*: it only constructs the app, registers
middleware, mounts routers + webhooks, and wires startup/shutdown hooks. All
domain logic lives under routers/ and services/.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import CORS_ORIGINS
from core.database import client, ensure_indexes
from routers import (admin, attestations, auth, credits, dashboards, evidence,
                     institution, legal, notifications, observer, parcels,
                     payments, public, surveyor)
from services.jobs import seed_demo_data
from services.worker import start_worker, stop_worker
from webhooks import paystack as paystack_webhook
from webhooks import stripe as stripe_webhook

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("landvault")

app = FastAPI(title="Aquasavannah LandVault")

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


@app.on_event("shutdown")
async def _shutdown() -> None:
    await stop_worker()
    client.close()
