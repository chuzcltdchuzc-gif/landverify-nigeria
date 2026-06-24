"""Session-based authentication primitives + RBAC dependency factory."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import Cookie, Depends, Header, HTTPException

from core.config import ROLE_RANK
from core.database import db
from core.helpers import now_utc, serialize_doc


async def _get_session_token(
    session_token_cookie: Optional[str] = Cookie(default=None, alias="session_token"),
    authorization: Optional[str] = Header(default=None),
) -> Optional[str]:
    if session_token_cookie:
        return session_token_cookie
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


async def get_current_user(token: Optional[str] = Depends(_get_session_token)) -> dict:
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    expires_at = session.get("expires_at")
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at and expires_at < now_utc():
        raise HTTPException(status_code=401, detail="Session expired")
    user = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    serialize_doc(user)
    return user


def require_role(min_role: str):
    """Dependency factory that ensures the caller's role outranks min_role."""

    async def _dep(user: dict = Depends(get_current_user)) -> dict:
        if ROLE_RANK.get(user["role"], 0) < ROLE_RANK[min_role]:
            raise HTTPException(status_code=403, detail=f"Requires role {min_role} or above")
        return user

    return _dep
