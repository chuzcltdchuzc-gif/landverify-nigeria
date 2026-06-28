"""Per-role Pydantic DTOs for the Registry API (Phase 2 §3.3).

All input models use `model_config = {"extra": "forbid"}` to defeat
mass-assignment attacks. Fields owned by the platform (`registry_id`,
`parcel_number`, `tenant_id`, `country_code`, `version`, audit fields,
provenance) are NOT in any input model — clients can never set them.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from contexts.registry.domain.value_objects import (
    LandVaultStatus,
    OwnershipType,
    PropertyType,
)


# ---- Geometry input (GeoJSON-like) ---------------------------------------

class GeometryIn(BaseModel):
    """Minimal GeoJSON Polygon — full validation happens in the domain."""
    model_config = ConfigDict(extra="forbid")
    type: str = "Polygon"
    coordinates: list[list[list[float]]]


# ---- Create ---------------------------------------------------------------

class CreateLandVaultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # location / admin
    state: str = Field(..., min_length=1, max_length=64)
    lga: str = Field(..., min_length=1, max_length=64)
    ward: str = Field(..., min_length=1, max_length=64)
    community: Optional[str] = Field(default=None, max_length=128)
    address: Optional[str] = Field(default=None, max_length=512)
    title: Optional[str] = Field(default=None, max_length=256)
    property_type: PropertyType
    # ownership
    ownership_type: OwnershipType
    owner_name: str = Field(..., min_length=1, max_length=256)
    owner_email: Optional[EmailStr] = None
    owner_phone: Optional[str] = Field(default=None, max_length=64)
    # geometry (optional at create — surveyors update later)
    geometry: Optional[GeometryIn] = None
    # operational
    field_agent_email: Optional[EmailStr] = None
    legacy_aliases: list[str] = Field(default_factory=list, max_length=10)
    # country at creation: comes from ExecutionContext OR may be supplied
    # by privileged super_admin only — the application layer enforces.
    country_code: Optional[str] = Field(default=None, min_length=2, max_length=3)


# ---- Task-oriented update DTOs --------------------------------------------

class UpdateLocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: Optional[int] = Field(default=None, ge=1)
    state: Optional[str] = None
    lga: Optional[str] = None
    ward: Optional[str] = None
    ward_code: Optional[str] = None
    community: Optional[str] = None
    village: Optional[str] = None
    address: Optional[str] = None
    land_use: Optional[str] = None
    size_sqm: Optional[float] = Field(default=None, ge=0)
    size_hectares: Optional[float] = Field(default=None, ge=0)


class UpdateGeometryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: Optional[int] = Field(default=None, ge=1)
    geometry: GeometryIn
    boundary_source: Optional[str] = None
    boundary_area: Optional[float] = Field(default=None, ge=0)
    boundary_perimeter: Optional[float] = Field(default=None, ge=0)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)


class UpdateOwnershipContactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: Optional[int] = Field(default=None, ge=1)
    owner_email: Optional[EmailStr] = None
    owner_phone: Optional[str] = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _at_least_one(self):
        if self.owner_email is None and self.owner_phone is None:
            raise ValueError("at least one of owner_email or owner_phone is required")
        return self


class RecordOwnershipTransferRequest(BaseModel):
    """A LEGAL ownership change. Distinct from contact edits."""
    model_config = ConfigDict(extra="forbid")
    expected_version: Optional[int] = Field(default=None, ge=1)
    ownership_type: Optional[OwnershipType] = None
    owner_name: Optional[str] = Field(default=None, min_length=1, max_length=256)
    owner_nin: Optional[str] = Field(default=None, max_length=64)
    representative_name: Optional[str] = None
    representative_authority: Optional[str] = None
    family_head: Optional[str] = None
    family_members: Optional[list[dict]] = None
    reason: str = Field(default="ownership change", max_length=512)


class UpdateSurveyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: Optional[int] = Field(default=None, ge=1)
    survey_plan_url: Optional[str] = None
    surveyor_id: Optional[str] = None
    surveyor_name: Optional[str] = None
    surveyor_licence: Optional[str] = None
    survey_date: Optional[str] = None
    survey_status: Optional[str] = None
    field_agent_email: Optional[EmailStr] = None


class UpdateCommunityDataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: Optional[int] = Field(default=None, ge=1)
    verbal_consent: Optional[bool] = None
    community_confirmed: Optional[bool] = None
    witness_records: Optional[list[dict]] = None


class ArchiveLandVaultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: Optional[int] = Field(default=None, ge=1)
    reason: str = Field(..., min_length=3, max_length=512)


# ---- Response models ------------------------------------------------------

class LandVaultResponse(BaseModel):
    """Per-role projected response. Field set varies by viewer role; we
    keep this Pydantic model permissive so projection happens upstream."""
    model_config = ConfigDict(extra="allow")
    registry_id: str
    parcel_number: str
    status: str
    version: int


class LandVaultListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[dict]
    total: int
    limit: int
    skip: int
