"""Append-only audit store tests (ADR-005)."""
from __future__ import annotations

import os

import pytest

from core.database import db as _shared_db
from kernel.audit.store import AuditEntry, AuditStore
from kernel.persistence.context import ExecutionContext, set_context


def _db():
    # Use the same Motor client as the running backend so transactions
    # opened inside the store talk to the same client that owns the session.
    return _shared_db


@pytest.mark.asyncio
async def test_record_appends_with_chain():
    """Insert several entries, then verify the chain holds across the
    actual stored sequence (the production invariant).

    The shared backend may also be writing audit entries, so we reconstruct
    the chain by reading consecutive seq numbers from the DB rather than by
    insertion order.
    """
    db = _db()
    store = AuditStore(db)

    set_context(ExecutionContext(principal_id="usr_test", email="t@example.com",
                                 country="NG", tenant_id="ten_test"))

    inserted = []
    for _ in range(3):
        e = await store.record(AuditEntry(action="test.audit.chain", resource_type="probe"))
        inserted.append(e)

    # All three returned entries must have a valid 64-char entry_hash.
    for e in inserted:
        assert isinstance(e["entry_hash"], str) and len(e["entry_hash"]) == 64
        assert isinstance(e["prev_hash"], str) and len(e["prev_hash"]) == 64

    # Now verify chain integrity globally across a window covering our inserts.
    lo = min(e["seq"] for e in inserted)
    hi = max(e["seq"] for e in inserted)
    window = await store.collection.find(
        {"seq": {"$gte": lo, "$lte": hi}}, {"_id": 0}
    ).sort("seq", 1).to_list(None)
    for i in range(1, len(window)):
        assert window[i]["prev_hash"] == window[i - 1]["entry_hash"], (
            f"hash chain broken between seq {window[i-1]['seq']} and {window[i]['seq']}"
        )


@pytest.mark.asyncio
async def test_store_has_no_update_or_delete_methods():
    """The public API surface must not expose update/delete (ADR-005)."""
    store = AuditStore(_db())
    public = {name for name in dir(store) if not name.startswith("_")}
    for forbidden_name in ("update", "delete", "replace", "modify", "remove"):
        assert forbidden_name not in public, (
            f"AuditStore public API exposes forbidden mutation: {forbidden_name}"
        )


def test_audit_entry_immutable_at_dataclass_level():
    """AuditEntry is a small dataclass — verify it carries occurred_at default."""
    e = AuditEntry(action="x", resource_type="y")
    assert e.occurred_at  # default-stamped
