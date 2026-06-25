"""Credit wallet + transactions (tenant-isolated via tdb)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from core.safe_db import tdb
from core.security import get_current_user

router = APIRouter(prefix="/credits")


@router.get("/balance")
async def credit_balance(user: dict = Depends(get_current_user)) -> dict:
    wallet = await tdb.credit_wallets.find_one({"user_id": user["user_id"]}, {"_id": 0})
    return {"wallet": wallet}


@router.get("/transactions")
async def credit_transactions(user: dict = Depends(get_current_user)) -> dict:
    items = [t async for t in tdb.credit_transactions.find(
        {"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).limit(100)]
    return {"items": items}
