"""Identity value objects — canonical 10-role enum + Email + CountryCode.

Roles are the EXACT legacy set recovered from the Base44 entities (Section 5,
Phase 1 Definitive Delivery Spec). No new roles may be invented; future
domains add namespaced permissions, not new identity roles.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ISO_3166_RE = re.compile(r"^[A-Z]{2}$")


@dataclass(frozen=True)
class Email:
    value: str

    def __post_init__(self) -> None:
        if not _EMAIL_RE.match(self.value):
            raise ValueError(f"invalid email: {self.value!r}")

    @classmethod
    def parse(cls, raw: str) -> "Email":
        return cls((raw or "").strip().lower())

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class CountryCode:
    """ISO 3166-1 alpha-2 country code (e.g. 'NG', 'KE', 'GH')."""
    value: str

    def __post_init__(self) -> None:
        if not _ISO_3166_RE.match(self.value):
            raise ValueError(f"invalid country code: {self.value!r}")

    def __str__(self) -> str:
        return self.value


# ---- THE 10 CANONICAL ROLES (binding) ------------------------------------
class Role(str, Enum):
    GENERAL_USER = "general_user"
    SURVEYOR_GENERAL = "surveyor_general"
    SURVEYOR = "surveyor"
    FIELD_AGENT = "field_agent"
    SUPER_ADMIN = "super_admin"
    COMPLIANCE_OFFICER = "compliance_officer"
    LICENSED_SURVEYOR = "licensed_surveyor"
    SURVEYOR_PARTNER = "surveyor_partner"
    COMMUNITY_VALIDATOR = "community_validator"
    GOVERNMENT_OBSERVER = "government_observer"


ALL_ROLES: frozenset[str] = frozenset(r.value for r in Role)

# ---- Privileged role sets (named ABAC attributes, applied per resource) -
# Section 5: privileged role sets recovered from legacy RLS coverage.
GOVERNANCE_ROLES: frozenset[str] = frozenset({
    Role.SUPER_ADMIN.value,
    Role.SURVEYOR_GENERAL.value,
    Role.COMPLIANCE_OFFICER.value,
})
SURVEY_ROLES: frozenset[str] = frozenset({
    Role.LICENSED_SURVEYOR.value,
    Role.SURVEYOR_PARTNER.value,
    Role.SURVEYOR.value,
})
COMMUNITY_ROLES: frozenset[str] = frozenset({Role.COMMUNITY_VALIDATOR.value})
OBSERVER_ROLES: frozenset[str] = frozenset({Role.GOVERNMENT_OBSERVER.value})
FIELD_ROLES: frozenset[str] = frozenset({Role.FIELD_AGENT.value})


def is_governance(roles) -> bool:
    return bool(set(roles) & GOVERNANCE_ROLES)


def is_survey(roles) -> bool:
    return bool(set(roles) & SURVEY_ROLES)


# ---- Account status (legacy parity) --------------------------------------
class AccountStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    PENDING = "pending"


CAN_AUTHENTICATE_STATUSES: frozenset[str] = frozenset({AccountStatus.ACTIVE.value})


# ---- Backwards-compatible exports (kept for previous tests) -------------
ROLE_PLATFORM_SUPER_ADMIN = Role.SUPER_ADMIN.value
ROLE_IDENTITY_USER = Role.GENERAL_USER.value  # legacy alias; new code should use Role.GENERAL_USER
ROLE_IDENTITY_TENANT_ADMIN = "IDENTITY_TENANT_ADMIN"  # deprecated, kept for migration grace
ROLE_IDENTITY_ORG_ADMIN = "IDENTITY_ORG_ADMIN"
ALL_DEFAULT_ROLES = ALL_ROLES
