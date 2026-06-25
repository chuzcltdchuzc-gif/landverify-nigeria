"""Payment HTTP endpoints — provider-agnostic.

Every route delegates to `payment_service`. No Stripe / Paystack SDK imports
in this file. New providers can be added by registering them inside
`services/payment_service.py` without touching routes.

Legacy provider-named endpoints are preserved for backward compatibility.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from core.security import get_current_user
from schemas.models import CheckoutCreate, PaystackInit
from services.payment_service import payment_service

router = APIRouter(prefix="/payments")


@router.get("/config")
async def config() -> dict:
    return payment_service.public_config()


@router.get("/providers")
async def providers() -> dict:
    """List every registered payment provider + its runtime status."""
    return payment_service.public_config()


# ── Provider-agnostic endpoints ───────────────────────────────────────────
@router.post("/checkout")
async def checkout(body: CheckoutCreate, request: Request,
                   provider: str | None = None,
                   user: dict = Depends(get_current_user)) -> dict:
    """Create a checkout session on the named provider (or the default)."""
    return await payment_service.create_checkout(provider, body, user, request)


@router.get("/verify/{reference}")
async def verify(reference: str, provider: str | None = None,
                 user: dict = Depends(get_current_user)) -> dict:
    return await payment_service.verify(provider, reference, user)


# ── Legacy provider-named endpoints (backward compatibility) ──────────────
@router.post("/stripe/checkout")
async def stripe_checkout(body: CheckoutCreate, request: Request,
                          user: dict = Depends(get_current_user)) -> dict:
    return await payment_service.create_checkout("stripe", body, user, request)


@router.get("/stripe/status/{session_id}")
async def stripe_status(session_id: str,
                        user: dict = Depends(get_current_user)) -> dict:
    return await payment_service.verify("stripe", session_id, user)


@router.post("/paystack/init")
async def paystack_init(body: PaystackInit, request: Request,
                        user: dict = Depends(get_current_user)) -> dict:
    return await payment_service.create_checkout("paystack", body, user, request)


@router.get("/paystack/verify/{reference}")
async def paystack_verify(reference: str,
                          user: dict = Depends(get_current_user)) -> dict:
    return await payment_service.verify("paystack", reference, user)


# ── Mock provider helper (development only) ───────────────────────────────
@router.post("/mock/checkout")
async def mock_checkout(body: CheckoutCreate, request: Request,
                        user: dict = Depends(get_current_user)) -> dict:
    return await payment_service.create_checkout("mock", body, user, request)


@router.get("/mock/verify/{reference}")
async def mock_verify(reference: str,
                      user: dict = Depends(get_current_user)) -> dict:
    return await payment_service.verify("mock", reference, user)
