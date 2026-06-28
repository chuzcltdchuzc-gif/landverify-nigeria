"""Phase 2A — Allocator concurrency tests (Directive §6).

Fires N parallel allocations on the SAME sequence_key and asserts:
* All N parcel_numbers are unique.
* All N use the canonical STATE-LGA-WARD-PROPTYPE-NNNNNN format.
* The counter document advanced by exactly N.
* Different sequence_keys do not interfere.
"""
from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from contexts.registry.adapters.mongo_allocator import (
    COUNTER_COLLECTION,
    MongoRegistryNumberAllocator,
)


@pytest_asyncio.fixture
async def allocator():
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"] + "_alloc_test"
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    await db[COUNTER_COLLECTION].delete_many({})
    a = MongoRegistryNumberAllocator(db)
    await a.ensure_indexes()
    try:
        yield a, db
    finally:
        await db[COUNTER_COLLECTION].delete_many({})
        client.close()


@pytest.mark.asyncio
async def test_parallel_allocations_produce_unique_parcel_numbers(allocator) -> None:
    a, db = allocator
    N = 50
    tasks = [
        a.allocate(country="NG", state="LAGOS", lga="IKEJA",
                   ward="WARD3", property_type="RES")
        for _ in range(N)
    ]
    results = await asyncio.gather(*tasks)
    assert len(set(results)) == N, "duplicate parcel_numbers under concurrency!"
    # All look canonical
    for pn in results:
        parts = pn.split("-")
        assert len(parts) == 5
        assert parts[0] == "LAGOS"
        assert parts[1] == "IKEJA"
        assert parts[2] == "WARD3"
        assert parts[3] == "RES"
        assert len(parts[4]) == 6 and parts[4].isdigit()
    # Counter advanced by exactly N
    doc = await db[COUNTER_COLLECTION].find_one(
        {"sequence_key": "LAGOS-IKEJA-WARD3-RES"})
    assert doc["counter"] == N
    # Sequence numbers form a contiguous range 1..N (no gaps, no reuse).
    nums = sorted(int(r.split("-")[-1]) for r in results)
    assert nums == list(range(1, N + 1))


@pytest.mark.asyncio
async def test_different_sequence_keys_are_isolated(allocator) -> None:
    a, _ = allocator
    a1 = await a.allocate(country="NG", state="LAGOS", lga="IKEJA",
                          ward="WARD3", property_type="RES")
    a2 = await a.allocate(country="NG", state="LAGOS", lga="IKEJA",
                          ward="WARD3", property_type="COM")
    a3 = await a.allocate(country="NG", state="OYO", lga="IBADAN",
                          ward="WARD1", property_type="RES")
    # Each different sequence_key starts at 000001
    assert a1.endswith("-000001")
    assert a2.endswith("-000001")
    assert a3.endswith("-000001")
    assert a1.split("-")[3] == "RES"
    assert a2.split("-")[3] == "COM"
    assert a3.split("-")[1] == "IBADAN"


@pytest.mark.asyncio
async def test_invalid_property_type_rejected(allocator) -> None:
    a, _ = allocator
    with pytest.raises(ValueError):
        await a.allocate(country="NG", state="LAGOS", lga="IKEJA",
                         ward="WARD3", property_type="XYZ")


@pytest.mark.asyncio
async def test_normalization_collapses_to_canonical_key(allocator) -> None:
    a, db = allocator
    pn1 = await a.allocate(country="NG", state="lagos", lga="Ikeja",
                           ward="ward 3", property_type="res")
    pn2 = await a.allocate(country="NG", state="LAGOS", lga="IKEJA",
                           ward="WARD3", property_type="RES")
    # Same canonical key → same counter document → consecutive numbers.
    assert pn1.split("-")[-1] != pn2.split("-")[-1]
    docs = await db[COUNTER_COLLECTION].find({}).to_list(length=10)
    # exactly one counter exists
    assert len(docs) == 1
    assert docs[0]["counter"] == 2
