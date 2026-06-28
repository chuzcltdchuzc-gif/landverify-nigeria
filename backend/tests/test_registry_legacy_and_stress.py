"""Phase 2A — Legacy compatibility adapter + N=200 allocator stress test.

These complement test_registry_api.py and test_registry_allocator_concurrency.py
by exercising the public HTTP surface (/api/parcels) end-to-end via dev-login,
and by hammering the allocator at higher concurrency to expose any race.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


def _dev_login(role: str) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/dev-login", json={"role": role}, timeout=15)
    assert r.status_code == 200, r.text
    return s


# ---- Legacy compatibility adapter (POST /api/parcels) ---------------------
class TestLegacyCompatibilityAdapter:
    def test_legacy_post_creates_canonical_registry_record(self):
        s = _dev_login("CITIZEN")
        body = {
            "community": f"TEST_LegShim_{uuid.uuid4().hex[:6]}",
            "ward": "Ikeja Ward 3",
            "lga": "Ikeja",
            "state": "Lagos",
            "property_type": "residential",
            "parcel_number": f"AS-LV-LEGACY-{uuid.uuid4().hex[:6].upper()}",
        }
        r = s.post(f"{BASE_URL}/api/parcels", json=body, timeout=30)
        assert r.status_code == 200, r.text
        out = r.json()
        # Carries registry_id and canonical parcel_number
        assert "registry_id" in out and out["registry_id"].startswith("reg_")
        parcel = out["parcel"]
        assert parcel["parcel_number"].startswith("LAGOS-IKEJA-")
        assert parcel["parcel_number"].endswith("RES-" + parcel["parcel_number"].split("-")[-1])
        # Sequence is 6 digits
        seq = parcel["parcel_number"].split("-")[-1]
        assert len(seq) == 6 and seq.isdigit()
        # Mirror row in legacy 'parcels' collection links back to registry_id
        assert parcel["x_legacy_mirror_of_registry_id"] == out["registry_id"]

        # Verify in Mongo: canonical registry doc + legacy mirror + alias retained
        from motor.motor_asyncio import AsyncIOMotorClient

        async def _check():
            db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
            reg = await db.landvault_landvaults.find_one(
                {"registry_id": out["registry_id"]}, {"_id": 0}
            )
            mir = await db.parcels.find_one(
                {"x_legacy_mirror_of_registry_id": out["registry_id"]}, {"_id": 0}
            )
            return reg, mir

        reg, mir = asyncio.run(_check())
        assert reg is not None
        assert reg["origin"]["source_system"] == "native"
        assert reg["status"] == "draft"
        assert reg["version"] == 1
        # legacy_aliases retains the legacy parcel_number that the caller supplied
        assert body["parcel_number"] in reg.get("legacy_aliases", [])
        assert mir is not None
        assert mir["parcel_number"] == parcel["parcel_number"]


# ---- Allocator stress at N=200 -------------------------------------------
@pytest.mark.asyncio
async def test_allocator_N200_concurrent_no_duplicates():
    from motor.motor_asyncio import AsyncIOMotorClient

    from contexts.registry.adapters.mongo_allocator import (
        MongoRegistryNumberAllocator,
    )

    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    # Use a unique sequence_key to isolate from other tests
    suffix = uuid.uuid4().hex[:6].upper()
    state = f"ST{suffix[:3]}"
    lga = f"LGA{suffix}"
    ward = f"WRD{suffix}"
    alloc = MongoRegistryNumberAllocator(db)
    await alloc.ensure_indexes()

    async def one():
        return await alloc.allocate(
            country="NG", state=state, lga=lga, ward=ward, property_type="RES"
        )

    results = await asyncio.gather(*[one() for _ in range(200)])
    assert len(results) == 200
    # All unique
    assert len(set(results)) == 200, "duplicate parcel_numbers under concurrency"
    # Contiguous sequence 1..200
    seqs = sorted(int(r.split("-")[-1]) for r in results)
    assert seqs == list(range(1, 201)), f"non-contiguous: head={seqs[:5]} tail={seqs[-5:]}"
