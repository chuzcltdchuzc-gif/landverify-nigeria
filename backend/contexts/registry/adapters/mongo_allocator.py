"""Mongo adapter: RegistryNumberAllocator.

Phase 2 §3.2 + Phase 2A §6: atomic, concurrency-safe parcel-number
allocation. Uses `find_one_and_update` with `$inc` and `upsert=True` on a
counters collection keyed by `STATE-LGA-WARD-PROPTYPE`. No read-modify-
write loop. Sequences never decrement, reset, or reuse.

Format: `STATE-LGA-WARD-PROPTYPE-NNNNNN` (6-digit zero-padded sequence).
"""
from __future__ import annotations

import re

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from contexts.registry.domain.value_objects import PropertyType

COUNTER_COLLECTION = "landvault_sequence_counters"

# Strict normalization rules ensure the sequence_key is canonical regardless
# of caller casing or whitespace.
_TOKEN_RE = re.compile(r"^[A-Z0-9]{2,8}$")


def _normalize(token: str, *, length: int = 8) -> str:
    if not token:
        raise ValueError("sequence-key component must not be empty")
    cleaned = re.sub(r"[^A-Za-z0-9]", "", token).upper()
    if not cleaned:
        raise ValueError(f"sequence-key component reduces to empty: {token!r}")
    if len(cleaned) < 2:
        raise ValueError(
            f"sequence-key component too short (<2 chars): {token!r}"
        )
    return cleaned[:length]


class MongoRegistryNumberAllocator:
    """Atomic allocator. Idempotent re-runs return new sequences (never reuse)."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self.collection = db[COUNTER_COLLECTION]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("sequence_key", unique=True)

    async def allocate(self, *, country: str, state: str, lga: str, ward: str,
                       property_type: str, session=None) -> str:
        state_n = _normalize(state, length=5)
        lga_n = _normalize(lga, length=8)
        ward_n = _normalize(ward, length=8)
        # property_type must be one of the canonical 3-letter enums.
        pt = property_type.upper()
        if pt not in {p.value for p in PropertyType}:
            raise ValueError(f"invalid property_type: {property_type!r}")

        sequence_key = f"{state_n}-{lga_n}-{ward_n}-{pt}"

        # Atomic increment with upsert. Concurrency-safe: Mongo guarantees
        # that the operation is atomic at the document level, even across
        # replicaset members.
        doc = await self.collection.find_one_and_update(
            {"sequence_key": sequence_key},
            {
                "$inc": {"counter": 1},
                "$setOnInsert": {"sequence_key": sequence_key,
                                  "country": country},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
            session=session,
        )
        sequence_number: int = doc["counter"]
        if sequence_number < 1:
            # Defensive — should be impossible because $inc starts from
            # absent → 1. Guard against tampered counters.
            raise RuntimeError("allocator returned non-positive sequence")
        return f"{sequence_key}-{sequence_number:06d}"
