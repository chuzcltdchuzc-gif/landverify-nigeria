"""Provider-agnostic payment abstraction.

Three concrete providers implement the same `PaymentProvider` protocol:

* `MockPaymentProvider`    — default in dev, no network calls, idempotent credit grant
* `StripeProvider`         — wraps emergentintegrations' StripeCheckout SDK
* `PaystackProvider`       — wraps Paystack REST API via httpx

Business workflows (routers + webhooks) interact ONLY with `PaymentService`,
never with these concrete classes directly.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any, Optional, Protocol

import httpx
from fastapi import HTTPException

from core.config import PAYSTACK_API_BASE

logger = logging.getLogger("landvault.payment_providers")


@dataclass
class CheckoutResult:
    url: str
    reference: str
    mode: str
    extra: dict[str, Any] | None = None


@dataclass
class VerifyResult:
    paid: bool
    status: str               # "success" | "pending" | "failed" | "expired"
    payment_status: str       # provider's payment_status string
    amount_total: int | None = None
    currency: str | None = None
    metadata: dict[str, Any] | None = None
    reason: str | None = None


@dataclass
class WebhookResult:
    verified: bool
    event_type: str | None
    reference: str | None
    paid: bool
    raw: dict[str, Any] | None = None
    reason: str | None = None


def _mode_from_key(key: str) -> str:
    if not key:
        return "DISABLED"
    if key.startswith("sk_live_") or key.startswith("pk_live_"):
        return "LIVE"
    return "TEST"


# ============================================================
# Protocol
# ============================================================
class PaymentProvider(Protocol):
    name: str

    @property
    def enabled(self) -> bool: ...

    @property
    def mode(self) -> str: ...

    def public_config(self) -> dict: ...

    async def create_checkout(self, *, amount_ngn: float, metadata: dict,
                              success_url: str, cancel_url: str,
                              webhook_url: str, user_email: str) -> CheckoutResult: ...

    async def verify(self, reference: str) -> VerifyResult: ...

    async def handle_webhook(self, body: bytes, headers: dict) -> WebhookResult: ...


# ============================================================
# Mock provider (default for dev)
# ============================================================
class MockPaymentProvider:
    name = "mock"

    @property
    def enabled(self) -> bool:
        return True  # always available

    @property
    def mode(self) -> str:
        return "MOCK"

    def public_config(self) -> dict:
        return {"enabled": True, "mode": "MOCK", "publishable_key": None}

    async def create_checkout(self, *, amount_ngn: float, metadata: dict,
                              success_url: str, cancel_url: str,
                              webhook_url: str, user_email: str) -> CheckoutResult:
        ref = f"mock_{uuid.uuid4().hex}"
        # Land back on a callback path that the frontend already handles.
        # Replace the {CHECKOUT_SESSION_ID} placeholder Stripe-style if present.
        url = success_url.replace("{CHECKOUT_SESSION_ID}", ref)
        if "?" in url:
            url += f"&mock_reference={ref}"
        else:
            url += f"?mock_reference={ref}"
        return CheckoutResult(url=url, reference=ref, mode="MOCK",
                              extra={"mock": True, "amount_ngn": amount_ngn})

    async def verify(self, reference: str) -> VerifyResult:
        # In the mock provider, any "mock_*" reference is considered paid.
        if not reference.startswith("mock_"):
            return VerifyResult(paid=False, status="failed",
                                payment_status="unknown", reason="Unknown reference")
        return VerifyResult(paid=True, status="success",
                            payment_status="paid", amount_total=None, currency="NGN")

    async def handle_webhook(self, body: bytes, headers: dict) -> WebhookResult:
        # No real webhook for mock; treat any payload as a confirmation.
        import json
        try:
            payload = json.loads(body or b"{}")
        except Exception:
            payload = {}
        ref = (payload.get("data") or {}).get("reference") or payload.get("reference")
        return WebhookResult(verified=True, event_type="mock.confirmation",
                             reference=ref, paid=bool(ref), raw=payload)


# ============================================================
# Stripe (via emergentintegrations)
# ============================================================
class StripeProvider:
    name = "stripe"

    @property
    def api_key(self) -> str:
        return os.environ.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_API_KEY") or ""

    @property
    def publishable_key(self) -> str:
        return os.environ.get("STRIPE_PUBLISHABLE_KEY") or ""

    @property
    def webhook_secret(self) -> str:
        return os.environ.get("STRIPE_WEBHOOK_SECRET") or ""

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    @property
    def mode(self) -> str:
        return _mode_from_key(self.api_key)

    def public_config(self) -> dict:
        return {"enabled": self.enabled, "mode": self.mode,
                "publishable_key": self.publishable_key or None}

    async def create_checkout(self, *, amount_ngn: float, metadata: dict,
                              success_url: str, cancel_url: str,
                              webhook_url: str, user_email: str) -> CheckoutResult:
        if not self.enabled:
            raise HTTPException(status_code=503, detail="Payment system not configured (Stripe)")
        from emergentintegrations.payments.stripe.checkout import (
            CheckoutSessionRequest, StripeCheckout)

        # Emergent Stripe sandbox is USD; convert from NGN at a fixed indicative rate.
        amount_usd = max(0.5, round(amount_ngn / 1500.0, 2))
        checkout = StripeCheckout(api_key=self.api_key, webhook_url=webhook_url)
        session = await checkout.create_checkout_session(CheckoutSessionRequest(
            amount=amount_usd, currency="usd",
            success_url=success_url, cancel_url=cancel_url, metadata=metadata,
        ))
        return CheckoutResult(url=session.url, reference=session.session_id, mode=self.mode,
                              extra={"amount_usd": amount_usd})

    async def verify(self, reference: str) -> VerifyResult:
        if not self.enabled:
            raise HTTPException(status_code=503, detail="Payment system not configured (Stripe)")
        from emergentintegrations.payments.stripe.checkout import StripeCheckout
        checkout = StripeCheckout(api_key=self.api_key, webhook_url="")
        try:
            r = await checkout.get_checkout_status(reference)
        except Exception as exc:
            logger.warning("Stripe verify failed for %s: %s", reference, exc)
            raise HTTPException(status_code=502, detail="Upstream Stripe error")
        return VerifyResult(
            paid=(r.payment_status == "paid"),
            status=r.status, payment_status=r.payment_status,
            amount_total=r.amount_total, currency=r.currency, metadata=r.metadata,
        )

    async def handle_webhook(self, body: bytes, headers: dict) -> WebhookResult:
        sig = headers.get("Stripe-Signature") or headers.get("stripe-signature") or ""
        if not self.webhook_secret or not self.api_key:
            return WebhookResult(verified=False, event_type=None, reference=None,
                                 paid=False, reason="webhook secret not configured")
        try:
            import stripe as stripe_sdk
            stripe_sdk.api_key = self.api_key
            event = stripe_sdk.Webhook.construct_event(body, sig, self.webhook_secret)
        except Exception as exc:
            logger.warning("Stripe webhook signature verification failed: %s", exc)
            raise HTTPException(status_code=400, detail="Invalid signature")
        event_type = event.get("type")
        data = event.get("data", {}).get("object", {})
        reference = data.get("id")
        paid = event_type in ("checkout.session.completed", "checkout.session.async_payment_succeeded")
        return WebhookResult(verified=True, event_type=event_type, reference=reference,
                             paid=paid, raw=data)


# ============================================================
# Paystack (REST via httpx)
# ============================================================
class PaystackProvider:
    name = "paystack"

    @property
    def secret_key(self) -> str:
        return os.environ.get("PAYSTACK_SECRET_KEY") or ""

    @property
    def public_key(self) -> str:
        return os.environ.get("PAYSTACK_PUBLIC_KEY") or ""

    @property
    def webhook_signing_secret(self) -> str:
        return os.environ.get("PAYSTACK_WEBHOOK_SECRET") or self.secret_key

    @property
    def enabled(self) -> bool:
        return bool(self.secret_key)

    @property
    def mode(self) -> str:
        return _mode_from_key(self.secret_key)

    def public_config(self) -> dict:
        return {"enabled": self.enabled, "mode": self.mode,
                "public_key": self.public_key or None}

    async def create_checkout(self, *, amount_ngn: float, metadata: dict,
                              success_url: str, cancel_url: str,
                              webhook_url: str, user_email: str) -> CheckoutResult:
        if not self.enabled:
            raise HTTPException(status_code=503, detail="Payment system not configured (Paystack)")
        reference = f"ps_{uuid.uuid4().hex}"
        try:
            async with httpx.AsyncClient(timeout=20) as http:
                r = await http.post(
                    f"{PAYSTACK_API_BASE}/transaction/initialize",
                    headers={"Authorization": f"Bearer {self.secret_key}",
                             "Content-Type": "application/json"},
                    json={"email": user_email, "amount": int(amount_ngn * 100),
                          "reference": reference, "callback_url": success_url,
                          "currency": "NGN", "metadata": metadata},
                )
        except httpx.HTTPError as exc:
            logger.exception("Paystack init network error: %s", exc)
            raise HTTPException(status_code=502, detail="Paystack network error")
        payload = r.json() if r.content else {}
        if r.status_code != 200 or not payload.get("status"):
            raise HTTPException(status_code=400, detail=payload.get("message") or "Paystack init failed")
        data = payload["data"]
        return CheckoutResult(url=data["authorization_url"], reference=data["reference"],
                              mode=self.mode, extra={"access_code": data.get("access_code")})

    async def verify(self, reference: str) -> VerifyResult:
        if not self.enabled:
            raise HTTPException(status_code=503, detail="Payment system not configured (Paystack)")
        try:
            async with httpx.AsyncClient(timeout=20) as http:
                r = await http.get(
                    f"{PAYSTACK_API_BASE}/transaction/verify/{reference}",
                    headers={"Authorization": f"Bearer {self.secret_key}"},
                )
        except httpx.HTTPError as exc:
            logger.exception("Paystack verify network error: %s", exc)
            raise HTTPException(status_code=502, detail="Paystack network error")
        payload = r.json() if r.content else {}
        ps_status = (payload.get("data") or {}).get("status")
        paid = (r.status_code == 200 and bool(payload.get("status")) and ps_status == "success")
        return VerifyResult(paid=paid, status=ps_status or "failed",
                            payment_status=ps_status or "failed",
                            metadata=(payload.get("data") or {}).get("metadata"),
                            reason=payload.get("message"))

    async def handle_webhook(self, body: bytes, headers: dict) -> WebhookResult:
        sig = headers.get("x-paystack-signature") or headers.get("X-Paystack-Signature") or ""
        secret = self.webhook_signing_secret
        if not secret:
            return WebhookResult(verified=False, event_type=None, reference=None,
                                 paid=False, reason="webhook secret not configured")
        expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha512).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise HTTPException(status_code=401, detail="Invalid signature")
        import json
        event = json.loads(body or b"{}")
        event_type = event.get("event")
        data = event.get("data") or {}
        reference = data.get("reference")
        return WebhookResult(verified=True, event_type=event_type, reference=reference,
                             paid=(event_type == "charge.success"), raw=data)
