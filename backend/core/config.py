"""Shared configuration: env loading, role hierarchy, plans, packs, services."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

APP_VERSION = "1.1.0"
SERVICE_START_TS = datetime.now(timezone.utc)

EMERGENT_SESSION_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"
PAYSTACK_API_BASE = "https://api.paystack.co"

ROLE_RANK = {
    "CITIZEN": 1,
    "COMMUNITY_VALIDATOR": 2,
    "SURVEYOR": 3,
    "LEGAL": 4,
    "LEGAL_USER": 4,
    "INSTITUTIONAL": 5,
    "INSTITUTIONAL_USER": 5,
    "GOVERNMENT_OBSERVER": 6,
    "OBSERVER": 6,
    "ADMIN": 7,
    "SUPER_ADMIN": 8,
}

ROLE_ROUTES = {
    "CITIZEN": "/dashboard",
    "COMMUNITY_VALIDATOR": "/validator",
    "SURVEYOR": "/surveyor",
    "LEGAL": "/legal",
    "LEGAL_USER": "/legal",
    "INSTITUTIONAL": "/institution",
    "INSTITUTIONAL_USER": "/institution",
    "GOVERNMENT_OBSERVER": "/observer",
    "OBSERVER": "/observer",
    "ADMIN": "/admin",
    "SUPER_ADMIN": "/admin",
}

SUBSCRIPTION_PLANS = [
    {"code": "CITIZEN", "name": "Citizen / Family", "monthly_ngn": 2500, "annual_ngn": 24000,
     "description": "Upload family land evidence, view parcel history, download certificates.",
     "features": ["Upload parcels & evidence", "Request attestations", "Download certificates", "100 starter credits/mo"]},
    {"code": "COMMUNITY_VALIDATOR", "name": "Community Validator", "monthly_ngn": 5000, "annual_ngn": 48000,
     "description": "Submit attestations, validate community evidence, access review queue.",
     "features": ["Review queue access", "Submit attestations", "Consensus view", "Conflict alerts"]},
    {"code": "SURVEYOR", "name": "Surveyor Partner", "monthly_ngn": 15000, "annual_ngn": 144000,
     "description": "Full surveyor dashboard, assign parcels, upload survey plans, revenue share.",
     "features": ["My assignments", "Upload survey plans", "Archive import", "Revenue dashboard"]},
    {"code": "LEGAL", "name": "Legal / Due Diligence", "monthly_ngn": 25000, "annual_ngn": 240000,
     "description": "Full due diligence reports, legal search packages, evidence bundles.",
     "features": ["Advanced parcel search", "Due diligence reports", "Legal search package", "Bulk search"]},
    {"code": "INSTITUTIONAL", "name": "Institutional (Bank / Corp)", "monthly_ngn": 75000, "annual_ngn": 720000,
     "description": "Organisation wallet, bulk searches, API access, compliance reports.",
     "features": ["Org wallet", "Bulk verification API", "Compliance reports", "Team management"]},
    {"code": "GOVERNMENT_OBSERVER", "name": "Government Observer", "monthly_ngn": 0, "annual_ngn": 0,
     "description": "Read-only access to anonymised aggregate data, pilot dashboards.",
     "features": ["Pilot overview", "Activity heatmap", "Trust metrics", "Read-only"]},
]

CREDIT_PACKS = [
    {"code": "STARTER", "name": "Starter", "credits": 100, "price_ngn": 5000},
    {"code": "PROFESSIONAL", "name": "Professional", "credits": 500, "price_ngn": 20000},
    {"code": "ENTERPRISE", "name": "Enterprise", "credits": 2000, "price_ngn": 70000},
]

SERVICE_CATALOG = {
    "PARCEL_UPLOAD": {"name": "Parcel Upload", "credits": 5},
    "PARCEL_VERIFICATION": {"name": "Parcel Verification", "credits": 10},
    "SURVEY_PLAN_VERIFICATION": {"name": "Survey Plan Verification", "credits": 15},
    "COMMUNITY_EVIDENCE_REPORT": {"name": "Community Evidence Report", "credits": 8},
    "DUE_DILIGENCE_REPORT": {"name": "Due Diligence Report", "credits": 25},
    "DIGITAL_CERTIFICATE": {"name": "Digital Certificate Generation", "credits": 5},
    "ARCHIVE_DIGITISATION": {"name": "Archive Digitisation", "credits": 20},
    "LEGAL_SEARCH_PACKAGE": {"name": "Legal Search Package", "credits": 30},
    "BANK_SEARCH_PACKAGE": {"name": "Bank Search Package", "credits": 30},
    "COMPLIANCE_REPORT": {"name": "Compliance Report", "credits": 20},
}

CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

REPORTS_DIR = ROOT_DIR / "_reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
