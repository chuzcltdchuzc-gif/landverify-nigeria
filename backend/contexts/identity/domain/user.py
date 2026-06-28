"""User aggregate — Identity context canonical authority.

Reproduces the EXACT recovered Base44 user model + extends for multi-country.
The User aggregate owns: identity records, roles, status, tenant/country/org
scope, and lifecycle metadata. Authentication adapters never own this — they
authenticate identities; the Identity Context owns them (Section 2.5).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from contexts.identity.domain.value_objects import AccountStatus, Role


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProviderIdentity:
    """One identity per external/local authentication provider."""
    provider: str
    subject: str
    password_hash: Optional[str] = None
    linked_at: str = field(default_factory=_now_iso)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"provider": self.provider, "subject": self.subject,
                "password_hash": self.password_hash, "linked_at": self.linked_at,
                "metadata": self.metadata}


@dataclass
class User:
    """User aggregate root."""
    user_id: str
    email: str
    full_name: str
    country: str
    tenant_id: str
    # ---- canonical role + status (legacy parity) -------------------------
    role: str = Role.GENERAL_USER.value          # single primary role (legacy schema)
    roles: list[str] = field(default_factory=list)  # also tracked as set for fast PDP checks
    role_confirmed: bool = False
    account_status: str = AccountStatus.ACTIVE.value
    # ---- extended legacy fields (Phase 1A spec) --------------------------
    phone: Optional[str] = None
    organization: Optional[str] = None
    organization_id: Optional[str] = None
    avatar_url: Optional[str] = None
    license_number: Optional[str] = None
    lga_code: Optional[str] = None
    # ---- suspension lifecycle -------------------------------------------
    suspension_reason: Optional[str] = None
    suspended_by: Optional[str] = None
    suspended_at: Optional[str] = None
    # ---- identity providers + audit -------------------------------------
    identities: list[ProviderIdentity] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    last_login_at: Optional[str] = None
    version: int = 1

    @classmethod
    def new(cls, *, email: str, full_name: str, country: str,
            tenant_id: Optional[str] = None, organization: Optional[str] = None,
            organization_id: Optional[str] = None,
            role: str = Role.GENERAL_USER.value,
            phone: Optional[str] = None, lga_code: Optional[str] = None,
            license_number: Optional[str] = None) -> "User":
        return cls(
            user_id="usr_" + uuid.uuid4().hex,
            email=email.strip().lower(),
            full_name=full_name.strip(),
            country=country.upper(),
            tenant_id=tenant_id or "ten_" + uuid.uuid4().hex,
            role=role,
            roles=[role],
            organization=organization,
            organization_id=organization_id,
            phone=phone,
            lga_code=lga_code,
            license_number=license_number,
        )

    # ---- Domain behaviour ----------------------------------------------
    def add_identity(self, identity: ProviderIdentity) -> None:
        for existing in self.identities:
            if existing.provider == identity.provider:
                raise ValueError(f"identity for provider {identity.provider!r} already linked")
        self.identities.append(identity)
        self.updated_at = _now_iso()

    def identity_for(self, provider: str) -> Optional[ProviderIdentity]:
        for ident in self.identities:
            if ident.provider == provider:
                return ident
        return None

    def mark_logged_in(self) -> None:
        self.last_login_at = _now_iso()
        self.updated_at = self.last_login_at

    def can_authenticate(self) -> bool:
        return self.account_status == AccountStatus.ACTIVE.value

    def suspend(self, *, reason: str, by_principal_id: str) -> None:
        if self.account_status == AccountStatus.SUSPENDED.value:
            return
        self.account_status = AccountStatus.SUSPENDED.value
        self.suspension_reason = reason
        self.suspended_by = by_principal_id
        self.suspended_at = _now_iso()
        self.updated_at = self.suspended_at

    def activate(self) -> None:
        self.account_status = AccountStatus.ACTIVE.value
        self.suspension_reason = None
        self.suspended_by = None
        self.suspended_at = None
        self.updated_at = _now_iso()

    def confirm_role(self) -> None:
        self.role_confirmed = True
        self.updated_at = _now_iso()

    def assign_role(self, role: str) -> None:
        from contexts.identity.domain.value_objects import ALL_ROLES
        if role not in ALL_ROLES:
            raise ValueError(f"unknown role: {role}")
        self.role = role
        if role not in self.roles:
            self.roles.append(role)
        self.updated_at = _now_iso()

    # ---- Persistence projections ----------------------------------------
    def to_doc(self) -> dict:
        return {
            "user_id": self.user_id, "email": self.email, "full_name": self.full_name,
            "country": self.country, "tenant_id": self.tenant_id,
            "role": self.role, "roles": list(self.roles),
            "role_confirmed": self.role_confirmed,
            "account_status": self.account_status,
            "phone": self.phone, "organization": self.organization,
            "organization_id": self.organization_id, "avatar_url": self.avatar_url,
            "license_number": self.license_number, "lga_code": self.lga_code,
            "suspension_reason": self.suspension_reason,
            "suspended_by": self.suspended_by, "suspended_at": self.suspended_at,
            "identities": [i.to_dict() for i in self.identities],
            "created_at": self.created_at, "updated_at": self.updated_at,
            "last_login_at": self.last_login_at,
            "version": self.version, "schema_version": 2,
        }

    @classmethod
    def from_doc(cls, doc: dict) -> "User":
        return cls(
            user_id=doc["user_id"], email=doc["email"],
            full_name=doc.get("full_name", ""),
            country=doc.get("country", "NG"),
            tenant_id=doc["tenant_id"],
            role=doc.get("role", Role.GENERAL_USER.value),
            roles=list(doc.get("roles") or [doc.get("role", Role.GENERAL_USER.value)]),
            role_confirmed=bool(doc.get("role_confirmed", False)),
            account_status=doc.get("account_status", AccountStatus.ACTIVE.value),
            phone=doc.get("phone"),
            organization=doc.get("organization"),
            organization_id=doc.get("organization_id"),
            avatar_url=doc.get("avatar_url"),
            license_number=doc.get("license_number"),
            lga_code=doc.get("lga_code"),
            suspension_reason=doc.get("suspension_reason"),
            suspended_by=doc.get("suspended_by"),
            suspended_at=doc.get("suspended_at"),
            identities=[ProviderIdentity(**i) for i in (doc.get("identities") or [])],
            created_at=doc.get("created_at") or _now_iso(),
            updated_at=doc.get("updated_at") or _now_iso(),
            last_login_at=doc.get("last_login_at"),
            version=int(doc.get("version", 1)),
        )

    def public_view(self) -> dict:
        return {
            "user_id": self.user_id, "email": self.email,
            "full_name": self.full_name, "country": self.country,
            "tenant_id": self.tenant_id, "lga_code": self.lga_code,
            "organization_id": self.organization_id, "organization": self.organization,
            "role": self.role, "roles": list(self.roles),
            "role_confirmed": self.role_confirmed,
            "account_status": self.account_status,
            "suspension_reason": self.suspension_reason,
            "suspended_by": self.suspended_by,
            "suspended_at": self.suspended_at,
            "phone": self.phone, "avatar_url": self.avatar_url,
            "license_number": self.license_number,
            "providers": [i.provider for i in self.identities],
            "created_at": self.created_at,
            "last_login_at": self.last_login_at,
        }


# Backwards-compat re-exports
STATUS_ACTIVE = AccountStatus.ACTIVE.value
STATUS_INVITED = "INVITED"  # legacy alias; not used by new code
STATUS_SUSPENDED = AccountStatus.SUSPENDED.value
STATUS_DELETED = "deleted"
