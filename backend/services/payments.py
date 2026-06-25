"""Payment provider configuration + amount resolution + atomic fulfilment."""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import HTTPException

from core.audit import audit_log  # noqa: F401  — used by callers
from core.config import CREDIT_PACKS, SUBSCRIPTION_PLANS
from core.database import db
from core.helpers import isoformat, new_id, now_utc
from core.tx import run_in_transaction

logger = logging.getLogger("landvault.payments")


def payments_config() -> dict:
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
        "stripe": {"enabled": bool(stripe_secret), "mode": _mode(stripe_secret),
                   "publishable_key": stripe_pub or None},
        "paystack": {"enabled": bool(paystack_secret), "mode": _mode(paystack_secret),
                     "public_key": paystack_pub or None},
    }


def resolve_amount(body) -> tuple[float, dict[str, str]]:
    if body.pack_code:
        pack = next((p for p in CREDIT_PACKS if p["code"] == body.pack_code), None)
        if not pack:
            raise HTTPException(status_code=400, detail="Unknown pack")
        return float(pack["price_ngn"]), {
            "type": "CREDIT_PACK", "pack_code": pack["code"],
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
            "type": "SUBSCRIPTION", "plan_code": plan["code"],
            "billing_cycle": body.billing_cycle or "monthly",
        }
    raise HTTPException(status_code=400, detail="pack_code or plan_code required")


async def fulfill_payment(pt: dict, reference: str) -> None:
    """Grant credits / activate subscription. ACID-atomic on replica sets."""
    if pt.get("credits_granted"):
        return
    meta: dict[str, Any] = pt.get("metadata", {}) or {}

    if meta.get("type") == "CREDIT_PACK":
        credits = int(meta.get("credits", "0"))
        if credits:
            existing_tx = await db.credit_transactions.find_one({"idempotency_key": reference})
            if not existing_tx:
                async def _do(session):
                    await db.credit_wallets.update_one(
                        {"user_id": pt["user_id"]},
                        {"$inc": {"balance": credits, "total_purchased": credits}},
                        session=session,
                    )
                    await db.credit_transactions.insert_one({
                        "id": new_id("tx"),
                        "user_id": pt["user_id"], "type": "PURCHASE", "amount": credits,
                        "description": f"{pt.get('provider', 'stripe').title()} purchase {meta.get('pack_code')}",
                        "reference": reference, "status": "COMPLETED",
                        "idempotency_key": reference, "tenant_id": pt.get("tenant_id"),
                        "created_at": isoformat(now_utc()),
                    }, session=session)
                    await db.payment_transactions.update_one(
                        {"session_id": pt["session_id"]},
                        {"$set": {"payment_status": "PAID", "credits_granted": True,
                                  "paid_at": isoformat(now_utc())}},
                        session=session,
                    )
                await run_in_transaction(_do)
                return
    elif meta.get("type") == "SUBSCRIPTION":
        async def _sub(session):
            await db.users.update_one(
                {"user_id": pt["user_id"]},
                {"$set": {"subscription_plan": meta.get("plan_code"),
                          "subscription_status": "ACTIVE", "role": meta.get("plan_code"),
                          "updated_at": isoformat(now_utc())}},
                session=session,
            )
            await db.payment_transactions.update_one(
                {"session_id": pt["session_id"]},
                {"$set": {"payment_status": "PAID", "credits_granted": True,
                          "paid_at": isoformat(now_utc())}},
                session=session,
            )
        await run_in_transaction(_sub)
        return

    # Fallback for unknown/empty pack metadata: still mark the payment paid.
    await db.payment_transactions.update_one(
        {"session_id": pt["session_id"]},
        {"$set": {"payment_status": "PAID", "credits_granted": True,
                  "paid_at": isoformat(now_utc())}},
    )


async def deduct_credits(
    user_id: str, amount: int, description: str, service_type: str, idempotency_key: str,
) -> dict:
    """Atomic credit deduction. Multi-doc ACID transaction on replica sets;
    single-doc atomic conditional update + idempotency-key guard otherwise.
    Retries automatically on TransientTransactionError (WriteConflict).
    """
    existing = await db.credit_transactions.find_one({"idempotency_key": idempotency_key}, {"_id": 0})
    if existing:
        return existing
    wallet = await db.credit_wallets.find_one({"user_id": user_id}, {"_id": 0})
    if not wallet:
        raise HTTPException(status_code=400, detail="Credit wallet not found")
    if wallet["balance"] < amount:
        raise HTTPException(status_code=402, detail=f"Insufficient credits. Need {amount}, have {wallet['balance']}")

    tx = {
        "id": new_id("tx"), "wallet_id": wallet["id"], "user_id": user_id,
        "type": "USAGE", "amount": -amount, "description": description,
        "service_type": service_type, "service_id": None, "reference": None,
        "status": "COMPLETED", "idempotency_key": idempotency_key,
        "tenant_id": wallet.get("tenant_id"), "created_at": isoformat(now_utc()),
    }

    insufficient = {"flag": False}

    async def _do(session):
        # Conditional update inside the TX: only deducts if balance is still high
        # enough at commit time. Returns None if the wallet was emptied by a
        # concurrent transaction.
        result = await db.credit_wallets.find_one_and_update(
            {"user_id": user_id, "balance": {"$gte": amount}},
            {"$inc": {"balance": -amount, "total_consumed": amount}},
            return_document=True, session=session,
        )
        if not result:
            insufficient["flag"] = True
            # Returning early aborts the TX without writing anything.
            return None
        # Re-insert needs to be safe on retry: idempotency_key is unique by intent
        # (caller passes a UUID-per-request). If a retry collides on it the
        # secondary insert will be a no-op via the earlier `existing` guard
        # because the previous TX was aborted (no write committed).
        await db.credit_transactions.insert_one(dict(tx), session=session)
        return tx

    result = await run_in_transaction(_do)
    if insufficient["flag"] or result is None:
        raise HTTPException(status_code=402, detail="Insufficient credits")
    return tx
