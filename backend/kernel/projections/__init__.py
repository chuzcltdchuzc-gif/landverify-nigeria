"""Kernel projection engine (Phase 3.8).

Deterministic, replayable, disposable read models.

Constitutional rules (ADR-0010):
* Projections contain ZERO business logic — only event-to-row mapping.
* Projections NEVER mutate aggregates.
* Projections NEVER publish commands.
* Projections NEVER become authoritative — the outbox event stream IS
  the source of truth.
* Deleting a projection's data and replaying from event 0 MUST produce
  byte-identical state.

The engine itself owns: cursor tracking (last delivered ``event_id`` per
projection), health/lag metrics, snapshot timestamps, version tagging,
and the replay command.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase

from kernel.events.envelope import Envelope

logger = logging.getLogger("kernel.projections")

PROJECTION_CURSORS_COLLECTION = "kernel_projection_cursors"


class Projection(Protocol):
    """A projection implements ``on_event`` (idempotent) and exposes
    ``name``, ``version``, ``event_glob`` for engine routing."""

    name: str
    version: int
    event_glob: str  # outbox subscribe pattern, e.g. "evidence.*"

    async def on_event(self, env: Envelope) -> None: ...

    async def reset(self) -> None: ...


@dataclass
class ProjectionStatus:
    name: str
    version: int
    cursor_event_id: Optional[str]
    last_delivered_at: Optional[str]
    last_event_type: Optional[str]
    delivered_count: int
    lag_events: int
    rebuilding: bool
    last_snapshot_at: Optional[str]


@dataclass
class ProjectionEngine:
    """Owns cursors, replay, lag metrics. The actual delivery still
    happens via the existing outbox subscriber mechanism — this engine
    wraps each registered Projection in a cursor-tracking handler."""

    db: AsyncIOMotorDatabase
    registry: dict[str, Projection] = field(default_factory=dict)
    delivered_counts: dict[str, int] = field(default_factory=dict)

    async def ensure_indexes(self) -> None:
        await self.db[PROJECTION_CURSORS_COLLECTION].create_index(
            "name", unique=True)

    def register(self, projection: Projection) -> Callable[[Envelope], Awaitable[None]]:
        """Return a cursor-tracking wrapper around the projection's
        ``on_event`` so subscriber registrations stay one-liners.

        Enforces the ADR-0010 purity invariant before the projection is
        accepted into the engine."""
        assert_projection_purity(projection)
        self.registry[projection.name] = projection

        async def handler(env: Envelope) -> None:
            try:
                await projection.on_event(env)
            except Exception:  # noqa: BLE001
                logger.exception("projection %s failed on event %s",
                                  projection.name, env.event_id)
                return
            await self.db[PROJECTION_CURSORS_COLLECTION].update_one(
                {"name": projection.name},
                {"$set": {
                    "name": projection.name,
                    "version": projection.version,
                    "cursor_event_id": env.event_id,
                    "last_delivered_at": datetime.now(timezone.utc).isoformat(),
                    "last_event_type": env.event_type,
                }, "$inc": {"delivered_count": 1}},
                upsert=True)
            self.delivered_counts[projection.name] = \
                self.delivered_counts.get(projection.name, 0) + 1

        return handler

    async def status(self, name: str) -> ProjectionStatus:
        if name not in self.registry:
            raise KeyError(f"projection {name!r} not registered")
        proj = self.registry[name]
        cur = await self.db[PROJECTION_CURSORS_COLLECTION].find_one(
            {"name": name}, {"_id": 0}) or {}
        # Lag = total outbox events matching glob - delivered count.
        from kernel.events.outbox import OUTBOX_COLLECTION
        total = await self.db[OUTBOX_COLLECTION].count_documents(
            self._glob_filter(proj.event_glob))
        delivered = cur.get("delivered_count", 0)
        return ProjectionStatus(
            name=name, version=proj.version,
            cursor_event_id=cur.get("cursor_event_id"),
            last_delivered_at=cur.get("last_delivered_at"),
            last_event_type=cur.get("last_event_type"),
            delivered_count=delivered,
            lag_events=max(0, total - delivered),
            rebuilding=bool(cur.get("rebuilding")),
            last_snapshot_at=cur.get("last_snapshot_at"))

    def _glob_filter(self, pattern: str) -> dict:
        if pattern == "*":
            return {}
        if pattern.endswith(".*"):
            prefix = pattern[:-2].replace(".", r"\.")
            return {"event_type": {"$regex": f"^{prefix}\\."}}
        return {"event_type": pattern}

    async def replay(self, name: str) -> ProjectionStatus:
        """Disposable rebuild: reset projection state + cursor, then
        replay every matching outbox event in occurred_at order. The
        constitutional determinism gate (ADR-0010).

        Walks the outbox over events with status ``DELIVERED`` — those
        are the events the publisher has confirmed and the projections
        have ever seen. Re-delivery during replay is safe because every
        projection is idempotent (adapter-level dedup on aggregate
        identity + seq)."""
        if name not in self.registry:
            raise KeyError(f"projection {name!r} not registered")
        proj = self.registry[name]
        await self.db[PROJECTION_CURSORS_COLLECTION].update_one(
            {"name": name},
            {"$set": {"name": name, "version": proj.version,
                       "rebuilding": True,
                       "rebuild_started_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True)
        # 1. Reset projection-owned state.
        await proj.reset()
        # 2. Reset cursor counts.
        await self.db[PROJECTION_CURSORS_COLLECTION].update_one(
            {"name": name},
            {"$set": {"cursor_event_id": None,
                       "delivered_count": 0,
                       "last_event_type": None,
                       "version": proj.version}})
        self.delivered_counts[name] = 0
        # 3. Walk the outbox in order.
        from kernel.events.outbox import OUTBOX_COLLECTION
        flt = self._glob_filter(proj.event_glob)
        flt["status"] = "DELIVERED"
        cur = self.db[OUTBOX_COLLECTION].find(flt, {"_id": 0}).sort(
            "occurred_at", 1)
        replayed = 0
        last_env: Optional[Envelope] = None
        async for doc in cur:
            env = Envelope(**{k: doc.get(k)
                              for k in Envelope.__dataclass_fields__})
            try:
                await proj.on_event(env)
                replayed += 1
                last_env = env
            except Exception:  # noqa: BLE001
                logger.exception("replay handler crashed on %s", env.event_id)
        await self.db[PROJECTION_CURSORS_COLLECTION].update_one(
            {"name": name},
            {"$set": {"rebuilding": False,
                       "delivered_count": replayed,
                       "last_event_type": last_env.event_type if last_env else None,
                       "cursor_event_id": last_env.event_id if last_env else None,
                       "last_delivered_at": datetime.now(timezone.utc).isoformat(),
                       "rebuild_completed_at": datetime.now(timezone.utc).isoformat()}})
        self.delivered_counts[name] = replayed
        return await self.status(name)

    async def snapshot(self, name: str) -> None:
        """Record a snapshot timestamp. Real durable snapshots are a
        projection-specific concern (each projection owns its rows);
        the engine just records that a snapshot was taken so the lag
        monitor can mark a baseline."""
        if name not in self.registry:
            raise KeyError(f"projection {name!r} not registered")
        proj = self.registry[name]
        await self.db[PROJECTION_CURSORS_COLLECTION].update_one(
            {"name": name},
            {"$set": {"name": name, "version": proj.version,
                       "last_snapshot_at":
                       datetime.now(timezone.utc).isoformat()}},
            upsert=True)

    async def health(self) -> list[ProjectionStatus]:
        return [await self.status(n) for n in sorted(self.registry)]


# ---- Module-level singleton --------------------------------------------

_engine: Optional[ProjectionEngine] = None


def configure_engine(db: AsyncIOMotorDatabase) -> ProjectionEngine:
    global _engine
    _engine = ProjectionEngine(db=db)
    return _engine


def current_engine() -> ProjectionEngine:
    if _engine is None:
        raise RuntimeError("projection engine not configured")
    return _engine


# ---- Projection Purity Invariant (ADR-0010 §1) -------------------------


class InvariantError(Exception):
    """Raised when a projection violates ADR-0010 constitutional rules."""


FORBIDDEN_IMPORT_NAMES = (
    # Publishing commands FROM a projection is a constitutional violation.
    "kernel.events.outbox.publish",
    # Aggregate mutation FROM a projection is a constitutional violation.
    ".save", ".release", ".archive", ".transfer", ".extend",
)


def assert_projection_purity(projection: Projection) -> None:
    """Static (best-effort) check that a Projection's on_event method
    body does not call any forbidden mutator. Runs once at engine
    registration and is also driven by
    ``tests/test_phase38_projections.py::test_projection_purity_invariant``.

    This is intentionally a coarse check — it inspects the class source
    for forbidden tokens. A determined author can work around it; the
    test suite + ADR-0010 are the binding governance. The point is to
    catch accidental drift early.
    """
    import inspect
    try:
        src = inspect.getsource(projection.__class__)
    except (OSError, TypeError):
        return  # dynamically-built test doubles skip the static check
    for token in (
        "kernel.events.outbox.publish",
        "await publish(",
        # Aggregate mutators that would break the read-only contract.
        ".save_seal(", ".save_item(", ".archive(",
    ):
        if token in src:
            raise InvariantError(
                f"projection {projection.name!r} violates ADR-0010 purity: "
                f"source code contains forbidden token {token!r}")
