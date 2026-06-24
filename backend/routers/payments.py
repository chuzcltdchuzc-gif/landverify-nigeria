"""Payment routes: config, Stripe checkout/status, Paystack init/verify.

Webhook routes live in /app/backend/webhooks/{stripe,paystack}.py.
"""
from __future__ import annotations

import logging
import os
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from core.audit import audit_log
from core.config import PAYSTACK_API_BASE, ROLE_RANK
from core.database import db
from core.helpers import isoformat, new_id, now_utc
from core.security import get_current_user
from schemas.models import CheckoutCreate, PaystackInit
from services.payments import fulfill_payment, payments_config, resolve_amount

logger = logging.getLogger("landvault.payments")
router = APIRouter(prefix="/payments")


@router.get("/config")
async def get_config() -> dict:
    return payments_config()


@router.post("/stripe/checkout")
async def stripe_checkout(body: CheckoutCreate, request: Request,
                          user: dict = Depends(get_current_user)) -> dict:
    cfg = payments_config()
    if not cfg["stripe"]["enabled"]:
        raise HTTPException(status_code=503, detail="Payment system not configured (Stripe)")
    from emergentintegrations.payments.stripe.checkout import CheckoutSessionRequest, StripeCheckout
    api_key = os.environ.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="Payment system not configured (Stripe)")

    amount_ngn, metadata = resolve_amount(body)
    metadata.update({"user_id": user["user_id"], "tenant_id": user["tenant_id"]})
    amount_usd = max(0.5, round(amount_ngn / 1500.0, 2))

    webhook_url = f"{str(request.base_url).rstrip('/')}/api/webhook/stripe"
    checkout = StripeCheckout(api_key=api_key, webhook_url=webhook_url)

    origin = body.origin_url.rstrip("/")
    session = await checkout.create_checkout_session(CheckoutSessionRequest(
        amount=amount_usd, currency="usd",
        success_url=f"{origin}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{origin}/billing/cancel", metadata=metadata,
    ))
    await db.payment_transactions.insert_one({
        "id": new_id("pt"), "provider": "stripe", "session_id": session.session_id,
        "user_id": user["user_id"], "tenant_id": user["tenant_id"],
        "amount_usd": amount_usd, "amount_ngn": amount_ngn, "currency": "usd",
        "metadata": metadata, "payment_status": "INITIATED", "credits_granted": False,
        "created_at": isoformat(now_utc()),
    })
    await audit_log("STRIPE_CHECKOUT_CREATED", "payment", session.session_id, user=user,
                    metadata={"amount_ngn": amount_ngn, "metadata": metadata})
    return {"url": session.url, "session_id": session.session_id, "mode": cfg["stripe"]["mode"]}


@router.get("/stripe/status/{session_id}")
async def stripe_status(session_id: str, user: dict = Depends(get_current_user)) -> dict:
    cfg = payments_config()
    if not cfg["stripe"]["enabled"]:
        raise HTTPException(status_code=503, detail="Payment system not configured (Stripe)")

    pt = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
    if not pt:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if pt["user_id"] != user["user_id"] and ROLE_RANK.get(user["role"], 0) < ROLE_RANK["ADMIN"]:
        raise HTTPException(status_code=404, detail="Transaction not found")

    from emergentintegrations.payments.stripe.checkout import StripeCheckout
    api_key = os.environ.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_API_KEY")
    checkout = StripeCheckout(api_key=api_key, webhook_url="")
    try:
        status_resp = await checkout.get_checkout_status(session_id)
    except Exception as exc:
        logger.warning("Stripe status lookup failed for %s: %s", session_id, exc)
        raise HTTPException(status_code=502, detail="Upstream Stripe error")

    if status_resp.payment_status == "paid":
        await fulfill_payment(pt, session_id)
    elif status_resp.status == "expired":
        await db.payment_transactions.update_one(
            {"session_id": session_id}, {"$set": {"payment_status": "EXPIRED"}},
        )
    return {
        "status": status_resp.status, "payment_status": status_resp.payment_status,
        "amount_total": status_resp.amount_total, "currency": status_resp.currency,
        "metadata": status_resp.metadata,
    }


@router.post("/paystack/init")
async def paystack_init(body: PaystackInit, user: dict = Depends(get_current_user)) -> dict:
    cfg = payments_config()
    if not cfg["paystack"]["enabled"]:
        raise HTTPException(status_code=503, detail="Payment system not configured (Paystack)")

    amount_ngn, metadata = resolve_amount(body)
    metadata.update({"user_id": user["user_id"], "tenant_id": user["tenant_id"]})
    reference = f"ps_{uuid.uuid4().hex}"
    callback_url = f"{body.origin_url.rstrip('/')}/billing/paystack-callback"

    secret = os.environ["PAYSTACK_SECRET_KEY"]
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.post(
                f"{PAYSTACK_API_BASE}/transaction/initialize",
                headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
                json={"email": user["email"], "amount": int(amount_ngn * 100),
                      "reference": reference, "callback_url": callback_url,
                      "currency": "NGN", "metadata": metadata},
            )
    except httpx.HTTPError as exc:
        logger.exception("Paystack init network error: %s", exc)
        raise HTTPException(status_code=502, detail="Paystack network error")

    payload = r.json() if r.content else {}
    if r.status_code != 200 or not payload.get("status"):
        logger.warning("Paystack init failed: %s %s", r.status_code, payload)
        raise HTTPException(status_code=400, detail=payload.get("message") or "Paystack init failed")
    data = payload["data"]
    await db.payment_transactions.insert_one({
        "id": new_id("pt"), "provider": "paystack", "session_id": reference,
        "user_id": user["user_id"], "tenant_id": user["tenant_id"],
        "amount_ngn": amount_ngn, "currency": "NGN", "metadata": metadata,
        "payment_status": "INITIATED", "credits_granted": False,
        "callback_url": callback_url, "created_at": isoformat(now_utc()),
    })
    await audit_log("PAYSTACK_CHECKOUT_CREATED", "payment", reference, user=user,
                    metadata={"amount_ngn": amount_ngn})
    return {
        "authorization_url": data["authorization_url"],
        "access_code": data.get("access_code"),
        "reference": data["reference"], "mode": cfg["paystack"]["mode"],
    }


@router.get("/paystack/verify/{reference}")
async def paystack_verify(reference: str, user: dict = Depends(get_current_user)) -> dict:
    cfg = payments_config()
    if not cfg["paystack"]["enabled"]:
        raise HTTPException(status_code=503, detail="Payment system not configured (Paystack)")
    pt = await db.payment_transactions.find_one({"session_id": reference}, {"_id": 0})
    if not pt:
        raise HTTPException(status_code=404, detail="Reference not found")

    secret = os.environ["PAYSTACK_SECRET_KEY"]
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.get(
                f"{PAYSTACK_API_BASE}/transaction/verify/{reference}",
                headers={"Authorization": f"Bearer {secret}"},
            )
    except httpx.HTTPError as exc:
        logger.exception("Paystack verify network error: %s", exc)
        raise HTTPException(status_code=502, detail="Paystack network error")

    payload = r.json() if r.content else {}
    paystack_status = (payload.get("data") or {}).get("status")
    if r.status_code == 200 and payload.get("status") and paystack_status == "success":
        await fulfill_payment(pt, reference)
        return {"status": "success", "reference": reference, "verified": True}
    return {
        "status": paystack_status or "failed", "reference": reference,
        "verified": False, "message": payload.get("message"),
    }
