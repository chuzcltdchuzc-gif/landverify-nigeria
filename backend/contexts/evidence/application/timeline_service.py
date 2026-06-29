"""Phase 3.7 application service — timeline/custody auto-projection +
LegalHold + supersession + access logging.

Subscribes to the outbox event stream and appends a timeline entry for
every Phase 3.4/3.5/3.6 evidence event. Custody entries are appended
when the operator explicitly records a transfer or when a signed-URL
issuance is logged.
"""
from __future__ import annotations

from typing import Optional

from contexts.evidence.adapters.mongo_timeline_repository import (
    MongoCustodyRepository,
    MongoLegalHoldRepository,
    MongoTimelineRepository,
)
from contexts.evidence.domain.invariants import (
    ImmutableFieldError,
    InvariantViolation,
    TransitionError,
)
from contexts.evidence.domain.timeline import (
    CustodyEntry,
    LegalHold,
    SupersessionLink,
    TimelineEntry,
    TimelineEventKind,
)
from kernel.audit import audit
from kernel.errors.problem import bad_request, conflict, not_found
from kernel.events.outbox import publish, subscribe
from kernel.persistence.context import current_context


# Map outbox event_type → timeline kind + summary template.
_EVENT_TO_TIMELINE: dict[str, tuple[str, str]] = {
    "evidence.item.uploaded": (TimelineEventKind.UPLOAD.value, "Evidence uploaded"),
    "evidence.item.hash_verified": (TimelineEventKind.VERIFICATION.value, "Hash verified"),
    "evidence.item.hash_mismatch": (TimelineEventKind.VERIFICATION.value, "Hash mismatch detected"),
    "evidence.item.archived_replaced": (TimelineEventKind.SUPERSESSION.value, "Evidence superseded"),
    "evidence.seal.created": (TimelineEventKind.SEAL.value, "Sealed"),
    "evidence.seal.worm_applied": (TimelineEventKind.LOCK.value, "WORM applied"),
    "evidence.lock.applied": (TimelineEventKind.LOCK.value, "Lock recorded"),
    "evidence.lock.extended": (TimelineEventKind.LOCK_EXTENDED.value, "Retention extended"),
    "evidence.integrity.passed": (TimelineEventKind.INTEGRITY.value, "Integrity check passed"),
    "evidence.integrity.failed": (TimelineEventKind.INTEGRITY.value, "Integrity check FAILED"),
    "evidence.anchor.confirmed": (TimelineEventKind.ANCHOR.value, "Anchored"),
    "evidence.anchor.failed": (TimelineEventKind.ANCHOR.value, "Anchor failed"),
    "evidence.signed_url.issued": (TimelineEventKind.ACCESS_GRANTED.value, "Signed URL issued"),
    "evidence.legal_hold.applied": (TimelineEventKind.LEGAL_HOLD_APPLIED.value, "Legal hold applied"),
    "evidence.legal_hold.released": (TimelineEventKind.LEGAL_HOLD_RELEASED.value, "Legal hold released"),
}


class TimelineProjector:
    """Outbox subscriber that materialises an immutable evidence timeline."""

    def __init__(self, db, timeline_repo: MongoTimelineRepository,
                 custody_repo: MongoCustodyRepository) -> None:
        self._db = db
        self._timeline = timeline_repo
        self._custody = custody_repo

    async def on_event(self, env) -> None:
        if env.event_type not in _EVENT_TO_TIMELINE:
            return
        payload = env.payload or {}
        # Resolve targeted evidence_ids — support both single and fan-out
        # (seal events carry `evidence_ids: list[str]`).
        evidence_ids: list[str] = []
        if isinstance(payload.get("evidence_ids"), list):
            evidence_ids = list(payload["evidence_ids"])
        elif payload.get("evidence_id"):
            evidence_ids = [payload["evidence_id"]]
        elif env.aggregate_type == "EvidenceItem":
            evidence_ids = [env.aggregate_id]
        if not evidence_ids:
            return
        tenant_id = env.tenant_id or "default"
        country = env.country or "NG"
        kind, summary = _EVENT_TO_TIMELINE[env.event_type]
        for evidence_id in evidence_ids:
            try:
                head = await self._timeline.head(evidence_id)
                seq = (head.seq + 1) if head else 0
                prev_hash = head.entry_hash if head else None
                entry = TimelineEntry.create(
                    evidence_id=evidence_id, tenant_id=tenant_id,
                    country_code=country, kind=kind,
                    actor=env.actor or "system",
                    seq=seq, prev_hash=prev_hash, summary=summary,
                    payload={"event_id": env.event_id,
                              "event_type": env.event_type,
                              "ref": payload})
                await self._timeline.append(entry)
            except InvariantViolation:
                continue
        # When a signed URL is issued we additionally record an
        # `accessed` custody entry to maintain the chain-of-custody.
        if env.event_type == "evidence.signed_url.issued":
            evidence_id = evidence_ids[0]
            try:
                chead = await self._custody.head(evidence_id)
                seq = (chead.seq + 1) if chead else 0
                prev_hash = chead.entry_hash if chead else None
                cust = CustodyEntry.create(
                    evidence_id=evidence_id, tenant_id=tenant_id,
                    country_code=country,
                    actor=payload.get("principal_id") or env.actor or "system",
                    role="signed_url_consumer",
                    action="accessed",
                    justification=f"signed-url action={payload.get('action', 'read')} "
                                   f"ttl={payload.get('ttl_seconds')}",
                    seq=seq, prev_hash=prev_hash,
                    previous_custody_id=(chead.custody_id if chead else None))
                await self._custody.append(cust)
            except InvariantViolation:
                return


class CustodyService:
    def __init__(self, db, custody_repo: MongoCustodyRepository) -> None:
        self._db = db
        self._custody = custody_repo

    async def record_transfer(self, *, evidence_id: str, role: str,
                                action: str, justification: str,
                                signature_kid: Optional[str] = None,
                                signature: Optional[str] = None) -> dict:
        ctx = current_context()
        head = await self._custody.head(evidence_id)
        seq = (head.seq + 1) if head else 0
        prev_hash = head.entry_hash if head else None
        try:
            entry = CustodyEntry.create(
                evidence_id=evidence_id, tenant_id=ctx.tenant_id or "default",
                country_code=ctx.country or "NG",
                actor=ctx.principal_id, role=role, action=action,
                justification=justification, seq=seq, prev_hash=prev_hash,
                previous_custody_id=(head.custody_id if head else None),
                signature_kid=signature_kid, signature=signature)
        except InvariantViolation as exc:
            raise bad_request(str(exc), code="evidence.custody.invalid")
        await self._custody.append(entry)
        from kernel.events.envelope import new_envelope
        env = new_envelope(
            event_type="evidence.custody.appended", event_version=1,
            aggregate_type="CustodyEntry", aggregate_id=entry.custody_id,
            aggregate_version=seq + 1,
            payload={"custody_id": entry.custody_id,
                     "evidence_id": evidence_id, "action": action,
                     "role": role},
            producer="evidence", tenant_id=entry.tenant_id,
            country=entry.country_code, actor=ctx.principal_id)
        await publish(env)
        await audit(action="evidence.custody.appended",
                     resource_type="custody_entry",
                     resource_id=entry.custody_id, decision="EXECUTED",
                     payload={"evidence_id": evidence_id})
        return entry.to_state()


class LegalHoldService:
    def __init__(self, db, holds_repo: MongoLegalHoldRepository) -> None:
        self._db = db
        self._holds = holds_repo

    async def apply(self, *, evidence_id: str, case_reference: str,
                      reason: str) -> dict:
        ctx = current_context()
        try:
            hold = LegalHold.create(
                evidence_id=evidence_id, tenant_id=ctx.tenant_id or "default",
                country_code=ctx.country or "NG",
                case_reference=case_reference, issued_by=ctx.principal_id,
                reason=reason)
        except InvariantViolation as exc:
            raise bad_request(str(exc), code="evidence.legal_hold.invalid")
        await self._holds.add(hold)
        for evt in hold.pull_events():
            env = evt.to_envelope(tenant_id=hold.tenant_id,
                                    country=hold.country_code,
                                    actor=ctx.principal_id)
            await publish(env)
            await audit(action=evt.event_type, resource_type="legal_hold",
                         resource_id=evt.aggregate_id, decision="EXECUTED",
                         payload={"evidence_id": evidence_id})
        return hold.to_state()

    async def release(self, *, hold_id: str,
                        release_reason: str) -> dict:
        ctx = current_context()
        hold = await self._holds.get(hold_id)
        if not hold:
            raise not_found(f"legal hold {hold_id} not found",
                              code="evidence.legal_hold.not_found")
        prev_v = hold.version
        try:
            hold.release(released_by=ctx.principal_id,
                           release_reason=release_reason)
        except (TransitionError, InvariantViolation) as exc:
            raise conflict(str(exc),
                             code="evidence.legal_hold.invalid_transition")
        updated = await self._holds.release(hold, expected_version=prev_v)
        for evt in hold.pull_events():
            env = evt.to_envelope(tenant_id=hold.tenant_id,
                                    country=hold.country_code,
                                    actor=ctx.principal_id)
            await publish(env)
            await audit(action=evt.event_type, resource_type="legal_hold",
                         resource_id=evt.aggregate_id, decision="EXECUTED",
                         payload={"hold_id": hold_id})
        return updated.to_state()


class SupersessionService:
    """Read-only supersession graph traversal over the EvidenceItem
    ``replaced_by`` chain (already persisted by Phase 3.3 remediation)."""

    def __init__(self, db, items_repo) -> None:
        self._db = db
        self._items = items_repo

    async def chain(self, evidence_id: str) -> list[SupersessionLink]:
        """Walk the supersession chain from ``evidence_id`` to the
        terminal (non-replaced) descendant."""
        seen: set[str] = set()
        links: list[SupersessionLink] = []
        current = evidence_id
        while current and current not in seen:
            seen.add(current)
            it = await self._items.get(current)
            if not it:
                break
            # Find the predecessor: scan for an item whose replaced_by
            # equals this id. (Cheap on the small in-tenant set.)
            predecessor = await self._db["evidence_items"].find_one(
                {"replaced_by": current}, {"_id": 0, "evidence_id": 1})
            links.append(SupersessionLink(
                evidence_id=it.evidence_id,
                previous_version_id=(predecessor["evidence_id"]
                                       if predecessor else None),
                superseded_by=it.replaced_by,
                superseded_at=it.replaced_at,
                superseded_reason=None))
            current = it.replaced_by
        return links
