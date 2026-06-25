"""Paystack webhook receiver — delegates to PaymentService."""
from __future__ import annotations

from fastapi import APIRouter, Request

from services.payment_service import payment_service

router = APIRouter()


@router.post("/api/webhook/paystack")
async def paystack_webhook(request: Request) -> dict:
    return await payment_service.handle_webhook("paystack", request)


@router.post("/api/webhook/mock")
async def mock_webhook(request: Request) -> dict:
    """For dev/test only — confirms the MockPaymentProvider's webhook path."""
    return await payment_service.handle_webhook("mock", request)
