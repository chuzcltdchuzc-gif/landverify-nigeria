"""Session aggregate — server-side record of an issued refresh token.

The refresh token plaintext is sent to the caller as an httpOnly cookie and
NEVER stored in the database. Only its SHA-256 hash is stored, so a database
read does not yield a usable refresh token.

Lifecycle:
    ACTIVE  -> rotated/refreshed: previous session is REVOKED, a new one issued
    REVOKED -> terminal; replays of the previous secret terminate the session chain
    EXPIRED -> background sweep, terminal
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


STATUS_ACTIVE = "ACTIVE"
STATUS_REVOKED = "REVOKED"
STATUS_EXPIRED = "EXPIRED"


@dataclass
class Session:
    session_id: str
    user_id: str
    refresh_token_hash: str
    expires_at: str
    status: str = STATUS_ACTIVE
    created_at: str = field(default_factory=_now_iso)
    rotated_from: Optional[str] = None
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    revoked_at: Optional[str] = None
    revoked_reason: Optional[str] = None
    version: int = 1

    @classmethod
    def new(cls, *, user_id: str, refresh_token_hash: str, expires_at: str,
            user_agent: Optional[str] = None, ip_address: Optional[str] = None,
            rotated_from: Optional[str] = None) -> "Session":
        return cls(
            session_id="ses_" + uuid.uuid4().hex,
            user_id=user_id,
            refresh_token_hash=refresh_token_hash,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
            rotated_from=rotated_from,
        )

    def revoke(self, reason: str) -> None:
        self.status = STATUS_REVOKED
        self.revoked_at = _now_iso()
        self.revoked_reason = reason

    def to_doc(self) -> dict:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "refresh_token_hash": self.refresh_token_hash,
            "expires_at": self.expires_at,
            "status": self.status,
            "created_at": self.created_at,
            "rotated_from": self.rotated_from,
            "user_agent": self.user_agent,
            "ip_address": self.ip_address,
            "revoked_at": self.revoked_at,
            "revoked_reason": self.revoked_reason,
            "version": self.version,
            "schema_version": 1,
        }

    @classmethod
    def from_doc(cls, doc: dict) -> "Session":
        return cls(
            session_id=doc["session_id"],
            user_id=doc["user_id"],
            refresh_token_hash=doc["refresh_token_hash"],
            expires_at=doc["expires_at"],
            status=doc.get("status", STATUS_ACTIVE),
            created_at=doc.get("created_at") or _now_iso(),
            rotated_from=doc.get("rotated_from"),
            user_agent=doc.get("user_agent"),
            ip_address=doc.get("ip_address"),
            revoked_at=doc.get("revoked_at"),
            revoked_reason=doc.get("revoked_reason"),
            version=int(doc.get("version", 1)),
        )
