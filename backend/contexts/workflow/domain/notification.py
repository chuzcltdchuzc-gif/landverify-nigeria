"""NotificationDelivery aggregate (Phase 4 — Slice 4.1).

Records ONE non-authoritative notification delivery attempt. Delivery
infrastructure ONLY: provider abstraction + retry + DLQ + delivery log
(ADR-0019). NO business notification templates or content live here —
those belong to future business slices.

Constitutional rules:
* Notifications NEVER block a workflow (ADR-0019). A delivery failure
  is logged and retried; the workflow lifecycle continues.
* Never authoritative: the workflow's authoritative record is the
  event stream, not the notification.
* No PII in delivery logs (payload is opaque; we log the address hash
  + provider status only).
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from contexts.workflow.domain.value_objects import now_iso


class DeliveryStatus(str, Enum):
    QUEUED = "queued"
    SENDING = "sending"
    DELIVERED = "delivered"
    RETRY = "retry"
    DEAD_LETTERED = "dead_lettered"


TERMINAL_DELIVERY_STATUSES = frozenset({
    DeliveryStatus.DELIVERED.value,
    DeliveryStatus.DEAD_LETTERED.value,
})


def new_delivery_id() -> str:
    return "wfnd_" + uuid.uuid4().hex


def _hash_address(addr: str) -> str:
    return "addr_" + hashlib.sha256(addr.encode("utf-8")).hexdigest()[:16]


@dataclass
class NotificationDelivery:
    """One non-authoritative notification delivery record."""

    delivery_id: str
    instance_id: Optional[str]      # None for standalone deliveries
    channel: str                    # "inbox" | "email" | "sms"
    address_hash: str               # never store the raw address
    provider: str                   # e.g. "log" | "smtp" | "twilio"
    subject_ref: str                # opaque reference (no PII)
    tenant_id: str
    country_code: str
    created_at: str
    status: str = DeliveryStatus.QUEUED.value
    attempts: int = 0
    max_attempts: int = 3
    last_error: Optional[str] = None
    delivered_at: Optional[str] = None
    dead_lettered_at: Optional[str] = None
    next_attempt_at: Optional[str] = None
    version: int = 1

    @classmethod
    def create(cls, *, channel: str, address: str, provider: str,
               subject_ref: str, tenant_id: str, country_code: str,
               instance_id: Optional[str] = None,
               max_attempts: int = 3,
               delivery_id: Optional[str] = None) -> "NotificationDelivery":
        return cls(
            delivery_id=delivery_id or new_delivery_id(),
            instance_id=instance_id, channel=channel,
            address_hash=_hash_address(address),
            provider=provider,
            subject_ref=subject_ref,
            tenant_id=tenant_id, country_code=country_code,
            created_at=now_iso(), max_attempts=max_attempts)

    @classmethod
    def from_state(cls, state: dict) -> "NotificationDelivery":
        clean = {k: v for k, v in state.items()
                 if k in cls.__dataclass_fields__ and not k.startswith("_")}
        return cls(**clean)

    def mark_sending(self) -> None:
        if self.status in TERMINAL_DELIVERY_STATUSES:
            return
        self.status = DeliveryStatus.SENDING.value
        self.version += 1

    def mark_delivered(self) -> None:
        self.status = DeliveryStatus.DELIVERED.value
        self.delivered_at = now_iso()
        self.attempts += 1
        self.last_error = None
        self.next_attempt_at = None
        self.version += 1

    def mark_failed(self, *, error: str,
                    next_attempt_at: Optional[str]) -> None:
        self.attempts += 1
        self.last_error = error
        if self.attempts >= self.max_attempts:
            self.status = DeliveryStatus.DEAD_LETTERED.value
            self.dead_lettered_at = now_iso()
            self.next_attempt_at = None
        else:
            self.status = DeliveryStatus.RETRY.value
            self.next_attempt_at = next_attempt_at
        self.version += 1

    def to_state(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__
                if not k.startswith("_")}
