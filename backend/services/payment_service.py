"""Provider-agnostic PaymentService.

This is the SINGLE entry point that business workflows (routers, webhooks)
call. They never import Stripe / Paystack / Mock directly — they only ask the
PaymentService.

The service exposes three primary operations:

    await service.create_checkout(provider, body, user, request)
    await service.verify(provider, reference, user)
    await service.handle_webhook(provider, request)

…plus `public_config()` for the frontend banner / mode pills.

The provider is selected via the `PAYMENT_PROVIDER` env var (default `mock`).
Each named provider can also be addressed explicitly by name, which is what
the legacy `/api/payments/stripe/*` and `/api/payments/paystack/*` routes do.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import HTTPException, Request

from core.audit import audit_log
from core.database import db
from core.helpers import isoformat, new_id, now_utc
from services.payment_providers import (MockPaymentProvider, PaymentProvider,
                                         PaystackProvider, StripeProvider)
from services.payments import fulfill_payment, resolve_amount

logger = logging.getLogger("landvault.payment_service")


class PaymentService:
    """Registry + orchestration over all payment providers."""

    def __init__(self) -> None:
        self._providers: dict[str, PaymentProvider] = {
            "mock": MockPaymentProvider(),
            "stripe": StripeProvider(),
            "paystack": PaystackProvider(),
        }

    # ------------------------------------------------------------------
    # Provider selection
    # ------------------------------------------------------------------
    def get(self, name: Optional[str]) -> PaymentProvider:
        key = (name or self.default_provider_name()).lower()
        provider = self._providers.get(key)
        if provider is None:
            raise HTTPException(status_code=400, detail=f"Unknown payment provider '{key}'")
        return provider

    def default_provider_name(self) -> str:
        """Return the configured default provider.

        Resolution order:
            1. PAYMENT_PROVIDER env var if set to a known provider name
            2. If env value is "auto" → first enabled real provider, else "mock"
            3. "mock" otherwise (safe development default)
        """
        configured = (os.environ.get("PAYMENT_PROVIDER") or "mock").strip().lower()
        if configured == "auto":
            for name in ("stripe", "paystack"):
                if self._providers[name].enabled:
                    return name
            return "mock"
        if configured in self._providers:
            return configured
        return "mock"

    # ------------------------------------------------------------------
    # Public-safe configuration for the frontend
    # ------------------------------------------------------------------
    def public_config(self) -> dict:
        return {
            "default_provider": self.default_provider_name(),
            **{name: p.public_config() for name, p in self._providers.items()},
        }

    # ------------------------------------------------------------------
    # Checkout
    # ------------------------------------------------------------------
    async def create_checkout(self, provider_name: Optional[str], body,
                              user: dict, request: Request) -> dict:
        provider = self.get(provider_name)
        if not provider.enabled:
            raise HTTPException(status_code=503,
                                detail=f"Payment system not configured ({provider.name.title()})")

        amount_ngn, metadata = resolve_amount(body)
        metadata.update({"user_id": user["user_id"], "tenant_id": user["tenant_id"],
                         "provider": provider.name})

        origin = body.origin_url.rstrip("/")
        success_url = f"{origin}/billing/success?session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{origin}/billing/cancel"
        webhook_url = f"{str(request.base_url).rstrip('/')}/api/webhook/{provider.name}"

        result = await provider.create_checkout(
            amount_ngn=amount_ngn, metadata=metadata,
            success_url=success_url, cancel_url=cancel_url,
            webhook_url=webhook_url, user_email=user["email"],
        )

        await db.payment_transactions.insert_one({
            "id": new_id("pt"),
            "provider": provider.name,
            "session_id": result.reference,
            "user_id": user["user_id"],
            "tenant_id": user["tenant_id"],
            "amount_ngn": amount_ngn,
            "currency": "NGN" if provider.name == "paystack" else "usd",
            "metadata": metadata,
            "payment_status": "INITIATED",
            "credits_granted": False,
            "created_at": isoformat(now_utc()),
            **(result.extra or {}),
        })
        await audit_log(f"{provider.name.upper()}_CHECKOUT_CREATED", "payment",
                        result.reference, user=user,
                        metadata={"amount_ngn": amount_ngn, "metadata": metadata})

        return {
            "url": result.url,
            "session_id": result.reference,   # backwards-compat alias
            "reference": result.reference,
            "provider": provider.name,
            "mode": result.mode,
        }

    # ------------------------------------------------------------------
    # Verify
    # ------------------------------------------------------------------
    async def verify(self, provider_name: Optional[str], reference: str, user: dict) -> dict:
        provider = self.get(provider_name)
        if not provider.enabled:
            raise HTTPException(status_code=503,
                                detail=f"Payment system not configured ({provider.name.title()})")

        # Local ledger first → fast 404, prevents enumeration, allows ownership check.
        pt = await db.payment_transactions.find_one({"session_id": reference}, {"_id": 0})
        if not pt:
            raise HTTPException(status_code=404, detail="Transaction not found")
        from core.config import ROLE_RANK
        if pt["user_id"] != user["user_id"] and ROLE_RANK.get(user["role"], 0) < ROLE_RANK["ADMIN"]:
            raise HTTPException(status_code=404, detail="Transaction not found")

        result = await provider.verify(reference)
        if result.paid:
            await fulfill_payment(pt, reference)
        elif result.status == "expired":
            await db.payment_transactions.update_one(
                {"session_id": reference}, {"$set": {"payment_status": "EXPIRED"}},
            )
        return {
            "status": result.status,
            "payment_status": result.payment_status,
            "amount_total": result.amount_total,
            "currency": result.currency,
            "metadata": result.metadata,
            "reference": reference,
            "provider": provider.name,
            "verified": result.paid,
        }

    # ------------------------------------------------------------------
    # Webhook
    # ------------------------------------------------------------------
    async def handle_webhook(self, provider_name: str, request: Request) -> dict:
        provider = self.get(provider_name)
        body = await request.body()
        result = await provider.handle_webhook(body, dict(request.headers))
        if not result.verified:
            return {"received": True, "verified": False,
                    "reason": result.reason or "not verified"}
        if result.paid and result.reference:
            pt = await db.payment_transactions.find_one(
                {"session_id": result.reference}, {"_id": 0})
            if pt:
                await fulfill_payment(pt, result.reference)
                await audit_log(f"{provider.name.upper()}_WEBHOOK_FULFILLED", "payment",
                                result.reference, metadata={"event": result.event_type})
        elif result.event_type in ("checkout.session.expired",) and result.reference:
            await db.payment_transactions.update_one(
                {"session_id": result.reference},
                {"$set": {"payment_status": "EXPIRED",
                          "expired_at": isoformat(now_utc())}},
            )
        return {"received": True, "verified": True,
                "type": result.event_type, "provider": provider.name}


# Singleton — every router / webhook imports this object only.
payment_service = PaymentService()
