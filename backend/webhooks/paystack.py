"""Paystack webhook receiver — HMAC-SHA512 verified."""
from __future__ import annotations

import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, HTTPException, Request

from core.audit import audit_log
from core.database import db
from services.payments import fulfill_payment

logger = logging.getLogger("landvault.webhook.paystack")
router = APIRouter()


@router.post("/api/webhook/paystack")
async def paystack_webhook(request: Request) -> dict:
    body = await request.body()
    sig_header = request.headers.get("x-paystack-signature", "")
    signing_secret = (
        os.environ.get("PAYSTACK_WEBHOOK_SECRET")
        or os.environ.get("PAYSTACK_SECRET_KEY")
        or ""
    )
    if not signing_secret:
        logger.warning("Paystack webhook received but no signing secret configured.")
        return {"received": True, "verified": False, "reason": "webhook secret not configured"}

    expected = hmac.new(signing_secret.encode("utf-8"), body, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(expected, sig_header):
        logger.warning("Paystack webhook signature mismatch.")
        raise HTTPException(status_code=401, detail="Invalid signature")

    event = await request.json()
    event_type = event.get("event")
    data = event.get("data") or {}
    reference = data.get("reference")
    if event_type == "charge.success" and reference:
        pt = await db.payment_transactions.find_one({"session_id": reference}, {"_id": 0})
        if pt:
            await fulfill_payment(pt, reference)
            await audit_log("PAYSTACK_WEBHOOK_FULFILLED", "payment", reference,
                            metadata={"event": event_type})
    return {"received": True, "verified": True, "type": event_type}
