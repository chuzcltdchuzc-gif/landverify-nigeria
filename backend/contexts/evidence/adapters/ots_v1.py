"""OpenTimestamps AnchorPort adapter — Phase 3.6 secondary.

Per ADR-0008 §15 Decision 2: calendar list + 2-of-N quorum, and
**failure of one calendar does NOT fail the saga**.

This adapter does NOT perform real network calls in the default build
— OTS network tests are skipped unless ``OTS_NETWORK_TESTS=1`` is set.
A pluggable HTTP fetcher allows tests to inject deterministic calendar
responses without hitting the public OpenTimestamps infrastructure.

The adapter persists per-calendar state in Mongo (collection
``evidence_ots_attempts``) so that progress survives worker restarts
and an in-flight quorum reaches confirmation across multiple polls.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from contexts.evidence.domain.value_objects import now_iso
from contexts.evidence.ports.anchor import (
    AnchorPollResult,
    AnchorRequest,
    AnchorState,
    InclusionProof,
)

PROVIDER_ID = "ots_v1"
OTS_ATTEMPTS_COLLECTION = "evidence_ots_attempts"

DEFAULT_CALENDARS = (
    "btc.calendar.opentimestamps.org",
    "alice.btc.calendar.opentimestamps.org",
    "finney.calendar.eternitywall.com",
)


@dataclass(frozen=True)
class OtsCalendarOutcome:
    """Single calendar submit or poll outcome."""
    calendar: str
    state: str  # 'submitted' | 'upgraded' | 'failed' | 'pending'
    proof_b64: Optional[str] = None
    detail: Optional[str] = None


@dataclass
class OtsFetcher:
    """Pluggable HTTP fetcher. Defaults to a stub that records the
    attempt without making real calls — adequate for unit tests AND
    for an air-gapped dev environment."""
    submit: Callable[[str, bytes], Awaitable[OtsCalendarOutcome]] = field(default=None)  # type: ignore[assignment]
    poll: Callable[[str, str, bytes], Awaitable[OtsCalendarOutcome]] = field(default=None)  # type: ignore[assignment]


async def _stub_submit(calendar: str, root: bytes) -> OtsCalendarOutcome:
    # Deterministic dev stub — returns 'submitted' with no proof.
    return OtsCalendarOutcome(calendar=calendar, state="submitted",
                              detail="dev-stub: no real network call")


async def _stub_poll(calendar: str, opaque_id: str,
                    root: bytes) -> OtsCalendarOutcome:
    # Deterministic dev stub — 'upgraded' after at most one poll.
    proof_bytes = hashlib.sha256(opaque_id.encode() + root).digest()
    return OtsCalendarOutcome(calendar=calendar, state="upgraded",
                              proof_b64=proof_bytes.hex(),
                              detail="dev-stub: synthetic proof")


class OtsV1Adapter:
    """OpenTimestamps AnchorPort adapter."""

    provider_id = PROVIDER_ID

    def __init__(self, db: AsyncIOMotorDatabase,
                 *, calendars: Optional[tuple[str, ...]] = None,
                 quorum: Optional[int] = None,
                 fetcher: Optional[OtsFetcher] = None) -> None:
        self._db = db
        self.attempts = db[OTS_ATTEMPTS_COLLECTION]
        # Env > ctor > defaults
        env_cals = os.environ.get("EVIDENCE_OTS_CALENDARS")
        self.calendars = (tuple(c.strip() for c in env_cals.split(",") if c.strip())
                            if env_cals else (calendars or DEFAULT_CALENDARS))
        env_q = os.environ.get("EVIDENCE_OTS_CALENDAR_QUORUM")
        self.quorum = int(env_q) if env_q else (quorum or 2)
        self.quorum = max(1, min(self.quorum, len(self.calendars)))
        self.fetcher = fetcher or OtsFetcher(submit=_stub_submit, poll=_stub_poll)

    async def ensure_indexes(self) -> None:
        await self.attempts.create_index(
            [("batch_id", 1), ("calendar", 1)], unique=True)

    async def request_anchor(self, *, batch_id: str,
                              root: str) -> AnchorRequest:
        """Submit the root to every configured calendar. A
        single-calendar failure is recorded but never raises — only an
        all-calendars-failed scenario surfaces as a transient failure to
        the saga."""
        opaque_id = secrets.token_hex(16)
        root_bytes = bytes.fromhex(root)
        successes = 0
        per_calendar: dict[str, dict] = {}
        for cal in self.calendars:
            try:
                outcome = await self.fetcher.submit(cal, root_bytes)
                per_calendar[cal] = {"state": outcome.state,
                                       "detail": outcome.detail,
                                       "proof_b64": outcome.proof_b64}
                if outcome.state in ("submitted", "upgraded"):
                    successes += 1
            except Exception as exc:  # noqa: BLE001
                per_calendar[cal] = {"state": "failed", "detail": str(exc)}
        await self.attempts.update_one(
            {"batch_id": batch_id, "calendar": "__meta__"},
            {"$set": {"opaque_id": opaque_id, "root": root,
                       "submitted_at": now_iso(),
                       "calendars": per_calendar,
                       "successes_at_submit": successes}},
            upsert=True)
        if successes == 0:
            raise RuntimeError(
                f"ots: all {len(self.calendars)} calendars failed submit")
        return AnchorRequest(provider_id=self.provider_id, batch_id=batch_id,
                              root=root, provider_request_id=opaque_id,
                              submitted_at=now_iso(),
                              extra={"calendars": self.calendars,
                                      "quorum": self.quorum,
                                      "submit_successes": successes})

    async def poll_confirmation(self,
                                  request: AnchorRequest) -> AnchorPollResult:
        meta = await self.attempts.find_one(
            {"batch_id": request.batch_id, "calendar": "__meta__"},
            {"_id": 0})
        if not meta:
            return AnchorPollResult(state=AnchorState.FAILED_TRANSIENT.value,
                                      detail="no submit metadata; re-submit")
        opaque_id = meta["opaque_id"]
        root_bytes = bytes.fromhex(meta["root"])
        per_calendar = dict(meta.get("calendars", {}))
        upgraded = 0
        proofs: dict[str, str] = {}
        for cal in self.calendars:
            cur = per_calendar.get(cal, {})
            if cur.get("state") == "upgraded":
                upgraded += 1
                if cur.get("proof_b64"):
                    proofs[cal] = cur["proof_b64"]
                continue
            try:
                outcome = await self.fetcher.poll(cal, opaque_id, root_bytes)
                per_calendar[cal] = {"state": outcome.state,
                                       "detail": outcome.detail,
                                       "proof_b64": outcome.proof_b64}
                if outcome.state == "upgraded":
                    upgraded += 1
                    if outcome.proof_b64:
                        proofs[cal] = outcome.proof_b64
            except Exception as exc:  # noqa: BLE001
                per_calendar[cal] = {"state": "failed", "detail": str(exc)}
        await self.attempts.update_one(
            {"batch_id": request.batch_id, "calendar": "__meta__"},
            {"$set": {"calendars": per_calendar,
                       "last_polled_at": now_iso(),
                       "upgrades": upgraded}})
        if upgraded >= self.quorum:
            return AnchorPollResult(
                state=AnchorState.CONFIRMED.value,
                provider_response={"quorum": self.quorum,
                                     "upgrades": upgraded,
                                     "proofs": proofs,
                                     "calendars": list(self.calendars)})
        # Single-calendar failure does NOT fail the saga.
        return AnchorPollResult(
            state=AnchorState.PENDING.value,
            detail=f"upgrades={upgraded}/{self.quorum} quorum-needed")

    async def fetch_inclusion_proof(self, request: AnchorRequest,
                                      leaf_hash: str) -> InclusionProof:
        meta = await self.attempts.find_one(
            {"batch_id": request.batch_id, "calendar": "__meta__"},
            {"_id": 0})
        if not meta:
            raise RuntimeError(
                f"ots: no submit metadata for batch {request.batch_id}")
        per_calendar = meta.get("calendars", {})
        proofs = {cal: data.get("proof_b64") for cal, data in per_calendar.items()
                   if data.get("proof_b64")}
        return InclusionProof(
            provider_id=self.provider_id, seal_id=request.batch_id,
            leaf_hash=leaf_hash,
            proof_blob={
                "opaque_id": meta["opaque_id"],
                "calendars": list(self.calendars),
                "quorum": self.quorum,
                "proofs": proofs,
            })


__all__ = ["OtsV1Adapter", "OtsFetcher", "OtsCalendarOutcome",
            "DEFAULT_CALENDARS", "PROVIDER_ID"]
