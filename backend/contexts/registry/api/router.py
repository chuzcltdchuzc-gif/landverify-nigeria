"""FastAPI router for the Registry context — `/api/v1/registry/landvaults`.

Every endpoint:
1. Resolves the ExecutionContext via the PEP dependency (`require_auth`).
2. Authorizes the action through the centralized PDP (`enforce`) — the
   PDP returns the policy_id, audit + metrics are recorded automatically.
3. Delegates to the Application Service.

Per Phase 2A §9: authorization is centralized; clients never assert their
own tenant/country/role.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, status

from contexts.registry.api.dtos import (
    ArchiveLandVaultRequest,
    CreateLandVaultRequest,
    LandVaultListResponse,
    LandVaultResponse,
    RecordOwnershipTransferRequest,
    UpdateCommunityDataRequest,
    UpdateGeometryRequest,
    UpdateLocationRequest,
    UpdateOwnershipContactRequest,
    UpdateSurveyRequest,
)
from contexts.registry.application import (
    PRIVILEGED_REGISTRY_ROLES,
    RegistryCommandService,
    RegistryQueryService,
)
from contexts.registry.ports.specifications import (
    LandVaultSpec,
    ByOwnerEmail,
    ByStatus,
    CreatedBy,
)
from kernel.authorization.pep import enforce, require_auth
from kernel.persistence.context import ExecutionContext

router = APIRouter(prefix="/v1/registry/landvaults", tags=["registry"])

_command_service: Optional[RegistryCommandService] = None
_query_service: Optional[RegistryQueryService] = None


def configure_router(command: RegistryCommandService,
                     query: RegistryQueryService) -> None:
    global _command_service, _query_service
    _command_service = command
    _query_service = query


def _command() -> RegistryCommandService:
    if _command_service is None:
        raise RuntimeError("registry command service not configured")
    return _command_service


def _query() -> RegistryQueryService:
    if _query_service is None:
        raise RuntimeError("registry query service not configured")
    return _query_service


# ---- Endpoints -----------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED, response_model=LandVaultResponse)
async def create_landvault(payload: CreateLandVaultRequest,
                           ctx: ExecutionContext = Depends(require_auth)):
    await enforce("registry.landvault.create",
                  resource={"resource_type": "land_vault"})
    # country_code is derived from ExecutionContext unless caller is super_admin.
    country_code = payload.country_code
    if not country_code or "super_admin" not in ctx.roles:
        country_code = ctx.country or country_code
    if not country_code:
        country_code = "NG"  # platform default
    body = payload.model_dump(exclude={"country_code"})
    body["country_code"] = country_code
    # Normalize Pydantic enums → plain strings.
    body["property_type"] = body["property_type"].value if hasattr(
        body["property_type"], "value") else body["property_type"]
    body["ownership_type"] = body["ownership_type"].value if hasattr(
        body["ownership_type"], "value") else body["ownership_type"]
    if body.get("geometry") is not None:
        body["geometry"] = dict(body["geometry"])
    return await _command().create_landvault(**body)


@router.get("/{registry_id}", response_model=LandVaultResponse)
async def get_landvault(registry_id: str,
                       _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("registry.landvault.read",
                  resource={"resource_type": "land_vault",
                            "resource_id": registry_id})
    return await _query().get(registry_id)


@router.get("", response_model=LandVaultListResponse)
async def list_landvaults(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    mine: bool = Query(default=False),
    owner_email: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    skip: int = Query(default=0, ge=0),
    ctx: ExecutionContext = Depends(require_auth),
):
    await enforce("registry.landvault.list",
                  resource={"resource_type": "land_vault"})
    spec = LandVaultSpec()
    if status_filter:
        spec = spec.and_(ByStatus(status_filter))
    if mine:
        spec = spec.and_(CreatedBy(ctx.principal_id))
    if owner_email:
        spec = spec.and_(ByOwnerEmail(owner_email))
    return await _query().list(spec=spec, limit=limit, skip=skip)


@router.patch("/{registry_id}/location", response_model=LandVaultResponse)
async def update_location(registry_id: str, payload: UpdateLocationRequest,
                         _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("registry.landvault.update.location",
                  resource={"resource_type": "land_vault",
                            "resource_id": registry_id})
    return await _command().update_location(registry_id,
                                            **payload.model_dump(exclude_none=True))


@router.patch("/{registry_id}/geometry", response_model=LandVaultResponse)
async def update_geometry(registry_id: str, payload: UpdateGeometryRequest,
                         _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("registry.landvault.update.geometry",
                  resource={"resource_type": "land_vault",
                            "resource_id": registry_id})
    body = payload.model_dump(exclude_none=True)
    body["geometry"] = dict(body["geometry"])
    return await _command().update_geometry(registry_id, **body)


@router.patch("/{registry_id}/ownership-contact", response_model=LandVaultResponse)
async def update_ownership_contact(registry_id: str,
                                   payload: UpdateOwnershipContactRequest,
                                   _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("registry.landvault.update.ownership_contact",
                  resource={"resource_type": "land_vault",
                            "resource_id": registry_id})
    return await _command().update_ownership_contact(
        registry_id, **payload.model_dump(exclude_none=True))


@router.post("/{registry_id}/ownership-transfer", response_model=LandVaultResponse)
async def record_ownership_transfer(registry_id: str,
                                    payload: RecordOwnershipTransferRequest,
                                    _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("registry.landvault.ownership.transfer",
                  resource={"resource_type": "land_vault",
                            "resource_id": registry_id})
    body = payload.model_dump(exclude_none=True)
    if "ownership_type" in body and hasattr(body["ownership_type"], "value"):
        body["ownership_type"] = body["ownership_type"].value
    return await _command().record_ownership_transfer(registry_id, **body)


@router.patch("/{registry_id}/survey", response_model=LandVaultResponse)
async def update_survey(registry_id: str, payload: UpdateSurveyRequest,
                       _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("registry.landvault.update.survey",
                  resource={"resource_type": "land_vault",
                            "resource_id": registry_id})
    return await _command().update_survey(registry_id,
                                          **payload.model_dump(exclude_none=True))


@router.patch("/{registry_id}/community-data", response_model=LandVaultResponse)
async def update_community_data(registry_id: str,
                               payload: UpdateCommunityDataRequest,
                               _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("registry.landvault.update.community_data",
                  resource={"resource_type": "land_vault",
                            "resource_id": registry_id})
    return await _command().update_community_data(
        registry_id, **payload.model_dump(exclude_none=True))


@router.post("/{registry_id}/archive", response_model=LandVaultResponse)
async def archive_landvault(registry_id: str, payload: ArchiveLandVaultRequest,
                           _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("registry.landvault.archive",
                  resource={"resource_type": "land_vault",
                            "resource_id": registry_id})
    return await _command().archive(registry_id,
                                    reason=payload.reason,
                                    expected_version=payload.expected_version)
