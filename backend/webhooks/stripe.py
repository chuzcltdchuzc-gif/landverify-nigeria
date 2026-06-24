"""Stripe webhook receiver — signature verified, idempotent fulfilment."""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, Request

from core.audit import audit_log
from core.database import db
from core.helpers import isoformat, now_utc
from services.payments import fulfill_payment

logger = logging.getLogger("landvault.webhook.stripe")
router = APIRouter()


@router.post("/api/webhook/stripe")
async def stripe_webhook(request: Request) -> dict:
    body = await request.body()
    sig_header = request.headers.get("Stripe-Signature", "")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET") or ""
    api_key = os.environ.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_API_KEY") or ""

    if not webhook_secret or not api_key:
        logger.warning("Stripe webhook received but webhook secret not configured — acknowledging without action.")
        return {"received": True, "verified": False, "reason": "webhook secret not configured"}

    try:
        import stripe as stripe_sdk
        stripe_sdk.api_key = api_key
        event = stripe_sdk.Webhook.construct_event(body, sig_header, webhook_secret)
    except Exception as exc:
        logger.warning("Stripe webhook signature verification failed: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event.get("type")
    data = event.get("data", {}).get("object", {})
    if event_type in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        session_id = data.get("id")
        if session_id:
            pt = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
            if pt:
                await fulfill_payment(pt, session_id)
                await audit_log("STRIPE_WEBHOOK_FULFILLED", "payment", session_id,
                                metadata={"event": event_type})
    elif event_type == "checkout.session.expired":
        session_id = data.get("id")
        if session_id:
            await db.payment_transactions.update_one(
                {"session_id": session_id},
                {"$set": {"payment_status": "EXPIRED", "expired_at": isoformat(now_utc())}},
            )
    return {"received": True, "verified": True, "type": event_type}
