"""Opaque refresh tokens.

Access tokens are short-lived RS256 JWTs (kernel.security.jwt). Refresh tokens
are opaque, cryptographically random secrets stored as a SHA-256 hash in the
`kernel_refresh_tokens` collection alongside the session record. The plaintext
secret is only ever sent back to the user as an httpOnly secure cookie.

Refresh-token rotation: on every /v1/auth/refresh call, the current token is
marked REVOKED and a fresh one is issued. Replays of a revoked token trigger
session termination (token-theft heuristic).
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from kernel.config import SETTINGS

TOKEN_BYTES = 32  # 256 bits of entropy


def new_opaque_token() -> tuple[str, str]:
    """Return (plaintext, sha256_hex). Persist the hash, return plaintext to caller."""
    raw = secrets.token_urlsafe(TOKEN_BYTES)
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def refresh_expiry(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now + timedelta(seconds=SETTINGS.refresh_token_ttl_seconds)
