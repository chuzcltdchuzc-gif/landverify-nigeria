"""All request/response Pydantic models in one place."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    role: str = "CITIZEN"
    subscription_plan: Optional[str] = "CITIZEN"
    subscription_status: str = "TRIAL"
    tenant_id: str
    organisation_name: Optional[str] = None
    phone: Optional[str] = None
    onboarding_complete: bool = False
    created_at: Optional[str] = None


class ParcelCreate(BaseModel):
    parcel_number: Optional[str] = None
    community: str
    ward: str
    lga: str
    state: str
    coordinates: Optional[dict] = None
    description: Optional[str] = None


class AttestationCreate(BaseModel):
    parcel_id: str
    role: str
    statement: str = Field(min_length=20)
    relationship_to_land: str
    years_of_knowledge: int = Field(ge=0, le=100)
    signature_url: Optional[str] = None
    photo_url: Optional[str] = None
    supporting_docs: list[str] = []


class EvidenceCreate(BaseModel):
    parcel_id: str
    evidence_type: str
    file_url: str
    file_name: str
    mime_type: str = "application/pdf"
    file_size: int = 0
    description: Optional[str] = None


class CheckoutCreate(BaseModel):
    pack_code: Optional[str] = None
    plan_code: Optional[str] = None
    billing_cycle: Optional[str] = "monthly"
    origin_url: str


class PaystackInit(BaseModel):
    pack_code: Optional[str] = None
    plan_code: Optional[str] = None
    billing_cycle: Optional[str] = "monthly"
    origin_url: str


class PortfolioCreate(BaseModel):
    name: str
    parcel_numbers: list[str]
