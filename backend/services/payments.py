"""Payment provider configuration + amount resolution + fulfilment.

Keeps payment business rules out of routers/payments.py.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import HTTPException

from core.audit import audit_log  # noqa: F401  — used by callers
from core.config import CREDIT_PACKS, SUBSCRIPTION_PLANS
from core.database import db
from core.helpers import isoformat, new_id, now_utc

logger = logging.getLogger("landvault.payments")


def payments_config() -> dict:
    """Return the runtime status of each payment provider.
    Never leaks secret keys — only publishable keys and computed mode.
    """
    stripe_secret = os.environ.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_API_KEY") or ""
    stripe_pub = os.environ.get("STRIPE_PUBLISHABLE_KEY") or ""
    paystack_secret = os.environ.get("PAYSTACK_SECRET_KEY") or ""
    paystack_pub = os.environ.get("PAYSTACK_PUBLIC_KEY") or ""

    def _mode(key: str) -> str:
        if not key:
            return "DISABLED"
        if key.startswith("sk_live_") or key.startswith("pk_live_"):
            return "LIVE"
        return "TEST"

    return {
        "stripe": {
            "enabled": bool(stripe_secret),
            "mode": _mode(stripe_secret),
            "publishable_key": stripe_pub or None,
        },
        "paystack": {
            "enabled": bool(paystack_secret),
            "mode": _mode(paystack_secret),
            "public_key": paystack_pub or None,
        },
    }


def resolve_amount(body) -> tuple[float, dict[str, str]]:
    """Validate pack_code / plan_code → (amount_ngn, metadata)."""
    if body.pack_code:
        pack = next((p for p in CREDIT_PACKS if p["code"] == body.pack_code), None)
        if not pack:
            raise HTTPException(status_code=400, detail="Unknown pack")
        return float(pack["price_ngn"]), {
            "type": "CREDIT_PACK",
            "pack_code": pack["code"],
            "credits": str(pack["credits"]),
        }
    if body.plan_code:
        plan = next((p for p in SUBSCRIPTION_PLANS if p["code"] == body.plan_code), None)
        if not plan:
            raise HTTPException(status_code=400, detail="Unknown plan")
        amount = float(plan["annual_ngn"] if body.billing_cycle == "annual" else plan["monthly_ngn"])
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Plan not purchasable (invite-only)")
        return amount, {
            "type": "SUBSCRIPTION",
            "plan_code": plan["code"],
            "billing_cycle": body.billing_cycle or "monthly",
        }
    raise HTTPException(status_code=400, detail="pack_code or plan_code required")


async def fulfill_payment(pt: dict, reference: str) -> None:
    """Grant credits / activate subscription. Idempotent via credits_granted flag +
    idempotency_key on the credit transaction."""
    if pt.get("credits_granted"):
        return
    meta: dict[str, Any] = pt.get("metadata", {}) or {}
    if meta.get("type") == "CREDIT_PACK":
        credits = int(meta.get("credits", "0"))
        if credits:
            existing_tx = await db.credit_transactions.find_one({"idempotency_key": reference})
            if not existing_tx:
                await db.credit_wallets.update_one(
                    {"user_id": pt["user_id"]},
                    {"$inc": {"balance": credits, "total_purchased": credits}},
                )
                await db.credit_transactions.insert_one({
                    "id": new_id("tx"),
                    "user_id": pt["user_id"],
                    "type": "PURCHASE",
                    "amount": credits,
                    "description": f"{pt.get('provider', 'stripe').title()} purchase {meta.get('pack_code')}",
                    "reference": reference,
                    "status": "COMPLETED",
                    "idempotency_key": reference,
                    "tenant_id": pt.get("tenant_id"),
                    "created_at": isoformat(now_utc()),
                })
    elif meta.get("type") == "SUBSCRIPTION":
        await db.users.update_one(
            {"user_id": pt["user_id"]},
            {"$set": {
                "subscription_plan": meta.get("plan_code"),
                "subscription_status": "ACTIVE",
                "role": meta.get("plan_code"),
                "updated_at": isoformat(now_utc()),
            }},
        )
    await db.payment_transactions.update_one(
        {"session_id": pt["session_id"]},
        {"$set": {
            "payment_status": "PAID",
            "credits_granted": True,
            "paid_at": isoformat(now_utc()),
        }},
    )


async def deduct_credits(
    user_id: str, amount: int, description: str, service_type: str, idempotency_key: str,
) -> dict:
    """Atomic credit deduction guarded by idempotency_key + $inc."""
    existing = await db.credit_transactions.find_one({"idempotency_key": idempotency_key}, {"_id": 0})
    if existing:
        return existing
    wallet = await db.credit_wallets.find_one({"user_id": user_id}, {"_id": 0})
    if not wallet:
        raise HTTPException(status_code=400, detail="Credit wallet not found")
    if wallet["balance"] < amount:
        raise HTTPException(status_code=402, detail=f"Insufficient credits. Need {amount}, have {wallet['balance']}")
    result = await db.credit_wallets.find_one_and_update(
        {"user_id": user_id, "balance": {"$gte": amount}},
        {"$inc": {"balance": -amount, "total_consumed": amount}},
        return_document=True,
    )
    if not result:
        raise HTTPException(status_code=402, detail="Insufficient credits")
    tx = {
        "id": new_id("tx"),
        "wallet_id": wallet["id"],
        "user_id": user_id,
        "type": "USAGE",
        "amount": -amount,
        "description": description,
        "service_type": service_type,
        "service_id": None,
        "reference": None,
        "status": "COMPLETED",
        "idempotency_key": idempotency_key,
        "tenant_id": wallet.get("tenant_id"),
        "created_at": isoformat(now_utc()),
    }
    await db.credit_transactions.insert_one(dict(tx))
    return tx
