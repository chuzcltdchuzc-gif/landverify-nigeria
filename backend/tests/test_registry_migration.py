"""Phase 2A — Legacy → Registry migration tool tests (Directive §10).

Validates:
* Mapping of LandParcel and LandVaultParcel rows.
* Idempotency: running twice produces no duplicates and no audit noise.
* Quarantine for invalid / unmappable rows (NOT auto-merged).
* Provenance: `origin.source_system` and `origin.source_id` are stamped.
* Legacy ids preserved as `legacy_aliases[]`.
* Repeatability without data corruption.
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from contexts.registry.adapters.mongo_repository import LANDVAULT_COLLECTION
from contexts.registry.migration import (
    QUARANTINE_COLLECTION,
    migrate,
)


@pytest_asyncio.fixture
async def mig_db():
    mongo_url = os.environ["MONGO_URL"]
    name = os.environ["DB_NAME"] + "_migtest_" + uuid.uuid4().hex[:6]
    client = AsyncIOMotorClient(mongo_url)
    db = client[name]
    yield client, db
    await client.drop_database(name)
    client.close()


def _legacy_parcel(**over):
    base = {
        "id": "lp_" + uuid.uuid4().hex[:8],
        "parcel_number": "AS-LV-2025-" + uuid.uuid4().hex[:6].upper(),
        "state": "LAGOS", "lga": "IKEJA", "ward": "WARD3",
        "property_type": "residential", "ownership_type": "individual",
        "owner_name": "Ada Lovelace", "owner_email": "ada@example.com",
        "owner_phone": "+234-800-0001111", "country": "NG",
        "tenant_id": "default", "created_by": "usr_creator",
        "geojson_polygon": {"type": "Polygon",
                             "coordinates": [[[3.3, 6.5], [3.4, 6.5],
                                              [3.4, 6.6], [3.3, 6.6],
                                              [3.3, 6.5]]]},
    }
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_migration_dry_run_does_not_write(mig_db):
    client, db = mig_db
    await db["parcels"].insert_one(_legacy_parcel())
    report = await migrate(db=db, client=client, import_batch="dry-1", commit=False)
    assert report.scanned == 1
    assert report.migrated == 1  # would-be-migrated
    count = await db[LANDVAULT_COLLECTION].count_documents({})
    assert count == 0  # nothing actually written


@pytest.mark.asyncio
async def test_migration_commits_with_provenance(mig_db):
    client, db = mig_db
    legacy = _legacy_parcel()
    await db["parcels"].insert_one(legacy)
    report = await migrate(db=db, client=client, import_batch="commit-1", commit=True)
    assert report.migrated == 1
    doc = await db[LANDVAULT_COLLECTION].find_one({})
    assert doc is not None
    assert doc["origin"]["source_system"] == "LandParcel"
    assert doc["origin"]["source_id"] == legacy["id"]
    assert doc["origin"]["import_batch"] == "commit-1"
    # Provenance fields are immutable — verified by the aggregate.
    # Legacy id preserved as alias.
    assert legacy["parcel_number"] in doc["legacy_aliases"]
    assert legacy["id"] in doc["legacy_aliases"]
    # NEW canonical parcel_number was allocated (different from legacy).
    assert doc["parcel_number"] != legacy["parcel_number"]
    assert doc["parcel_number"].split("-")[-1].isdigit()


@pytest.mark.asyncio
async def test_migration_is_idempotent(mig_db):
    client, db = mig_db
    await db["parcels"].insert_one(_legacy_parcel())
    r1 = await migrate(db=db, client=client, import_batch="idem-1", commit=True)
    r2 = await migrate(db=db, client=client, import_batch="idem-2", commit=True)
    assert r1.migrated == 1
    assert r2.scanned == 1
    assert r2.migrated == 0  # already imported on second run
    assert r2.skipped_already_imported == 1
    # Exactly one canonical record on disk.
    assert await db[LANDVAULT_COLLECTION].count_documents({}) == 1


@pytest.mark.asyncio
async def test_unmappable_row_is_quarantined_not_merged(mig_db):
    """Missing required field → row goes to quarantine, never to Registry."""
    client, db = mig_db
    bad = _legacy_parcel()
    bad.pop("owner_name")
    await db["parcels"].insert_one(bad)
    report = await migrate(db=db, client=client, import_batch="q-1", commit=True)
    assert report.quarantined == 1
    assert report.migrated == 0
    q = await db[QUARANTINE_COLLECTION].find_one({})
    assert q["source"] == "LandParcel"
    assert "missing or unmappable" in q["reason"]
    assert await db[LANDVAULT_COLLECTION].count_documents({}) == 0


@pytest.mark.asyncio
async def test_landvaultparcel_source_is_migrated(mig_db):
    """The migration also covers the `land_vault_parcels` legacy collection."""
    client, db = mig_db
    legacy = _legacy_parcel(id="lvp_001")
    await db["land_vault_parcels"].insert_one(legacy)
    report = await migrate(db=db, client=client, import_batch="lvp-1", commit=True)
    assert report.migrated == 1
    doc = await db[LANDVAULT_COLLECTION].find_one({})
    assert doc["origin"]["source_system"] == "LandVaultParcel"


@pytest.mark.asyncio
async def test_mixed_sources_do_not_collide(mig_db):
    """A LandParcel row and a LandVaultParcel row with the same legacy id
    are imported into DIFFERENT canonical records (no auto-merge)."""
    client, db = mig_db
    a = _legacy_parcel(id="shared_id", owner_name="From LandParcel")
    b = _legacy_parcel(id="shared_id", owner_name="From LandVaultParcel")
    await db["parcels"].insert_one(a)
    await db["land_vault_parcels"].insert_one(b)
    report = await migrate(db=db, client=client, import_batch="mix-1", commit=True)
    assert report.migrated == 2
    assert await db[LANDVAULT_COLLECTION].count_documents({}) == 2
    sources = sorted([d["origin"]["source_system"]
                      async for d in db[LANDVAULT_COLLECTION].find({})])
    assert sources == ["LandParcel", "LandVaultParcel"]
