"""Business + technical observability metrics (Section 2.6).

Phase 1 uses an in-process counter store backed by a Mongo collection so
metrics survive restarts and can be queried by the existing dashboards.
Phase 3+ will swap in Prometheus / OpenTelemetry exporters via an adapter
(the public API of this module will not change).

The metrics emitted automatically by the kernel (callers do NOT have to
instrument):

    login_success                login_failed
    account_lockout              authz_denial
    authz_permit                 delegation_granted
    delegation_revoked           suspension
    role_change                  audit_event_count
    policy_evaluation_time_ms    authz_cache_hits
    authz_cache_misses           active_sessions
    revoked_sessions             session_created
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger("kernel.metrics")

# Process-local counters (best-effort fast path)
_counters: dict[tuple[str, str], int] = defaultdict(int)
_timings: dict[str, list[float]] = defaultdict(list)
_lock = asyncio.Lock()
_db: AsyncIOMotorDatabase | None = None

COLLECTION = "kernel_metrics"


def configure_metrics(db: AsyncIOMotorDatabase) -> None:
    global _db
    _db = db


def _label_str(labels: Optional[dict]) -> str:
    if not labels:
        return ""
    return ",".join(f"{k}={v}" for k, v in sorted(labels.items()) if v is not None)


async def increment(metric: str, value: int = 1, labels: Optional[dict] = None) -> None:
    """Increment a business/technical counter. Fast in-process; flushed to Mongo lazily."""
    key = (metric, _label_str(labels))
    async with _lock:
        _counters[key] += value
    if _db is not None:
        try:
            await _db[COLLECTION].update_one(
                {"metric": metric, "labels": labels or {}},
                {"$inc": {"value": value}},
                upsert=True,
            )
        except Exception:  # noqa: BLE001
            logger.debug("metrics persistence failed", exc_info=True)


async def record_timing(metric: str, duration_ms: float,
                        labels: Optional[dict] = None) -> None:
    _timings[metric].append(duration_ms)
    if _db is not None:
        try:
            await _db[COLLECTION].update_one(
                {"metric": metric + "_total_ms", "labels": labels or {}},
                {"$inc": {"value": float(duration_ms), "count": 1}},
                upsert=True,
            )
        except Exception:  # noqa: BLE001
            logger.debug("metrics timing persistence failed", exc_info=True)


def snapshot() -> dict[str, Any]:
    return {
        "counters": {f"{m}[{lbl}]": v for (m, lbl), v in _counters.items()},
        "timings": {k: {"count": len(vs),
                       "avg_ms": (sum(vs) / len(vs)) if vs else 0.0}
                    for k, vs in _timings.items()},
    }
