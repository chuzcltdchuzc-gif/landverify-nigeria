"""Service account aggregate — non-human principal with explicit minimal scopes.

A service account NEVER carries a human role. It authenticates via a generated
API secret (stored only as a SHA-256 hash) and acts only within the scopes
granted at creation. All actions are audited identically to human principals.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ServiceAccount:
    account_id: str
    name: str
    description: str
    tenant_id: Optional[str]                # None → platform-level service account
    country: Optional[str]
    organization_id: Optional[str]
    scopes: list[str]                       # explicit minimal scopes
    secret_hash: str                        # SHA-256 of generated API key
    status: str = "ACTIVE"                  # ACTIVE | REVOKED
    created_by: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)
    last_used_at: Optional[str] = None
    revoked_at: Optional[str] = None
    revoked_by: Optional[str] = None
    version: int = 1

    @classmethod
    def new(cls, *, name: str, description: str, scopes: list[str], secret_hash: str,
            tenant_id: Optional[str] = None, country: Optional[str] = None,
            organization_id: Optional[str] = None,
            created_by: Optional[str] = None) -> "ServiceAccount":
        if not scopes:
            raise ValueError("service accounts must declare at least one scope")
        return cls(
            account_id="svc_" + uuid.uuid4().hex,
            name=name.strip(), description=description.strip(),
            tenant_id=tenant_id, country=country, organization_id=organization_id,
            scopes=list(scopes), secret_hash=secret_hash, created_by=created_by,
        )

    def revoke(self, by_principal_id: str) -> None:
        self.status = "REVOKED"
        self.revoked_at = _now_iso()
        self.revoked_by = by_principal_id

    def to_doc(self) -> dict:
        return {
            "account_id": self.account_id, "name": self.name,
            "description": self.description, "tenant_id": self.tenant_id,
            "country": self.country, "organization_id": self.organization_id,
            "scopes": list(self.scopes), "secret_hash": self.secret_hash,
            "status": self.status, "created_by": self.created_by,
            "created_at": self.created_at, "last_used_at": self.last_used_at,
            "revoked_at": self.revoked_at, "revoked_by": self.revoked_by,
            "version": self.version, "schema_version": 1,
        }

    @classmethod
    def from_doc(cls, doc: dict) -> "ServiceAccount":
        return cls(
            account_id=doc["account_id"], name=doc["name"],
            description=doc.get("description", ""),
            tenant_id=doc.get("tenant_id"),
            country=doc.get("country"),
            organization_id=doc.get("organization_id"),
            scopes=list(doc.get("scopes") or []),
            secret_hash=doc["secret_hash"],
            status=doc.get("status", "ACTIVE"),
            created_by=doc.get("created_by"),
            created_at=doc.get("created_at") or _now_iso(),
            last_used_at=doc.get("last_used_at"),
            revoked_at=doc.get("revoked_at"),
            revoked_by=doc.get("revoked_by"),
            version=int(doc.get("version", 1)),
        )

    def public_view(self) -> dict:
        d = self.to_doc()
        d.pop("secret_hash", None)
        return d
