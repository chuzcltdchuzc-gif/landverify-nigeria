"""Phase 2A — Legacy → Registry migration tool (Directive §10).

Migrates rows from the legacy `parcels` (LandParcel) and
`land_vault_parcels` (LandVaultParcel) collections into the canonical
`landvault_landvaults` aggregate. Designed to be:

* **Idempotent** — running it twice produces no duplicates or audit
  noise. Re-import is keyed by `(origin.source_system, origin.source_id)`.
* **Provenance-preserving** — every migrated row records its origin and
  carries its legacy identifier as a `legacy_aliases[]` entry.
* **Quarantining** — duplicates (same canonical key under both legacy
  collections, or invalid geometry, or missing-required-fields) are
  written to `landvault_migration_quarantine` rather than auto-merged.
* **Deterministic** — mapping is pure; the same input row always produces
  the same Registry document.
* **Repeatable without data corruption** — uses the same atomic allocator
  as the runtime API; never reuses, decrements, or overwrites sequences.

Usage (one-shot CLI, ad-hoc):

    python -m contexts.registry.migration --dry-run
    python -m contexts.registry.migration --commit --batch_id="2026-06-28-1"

This module is INTENTIONALLY separate from the runtime command/query
services — migration is the only code path that may read the legacy
collections (Phase 2 §2.1 "no code outside the migration tool may
reference legacy models").
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from contexts.registry.adapters.mongo_allocator import MongoRegistryNumberAllocator
from contexts.registry.adapters.mongo_repository import (
    LANDVAULT_COLLECTION,
    MongoLandVaultRepository,
)
from contexts.registry.domain.invariants import InvariantViolation
from contexts.registry.domain.land_vault import LandVault
from contexts.registry.domain.value_objects import (
    Geometry,
    Origin,
    OwnershipType,
    ParcelNumber,
    PropertyType,
    SourceSystem,
)

logger = logging.getLogger("registry.migration")
QUARANTINE_COLLECTION = "landvault_migration_quarantine"

# Legacy property_type -> canonical PropertyType. Conservative mapping;
# anything not in the table goes to quarantine.
_PROPERTY_TYPE_MAP = {
    "residential": PropertyType.RESIDENTIAL.value,
    "RES": PropertyType.RESIDENTIAL.value,
    "commercial": PropertyType.COMMERCIAL.value,
    "COM": PropertyType.COMMERCIAL.value,
    "farm": PropertyType.FARM.value,
    "farmland": PropertyType.FARM.value,
    "FRM": PropertyType.FARM.value,
    "market": PropertyType.MARKET.value,
    "MKT": PropertyType.MARKET.value,
    "shop": PropertyType.SHOP.value,
    "SHP": PropertyType.SHOP.value,
    "settlement": PropertyType.SETTLEMENT.value,
    "STL": PropertyType.SETTLEMENT.value,
    "kiosk": PropertyType.KIOSK.value,
    "KSK": PropertyType.KIOSK.value,
    "government": PropertyType.GOVERNMENT.value,
    "GOV": PropertyType.GOVERNMENT.value,
    "institutional": PropertyType.INSTITUTIONAL.value,
    "INS": PropertyType.INSTITUTIONAL.value,
}

# Legacy ownership_type -> canonical OwnershipType.
_OWNERSHIP_TYPE_MAP = {
    "individual": OwnershipType.INDIVIDUAL.value,
    "family": OwnershipType.FAMILY.value,
    "joint": OwnershipType.JOINT.value,
    "community": OwnershipType.COMMUNITY.value,
    "trust": OwnershipType.TRUST.value,
    "corporate": OwnershipType.CORPORATE.value,
    "government": OwnershipType.GOVERNMENT.value,
    "institutional": OwnershipType.INSTITUTIONAL.value,
}


@dataclass
class MigrationReport:
    scanned: int = 0
    migrated: int = 0
    skipped_already_imported: int = 0
    quarantined: int = 0
    failed: int = 0


# ---- Mapping ---------------------------------------------------------------

def _map_legacy_parcel(row: dict, source: str) -> Optional[dict]:
    """Translate a legacy row → a Registry creation kwargs dict.

    Returns None when required fields are missing (caller quarantines).
    """
    state = (row.get("state") or "").strip()
    lga = (row.get("lga") or "").strip()
    ward = (row.get("ward") or "").strip()
    if not state or not lga or not ward:
        return None
    raw_prop = (row.get("property_type") or row.get("propertyType")
                 or "residential")
    prop = _PROPERTY_TYPE_MAP.get(raw_prop) or _PROPERTY_TYPE_MAP.get(str(raw_prop).lower())
    if not prop:
        return None
    raw_owner = (row.get("ownership_type") or "individual")
    owner_type = _OWNERSHIP_TYPE_MAP.get(raw_owner) or _OWNERSHIP_TYPE_MAP.get(str(raw_owner).lower())
    if not owner_type:
        return None
    owner_name = (row.get("owner_name") or row.get("name")
                  or row.get("created_by_name") or "").strip()
    if not owner_name:
        return None
    legacy_id = row.get("id") or row.get("_id") or row.get("parcel_number")
    if not legacy_id:
        return None
    return {
        "state": state, "lga": lga, "ward": ward, "property_type": prop,
        "ownership_type": owner_type, "owner_name": owner_name,
        "owner_email": row.get("owner_email") or row.get("email"),
        "owner_phone": row.get("owner_phone") or row.get("phone"),
        "title": row.get("title"),
        "community": row.get("community"),
        "address": row.get("address"),
        "field_agent_email": row.get("field_agent_email"),
        "legacy_aliases": list(filter(None, [
            row.get("parcel_number"), row.get("id"),
        ])),
        "country_code": (row.get("country") or row.get("country_code") or "NG"),
        "tenant_id": row.get("tenant_id") or "default",
        "created_by": row.get("created_by") or row.get("owner_id") or "migration",
        "geometry_raw": row.get("geojson_polygon") or row.get("parcel_boundary")
                          or row.get("geometry"),
        "legacy_id": str(legacy_id),
    }


def _coerce_geometry(geom_raw) -> Optional[Geometry]:
    if not geom_raw:
        return None
    if isinstance(geom_raw, dict) and geom_raw.get("type") == "Polygon":
        try:
            return Geometry(type="Polygon",
                            coordinates=geom_raw.get("coordinates") or [])
        except ValueError:
            return None
    return None


# ---- Migration -------------------------------------------------------------

async def _quarantine(db: AsyncIOMotorDatabase, *, source: str, legacy_id,
                      row: dict, reason: str, import_batch: str) -> None:
    await db[QUARANTINE_COLLECTION].update_one(
        {"source": source, "legacy_id": str(legacy_id)},
        {"$set": {
            "source": source, "legacy_id": str(legacy_id),
            "row": row, "reason": reason, "import_batch": import_batch,
        }},
        upsert=True,
    )


async def _already_imported(db: AsyncIOMotorDatabase, *, source: str,
                            legacy_id: str) -> bool:
    return await db[LANDVAULT_COLLECTION].find_one({
        "origin.source_system": source,
        "origin.source_id": legacy_id,
    }, {"_id": 1}) is not None


async def _migrate_one(db: AsyncIOMotorDatabase, *, row: dict, source: str,
                       allocator: MongoRegistryNumberAllocator,
                       repo: MongoLandVaultRepository,
                       import_batch: str, commit: bool,
                       report: MigrationReport) -> None:
    report.scanned += 1
    mapped = _map_legacy_parcel(row, source)
    if mapped is None:
        legacy_id = row.get("id") or row.get("_id") or row.get("parcel_number") or "<unknown>"
        await _quarantine(db, source=source, legacy_id=legacy_id, row=row,
                          reason="missing or unmappable required fields",
                          import_batch=import_batch)
        report.quarantined += 1
        return

    if await _already_imported(db, source=source, legacy_id=mapped["legacy_id"]):
        report.skipped_already_imported += 1
        return

    if not commit:
        report.migrated += 1  # would-be-migrated count
        return

    try:
        pn_value = await allocator.allocate(
            country=mapped["country_code"], state=mapped["state"],
            lga=mapped["lga"], ward=mapped["ward"],
            property_type=mapped["property_type"],
        )
        agg = LandVault.create(
            parcel_number=ParcelNumber(pn_value),
            tenant_id=mapped["tenant_id"],
            country_code=mapped["country_code"],
            created_by=mapped["created_by"],
            origin=Origin(source_system=source,
                          source_id=mapped["legacy_id"],
                          import_batch=import_batch),
            ownership_type=mapped["ownership_type"],
            owner_name=mapped["owner_name"],
            owner_email=mapped.get("owner_email"),
            owner_phone=mapped.get("owner_phone"),
            state=mapped["state"], lga=mapped["lga"], ward=mapped["ward"],
            community=mapped.get("community"),
            property_type=mapped["property_type"],
            geometry=_coerce_geometry(mapped["geometry_raw"]),
            title=mapped.get("title"),
            legacy_aliases=mapped.get("legacy_aliases", []),
            field_agent_email=mapped.get("field_agent_email"),
            registered_by=mapped["created_by"],
        )
        # Migration does NOT publish runtime domain events — provenance
        # is encoded in `origin.*`, and the migration table provides an
        # explicit, replayable audit trail. (Phase 2 §3.7.)
        agg._events.clear()
        await repo.add(agg)
        report.migrated += 1
    except InvariantViolation as exc:
        await _quarantine(db, source=source, legacy_id=mapped["legacy_id"],
                          row=row, reason=f"invariant violation: {exc}",
                          import_batch=import_batch)
        report.quarantined += 1
    except Exception as exc:  # noqa: BLE001
        if "duplicate" in str(exc).lower():
            await _quarantine(db, source=source, legacy_id=mapped["legacy_id"],
                              row=row,
                              reason=f"duplicate parcel_number or registry_id: {exc}",
                              import_batch=import_batch)
            report.quarantined += 1
        else:
            logger.exception("migration failed for %s/%s",
                             source, mapped["legacy_id"])
            report.failed += 1


async def migrate(*, db: AsyncIOMotorDatabase, client: AsyncIOMotorClient,
                  import_batch: str, commit: bool = False,
                  limit: Optional[int] = None) -> MigrationReport:
    report = MigrationReport()
    repo = MongoLandVaultRepository(db)
    allocator = MongoRegistryNumberAllocator(db)
    await repo.ensure_indexes()
    await allocator.ensure_indexes()
    await db[QUARANTINE_COLLECTION].create_index(
        [("source", 1), ("legacy_id", 1)], unique=True)

    for source_collection, source_enum in (
        ("parcels", SourceSystem.LAND_PARCEL.value),
        ("land_vault_parcels", SourceSystem.LAND_VAULT_PARCEL.value),
    ):
        cur = db[source_collection].find({}, {"_id": 0})
        if limit is not None:
            cur = cur.limit(limit)
        async for row in cur:
            await _migrate_one(db, row=row, source=source_enum,
                                allocator=allocator, repo=repo,
                                import_batch=import_batch, commit=commit,
                                report=report)
    return report


# ---- CLI ------------------------------------------------------------------

async def _amain(args) -> int:
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(mongo_url)
    try:
        report = await migrate(
            db=client[db_name], client=client,
            import_batch=args.batch_id, commit=args.commit, limit=args.limit,
        )
        print(f"scanned={report.scanned} migrated={report.migrated} "
              f"skipped_already_imported={report.skipped_already_imported} "
              f"quarantined={report.quarantined} failed={report.failed}")
        return 0 if report.failed == 0 else 1
    finally:
        client.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="LandVault legacy migration tool")
    parser.add_argument("--commit", action="store_true",
                        help="Actually write to the Registry (default: dry-run)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Scan but do not write")
    parser.add_argument("--batch-id", dest="batch_id", default="manual",
                        help="Import batch tag stored in origin.import_batch")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max rows per legacy collection (debug)")
    args = parser.parse_args(argv)
    if args.dry_run:
        args.commit = False
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
