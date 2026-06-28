"""Transactional Outbox + lightweight in-process publisher.

The Outbox collection (`kernel_outbox`) is the durable buffer. Producers
insert events INSIDE the same MongoDB transaction as their state change, so
no event is ever orphaned or duplicated relative to its aggregate.

A background task (`start_outbox_publisher`) polls the outbox, delivers each
event to in-process subscribers, then marks the event `DELIVERED`. Subscribers
are idempotent. For Phase 1 the broker is in-process (per Foundation Spec §6:
"start with the outbox + a broker abstraction so the concrete transport can
be swapped without touching producers or consumers"). Phase 3+ will swap in a
real broker (Kafka/Rabbit/SQS) without changing producers or this contract.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from kernel.events.envelope import Envelope

logger = logging.getLogger("kernel.events.outbox")

OUTBOX_COLLECTION = "kernel_outbox"

# ---- Canonical Phase 1 event types --------------------------------------
EVENT_TYPES = (
    "identity.user.registered",
    "identity.account.activated",
    "identity.account.suspended",
    "identity.password.changed",
    "identity.role.assigned",
    "identity.delegation.granted",
    "identity.delegation.revoked",
    "identity.service_account.created",
    "identity.service_account.revoked",
    "identity.session.revoked",
    "identity.login.success",
    "identity.login.failed",
)

# In-process subscriber registry — handler(envelope) -> awaitable
Handler = Callable[[Envelope], Awaitable[None]]
_subscribers: list[tuple[str, Handler]] = []


def subscribe(event_type_glob: str, handler: Handler) -> None:
    """Register a subscriber. `event_type_glob` may be '*' or 'identity.*'."""
    _subscribers.append((event_type_glob, handler))


def _matches(event_type: str, pattern: str) -> bool:
    if pattern == "*":
        return True
    if pattern.endswith(".*"):
        return event_type.startswith(pattern[:-1])
    return event_type == pattern


# ---- Outbox -------------------------------------------------------------
class Outbox:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self.collection = db[OUTBOX_COLLECTION]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("event_id", unique=True)
        await self.collection.create_index([("status", 1), ("occurred_at", 1)])

    async def publish(self, envelope: Envelope, session=None) -> None:
        doc = envelope.to_doc()
        doc["status"] = "PENDING"
        doc["attempts"] = 0
        await self.collection.insert_one(dict(doc), session=session)

    async def _claim_batch(self, batch_size: int) -> list[dict]:
        """Atomically claim a batch of pending events."""
        claimed: list[dict] = []
        for _ in range(batch_size):
            doc = await self.collection.find_one_and_update(
                {"status": "PENDING"},
                {"$set": {"status": "PROCESSING"}, "$inc": {"attempts": 1}},
                sort=[("occurred_at", 1)],
                projection={"_id": 0},
                return_document=True,
            )
            if not doc:
                break
            claimed.append(doc)
        return claimed

    async def _deliver(self, doc: dict) -> None:
        env = Envelope(**{k: doc.get(k) for k in Envelope.__dataclass_fields__})
        for pattern, handler in _subscribers:
            if _matches(env.event_type, pattern):
                try:
                    await handler(env)
                except Exception:  # noqa: BLE001
                    logger.exception("subscriber failed for event_id=%s pattern=%s",
                                     env.event_id, pattern)
        await self.collection.update_one(
            {"event_id": env.event_id},
            {"$set": {"status": "DELIVERED"}},
        )


# ---- Module-level publisher --------------------------------------------
_outbox: Outbox | None = None
_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None
POLL_INTERVAL_SECONDS = 1.0
BATCH_SIZE = 25


def configure_outbox(db: AsyncIOMotorDatabase) -> Outbox:
    global _outbox
    _outbox = Outbox(db)
    return _outbox


async def publish(envelope: Envelope, session=None) -> None:
    if _outbox is None:
        logger.warning("outbox not configured; dropping event %s", envelope.event_type)
        return
    await _outbox.publish(envelope, session=session)


async def _publisher_loop(stop: asyncio.Event) -> None:
    assert _outbox is not None
    logger.info("Outbox publisher started (poll=%ss batch=%d)",
                POLL_INTERVAL_SECONDS, BATCH_SIZE)
    while not stop.is_set():
        try:
            batch = await _outbox._claim_batch(BATCH_SIZE)
            for doc in batch:
                await _outbox._deliver(doc)
        except Exception:  # noqa: BLE001
            logger.exception("outbox publisher iteration crashed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=POLL_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
    logger.info("Outbox publisher stopped.")


async def start_outbox_publisher() -> None:
    global _task, _stop_event
    if _outbox is None:
        raise RuntimeError("configure_outbox() must be called first")
    if _task and not _task.done():
        return
    await _outbox.ensure_indexes()
    _stop_event = asyncio.Event()
    _task = asyncio.create_task(_publisher_loop(_stop_event))


async def stop_outbox_publisher() -> None:
    global _task, _stop_event
    if _stop_event:
        _stop_event.set()
    if _task:
        try:
            await asyncio.wait_for(_task, timeout=5)
        except asyncio.TimeoutError:
            _task.cancel()
    _task = None
    _stop_event = None
