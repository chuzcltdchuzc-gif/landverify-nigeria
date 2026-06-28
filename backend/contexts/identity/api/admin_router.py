"""Identity Admin API — /api/v1/identity/*.

Governance endpoints for user suspension/activation, role assignment, service
accounts, and delegation grants. All gated by `super_admin` or
`compliance_officer` per the Phase 1 policy library; downstream resource
authorization is enforced by the centralized engine, not these controllers.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from contexts.identity.application.admin_service import IdentityAdminService
from contexts.identity.domain.value_objects import (
    GOVERNANCE_ROLES,
    Role,
)
from contexts.identity.ports.specifications import (
    ActiveUsersSpecification,
    SuspendedUsersSpecification,
    UsersByCountrySpecification,
    UsersByRoleSpecification,
    UsersByTenantSpecification,
)
from contexts.identity.adapters.mongo_user_repository import MongoUserRepository
from kernel.authorization.pep import require_role
from kernel.persistence.specification import Specification

router = APIRouter(prefix="/v1/identity", tags=["identity-admin"])

_service: IdentityAdminService | None = None
_user_repo: MongoUserRepository | None = None


def configure_admin_router(service: IdentityAdminService,
                           user_repo: MongoUserRepository) -> None:
    global _service, _user_repo
    _service = service
    _user_repo = user_repo


def _svc() -> IdentityAdminService:
    if _service is None:
        raise RuntimeError("IdentityAdminService not configured")
    return _service


def _users() -> MongoUserRepository:
    if _user_repo is None:
        raise RuntimeError("MongoUserRepository not configured")
    return _user_repo


# ---- DTOs ---------------------------------------------------------------
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SuspendRequest(_Strict):
    reason: str = Field(min_length=3, max_length=300)


class AssignRoleRequest(_Strict):
    role: str = Field(min_length=2, max_length=64)


class CreateServiceAccountRequest(_Strict):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=2, max_length=500)
    scopes: list[str] = Field(min_length=1, max_length=64)
    tenant_id: Optional[str] = None
    country: Optional[str] = None
    organization_id: Optional[str] = None


class DelegationRequest(_Strict):
    delegator_id: str
    delegate_id: str
    scope: list[str] = Field(min_length=1)
    valid_from: str
    valid_until: str
    reason: str = Field(min_length=3, max_length=300)


class RevokeRequest(_Strict):
    reason: str = Field(min_length=3, max_length=300)


# ---- User admin endpoints ----------------------------------------------
@router.get("/users")
async def list_users(
    role: Optional[str] = None, country: Optional[str] = None,
    tenant_id: Optional[str] = None, status: Optional[str] = None,
    limit: int = 50, skip: int = 0,
    _user=Depends(require_role(*GOVERNANCE_ROLES)),
):
    """List users filtered by Specifications — no Mongo syntax leaks here."""
    spec: Specification = Specification()
    if status == "active":
        spec = spec.and_(ActiveUsersSpecification())
    elif status == "suspended":
        spec = spec.and_(SuspendedUsersSpecification())
    if role:
        spec = spec.and_(UsersByRoleSpecification(role))
    if country:
        spec = spec.and_(UsersByCountrySpecification(country))
    if tenant_id:
        spec = spec.and_(UsersByTenantSpecification(tenant_id))
    users = await _users().find(spec, limit=min(limit, 200), skip=max(skip, 0),
                                sort=[("created_at", -1)])
    return {"items": [u.public_view() for u in users],
            "specification_clauses": list(spec.clauses)}


@router.post("/users/{user_id}/suspend")
async def suspend_user(user_id: str, body: SuspendRequest,
                       _user=Depends(require_role(*GOVERNANCE_ROLES))):
    return await _svc().suspend_user(user_id=user_id, reason=body.reason)


@router.post("/users/{user_id}/activate")
async def activate_user(user_id: str,
                        _user=Depends(require_role(*GOVERNANCE_ROLES))):
    return await _svc().activate_user(user_id=user_id)


@router.post("/users/{user_id}/role")
async def assign_role(user_id: str, body: AssignRoleRequest,
                      _user=Depends(require_role(Role.SUPER_ADMIN.value,
                                                 Role.COMPLIANCE_OFFICER.value))):
    return await _svc().assign_role(user_id=user_id, role=body.role)


# ---- Service accounts ---------------------------------------------------
@router.post("/service-accounts", status_code=201)
async def create_service_account(body: CreateServiceAccountRequest,
                                 _user=Depends(require_role(Role.SUPER_ADMIN.value))):
    return await _svc().create_service_account(
        name=body.name, description=body.description, scopes=body.scopes,
        tenant_id=body.tenant_id, country=body.country,
        organization_id=body.organization_id,
    )


@router.post("/service-accounts/{account_id}/revoke")
async def revoke_service_account(account_id: str,
                                 _user=Depends(require_role(Role.SUPER_ADMIN.value))):
    return await _svc().revoke_service_account(account_id)


# ---- Delegations --------------------------------------------------------
@router.post("/delegations", status_code=201)
async def grant_delegation(body: DelegationRequest,
                           _user=Depends(require_role(*GOVERNANCE_ROLES))):
    return await _svc().grant_delegation(
        delegator_id=body.delegator_id, delegate_id=body.delegate_id,
        scope=body.scope, valid_from=body.valid_from,
        valid_until=body.valid_until, reason=body.reason,
    )


@router.post("/delegations/{grant_id}/revoke")
async def revoke_delegation(grant_id: str, body: RevokeRequest,
                            _user=Depends(require_role(*GOVERNANCE_ROLES))):
    return await _svc().revoke_delegation(grant_id, body.reason)
