"""Multi-document MongoDB transactions with graceful standalone fallback +
automatic retry on TransientTransactionError.

Usage::

    async with atomic_transaction() as session:
        await db.col_a.update_one(..., session=session)
        await db.col_b.insert_one(..., session=session)

If the connected MongoDB is a replica set / mongos, a real transaction is
opened via `client.start_session() + start_transaction()`. The caller MUST
pass the yielded `session` to every Mongo op inside the block.

On `WriteConflict` / `TransientTransactionError`, the transaction is aborted
and replayed up to `MAX_TX_RETRIES` times with a short jittered back-off. The
client code is therefore expected to be **idempotent re-runnable** inside the
block (no external side effects). All Mongo ops naturally satisfy that.

If the deployment is a standalone mongod (no transactions), the context yields
`None`. Single-doc atomic ops + idempotency keys provide double-spend safety.
"""
from __future__ import annotations

import asyncio
import logging
import random
from contextlib import asynccontextmanager
from typing import Optional

from pymongo.errors import OperationFailure, PyMongoError

from core.database import client

logger = logging.getLogger("landvault.tx")

MAX_TX_RETRIES = 5
_replica_set_supported: Optional[bool] = None


async def _detect_replica_set() -> bool:
    global _replica_set_supported
    if _replica_set_supported is not None:
        return _replica_set_supported
    try:
        hello = await client.admin.command("hello")
        ok = bool(hello.get("setName")) or hello.get("msg") == "isdbgrid"
    except Exception as exc:
        logger.warning("hello probe failed: %s", exc)
        ok = False
    _replica_set_supported = ok
    if ok:
        logger.info("MongoDB transactions ENABLED")
    else:
        logger.warning("MongoDB transactions DISABLED (standalone mongod).")
    return ok


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, OperationFailure):
        labels = exc.details.get("errorLabels") if exc.details else None
        if labels and "TransientTransactionError" in labels:
            return True
    if isinstance(exc, PyMongoError):
        if "TransientTransactionError" in (str(exc) or ""):
            return True
    return False


class _NoTxContext:
    """When MongoDB is standalone, atomic_transaction yields a no-op context that
    looks like a session: any call with `session=None` is accepted by Motor."""
    def __init__(self) -> None:
        pass


@asynccontextmanager
async def atomic_transaction():
    """Yields a Mongo session bound to a transaction, or None if unsupported.

    Note: For automatic retry on TransientTransactionError, prefer
    `run_in_transaction(coro_factory)` below. This bare context manager does
    not retry — it propagates the error.
    """
    if await _detect_replica_set():
        async with await client.start_session() as session:
            async with session.start_transaction():
                yield session
    else:
        yield None


async def run_in_transaction(coro_factory, max_retries: int = MAX_TX_RETRIES):
    """Run `await coro_factory(session)` inside a transaction with retries.

    `coro_factory` must be a callable that accepts the session and returns a
    fresh coroutine each time (so it can be re-run on retry). Returns the
    value returned by the coroutine.
    """
    if not await _detect_replica_set():
        # Standalone mode: single attempt, session=None.
        return await coro_factory(None)

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            async with await client.start_session() as session:
                async with session.start_transaction():
                    result = await coro_factory(session)
                    return result
        except Exception as exc:  # noqa: BLE001
            if _is_transient(exc) and attempt + 1 < max_retries:
                backoff = (0.02 * (2 ** attempt)) + random.random() * 0.02
                logger.info("transient TX error, retry %d/%d in %.3fs",
                            attempt + 1, max_retries, backoff)
                await asyncio.sleep(backoff)
                last_exc = exc
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("run_in_transaction exhausted retries with no exception")


def is_transactional() -> bool:
    return bool(_replica_set_supported)
