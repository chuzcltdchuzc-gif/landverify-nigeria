"""Delegation grant — a time-bounded, revocable, audited permission for one
principal to act for another within an explicit scope (Foundation Spec §5).

Delegations are NOT a way to "switch user" — they grant a delegate the right
to invoke specific actions on behalf of the delegator within a window. The
Authorization Engine evaluates active grants in `PIP.principal_attributes`.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class DelegationGrant:
    grant_id: str
    delegator_id: str                # principal granting the authority
    delegate_id: str                 # principal receiving the authority
    scope: list[str]                 # explicit allowed actions
    valid_from: str
    valid_until: str
    reason: str
    status: str = "ACTIVE"           # ACTIVE | REVOKED | EXPIRED
    granted_by: Optional[str] = None
    revoked_at: Optional[str] = None
    revoked_by: Optional[str] = None
    revoked_reason: Optional[str] = None
    version: int = 1
    created_at: str = field(default_factory=_now_iso)

    @classmethod
    def new(cls, *, delegator_id: str, delegate_id: str, scope: list[str],
            valid_from: str, valid_until: str, reason: str,
            granted_by: Optional[str] = None) -> "DelegationGrant":
        if not scope:
            raise ValueError("delegations must declare at least one scope action")
        if valid_until <= valid_from:
            raise ValueError("valid_until must be after valid_from")
        return cls(
            grant_id="dlg_" + uuid.uuid4().hex,
            delegator_id=delegator_id, delegate_id=delegate_id,
            scope=list(scope), valid_from=valid_from, valid_until=valid_until,
            reason=reason.strip(), granted_by=granted_by,
        )

    def is_active_at(self, when: Optional[datetime] = None) -> bool:
        if self.status != "ACTIVE":
            return False
        now = (when or datetime.now(timezone.utc)).isoformat()
        return self.valid_from <= now <= self.valid_until

    def revoke(self, by_principal_id: str, reason: str) -> None:
        self.status = "REVOKED"
        self.revoked_at = _now_iso()
        self.revoked_by = by_principal_id
        self.revoked_reason = reason

    def to_doc(self) -> dict:
        return {
            "grant_id": self.grant_id, "delegator_id": self.delegator_id,
            "delegate_id": self.delegate_id, "scope": list(self.scope),
            "valid_from": self.valid_from, "valid_until": self.valid_until,
            "reason": self.reason, "status": self.status,
            "granted_by": self.granted_by, "revoked_at": self.revoked_at,
            "revoked_by": self.revoked_by, "revoked_reason": self.revoked_reason,
            "version": self.version, "created_at": self.created_at,
            "schema_version": 1,
        }

    @classmethod
    def from_doc(cls, doc: dict) -> "DelegationGrant":
        return cls(
            grant_id=doc["grant_id"], delegator_id=doc["delegator_id"],
            delegate_id=doc["delegate_id"], scope=list(doc.get("scope") or []),
            valid_from=doc["valid_from"], valid_until=doc["valid_until"],
            reason=doc.get("reason", ""), status=doc.get("status", "ACTIVE"),
            granted_by=doc.get("granted_by"),
            revoked_at=doc.get("revoked_at"),
            revoked_by=doc.get("revoked_by"),
            revoked_reason=doc.get("revoked_reason"),
            version=int(doc.get("version", 1)),
            created_at=doc.get("created_at") or _now_iso(),
        )
