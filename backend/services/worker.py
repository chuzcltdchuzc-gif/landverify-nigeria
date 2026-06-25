"""Async background worker for the job queue.

Runs alongside the FastAPI app as a long-lived asyncio task. Pulls PENDING
jobs in small batches, executes them via `services.jobs._execute_job`, and
applies exponential-backoff retries with a dead-letter terminal state.

Compared to the old admin-triggered `process_job_queue_internal()` (which is
kept for manual / on-demand processing), this worker:

* Polls automatically every `WORKER_POLL_INTERVAL` seconds
* Retries failed jobs up to `max_attempts` with exponential backoff
* Marks jobs `DEAD_LETTER` after the final attempt instead of leaving them
  silently FAILED, so the admin dashboard can surface them
* Tracks live status (`STARTED`/`RETRY_SCHEDULED`/`DEAD_LETTER`) for observability
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import timedelta

from core.database import db
from core.helpers import isoformat, now_utc
from services.jobs import _execute_job

logger = logging.getLogger("landvault.worker")

WORKER_POLL_INTERVAL = int(os.environ.get("WORKER_POLL_INTERVAL", "5"))
WORKER_BATCH_SIZE = int(os.environ.get("WORKER_BATCH_SIZE", "5"))
WORKER_BACKOFF_BASE = int(os.environ.get("WORKER_BACKOFF_BASE", "10"))  # seconds

_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


async def _claim_one_job() -> dict | None:
    """Atomically transition a PENDING (or RETRY-due) job to PROCESSING.

    Uses `find_one_and_update` so two worker instances never claim the same
    document. Returns the updated job dict or None when nothing was claimable.
    """
    now_iso = isoformat(now_utc())
    return await db.job_queue.find_one_and_update(
        {
            "status": {"$in": ["PENDING", "RETRY_SCHEDULED"]},
            "$or": [
                {"next_attempt_at": {"$lte": now_iso}},
                {"next_attempt_at": {"$exists": False}},
                {"next_attempt_at": None},
            ],
        },
        {"$set": {"status": "PROCESSING", "started_at": now_iso}, "$inc": {"attempts": 1}},
        sort=[("scheduled_at", 1)],
        return_document=True,
        projection={"_id": 0},
    )


async def _complete(job: dict, result: dict) -> None:
    await db.job_queue.update_one(
        {"id": job["id"]},
        {"$set": {
            "status": "COMPLETED",
            "result": result,
            "completed_at": isoformat(now_utc()),
            "error_message": None,
        }},
    )


async def _fail_or_retry(job: dict, exc: Exception) -> None:
    attempts = int(job.get("attempts", 0))
    max_attempts = int(job.get("max_attempts", 3))
    err = f"{type(exc).__name__}: {exc}"[:500]
    if attempts >= max_attempts:
        await db.job_queue.update_one(
            {"id": job["id"]},
            {"$set": {
                "status": "DEAD_LETTER",
                "error_message": err,
                "completed_at": isoformat(now_utc()),
            }},
        )
        logger.error("job %s sent to DEAD_LETTER after %d attempts: %s",
                     job["id"], attempts, err)
    else:
        delay = WORKER_BACKOFF_BASE * (2 ** (attempts - 1))
        next_at = isoformat(now_utc() + timedelta(seconds=delay))
        await db.job_queue.update_one(
            {"id": job["id"]},
            {"$set": {
                "status": "RETRY_SCHEDULED",
                "error_message": err,
                "next_attempt_at": next_at,
            }},
        )
        logger.warning("job %s scheduled for retry in %ds (attempt %d/%d): %s",
                       job["id"], delay, attempts, max_attempts, err)


async def _worker_loop(stop: asyncio.Event) -> None:
    logger.info("Background worker started (poll=%ss, batch=%s, backoff_base=%ss)",
                WORKER_POLL_INTERVAL, WORKER_BATCH_SIZE, WORKER_BACKOFF_BASE)
    while not stop.is_set():
        processed = 0
        try:
            for _ in range(WORKER_BATCH_SIZE):
                job = await _claim_one_job()
                if not job:
                    break
                try:
                    result = await _execute_job(job)
                    await _complete(job, result or {"ok": True})
                except Exception as exc:  # noqa: BLE001
                    logger.exception("job %s raised", job.get("id"))
                    await _fail_or_retry(job, exc)
                processed += 1
        except Exception:  # noqa: BLE001
            logger.exception("worker loop iteration crashed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=WORKER_POLL_INTERVAL)
        except asyncio.TimeoutError:
            pass
    logger.info("Background worker stopped.")


async def start_worker() -> None:
    """Launch the worker task. Idempotent."""
    global _task, _stop_event
    if _task and not _task.done():
        return
    _stop_event = asyncio.Event()
    _task = asyncio.create_task(_worker_loop(_stop_event))


async def stop_worker() -> None:
    global _task, _stop_event
    if _stop_event:
        _stop_event.set()
    if _task:
        try:
            await asyncio.wait_for(_task, timeout=10)
        except asyncio.TimeoutError:
            _task.cancel()
    _task = None
    _stop_event = None
