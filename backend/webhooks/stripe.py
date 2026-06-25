"""Stripe webhook receiver — delegates to PaymentService."""
from __future__ import annotations

from fastapi import APIRouter, Request

from services.payment_service import payment_service

router = APIRouter()


@router.post("/api/webhook/stripe")
async def stripe_webhook(request: Request) -> dict:
    return await payment_service.handle_webhook("stripe", request)
