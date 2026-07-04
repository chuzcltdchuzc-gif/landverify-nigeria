"""Notification DELIVERY infrastructure (Phase 4 — Slice 4.1).

Provides:
* A pluggable ``NotificationProvider`` port with three default adapters:
  ``LogProvider`` (writes to the delivery log), ``EmailStubProvider``
  (no-op success), ``SmsStubProvider`` (no-op success). Real provider
  adapters (SMTP / Twilio / etc.) live in later business slices.
* A ``NotificationDispatcher`` that enqueues + delivers notifications
  with retry + DLQ.

Constitutional rules (ADR-0019):
* NEVER authoritative — a delivery failure does NOT block a workflow.
* NEVER contains business notification templates or content — this
  module carries provider abstraction, retry, DLQ, delivery log only.
* NO PII in delivery logs — addresses are hashed at enqueue time
  (see NotificationDelivery.create).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

from contexts.workflow.adapters.slice41_repositories import (
    MongoNotificationLog,
)
from contexts.workflow.domain.notification import (
    DeliveryStatus,
    NotificationDelivery,
)
from kernel.audit import audit
from kernel.observability.metrics import increment

logger = logging.getLogger("contexts.workflow.notification_dispatcher")


class NotificationProvider:
    """Minimal port. Real adapters (SMTP, Twilio) come from later slices."""

    channel: str = "none"
    provider_id: str = "none"

    async def send(self, *, address: str, subject_ref: str,
                   payload: dict) -> None:
        raise NotImplementedError


class LogProvider(NotificationProvider):
    """Records the delivery to structured logs. Always succeeds."""
    channel = "inbox"
    provider_id = "log"

    async def send(self, *, address: str, subject_ref: str,
                   payload: dict) -> None:
        logger.info("[notify.log] subject=%s addr_hash_only=%d bytes",
                    subject_ref, len(address))
        return None


class EmailStubProvider(NotificationProvider):
    """No-op email provider — reports success, records nothing external.

    Real SMTP integration is deferred to a later slice (business content
    responsibility).
    """
    channel = "email"
    provider_id = "email_stub"

    async def send(self, *, address: str, subject_ref: str,
                   payload: dict) -> None:
        return None


class SmsStubProvider(NotificationProvider):
    channel = "sms"
    provider_id = "sms_stub"

    async def send(self, *, address: str, subject_ref: str,
                   payload: dict) -> None:
        return None


class FailingStubProvider(NotificationProvider):
    """Test-only provider that always fails — proves retry + DLQ path."""
    channel = "inbox"
    provider_id = "fail_stub"

    async def send(self, *, address: str, subject_ref: str,
                   payload: dict) -> None:
        raise RuntimeError("FailingStubProvider: forced failure")


class NotificationDispatcher:

    def __init__(self, *, log: MongoNotificationLog,
                 clock: Optional[Callable[[], datetime]] = None) -> None:
        self._log = log
        self._providers: dict[tuple[str, str], NotificationProvider] = {}
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def register_provider(self, provider: NotificationProvider) -> None:
        key = (provider.channel, provider.provider_id)
        self._providers[key] = provider

    def get_provider(self, channel: str,
                     provider_id: str) -> Optional[NotificationProvider]:
        return self._providers.get((channel, provider_id))

    async def enqueue(self, *, channel: str, provider_id: str,
                       address: str, subject_ref: str, payload: dict,
                       tenant_id: str, country_code: str,
                       instance_id: Optional[str] = None,
                       max_attempts: int = 3) -> NotificationDelivery:
        # The payload is NOT persisted — we only persist metadata (no PII).
        _ = payload
        delivery = NotificationDelivery.create(
            channel=channel, address=address, provider=provider_id,
            subject_ref=subject_ref, tenant_id=tenant_id,
            country_code=country_code,
            instance_id=instance_id, max_attempts=max_attempts)
        await self._log.save(delivery)
        await increment("workflow_notification_enqueued",
                          labels={"channel": channel,
                                  "provider": provider_id})
        return delivery

    async def dispatch_once(self, *, batch_size: int = 25) -> int:
        now = self._clock()
        batch = await self._log.claim_next_batch(
            now_iso=now.isoformat(), limit=batch_size)
        # NOTE: we no longer have the original payload (privacy). Real
        # providers must be idempotent + template-key-driven; those
        # arrive in later business slices. For Slice 4.1 we exercise the
        # retry/DLQ machinery only — providers are stubs.
        stub_payload: dict = {}
        processed = 0
        for delivery in batch:
            provider = self._providers.get(
                (delivery.channel, delivery.provider))
            delivery.mark_sending()
            await self._log.save(delivery)
            if provider is None:
                delivery.mark_failed(
                    error=f"no provider for "
                          f"{delivery.channel}/{delivery.provider}",
                    next_attempt_at=None)
                await self._log.save(delivery)
                await audit(
                    action="workflow.notification.dead_lettered",
                    resource_type="workflow_notification",
                    resource_id=delivery.delivery_id,
                    decision="PERMIT",
                    payload={"reason": "no provider",
                             "channel": delivery.channel,
                             "provider": delivery.provider})
                await increment("workflow_notification_dead_lettered",
                                  labels={"channel": delivery.channel,
                                          "provider": delivery.provider})
                processed += 1
                continue
            try:
                await provider.send(
                    address="__hashed__" + delivery.address_hash,
                    subject_ref=delivery.subject_ref,
                    payload=stub_payload)
            except Exception as exc:  # noqa: BLE001
                # Deterministic 5s exponential-ish retry.
                delay = 5 * (2 ** delivery.attempts)
                next_at = (now + timedelta(
                    seconds=min(delay, 60))).isoformat()
                delivery.mark_failed(error=str(exc),
                                       next_attempt_at=next_at)
                await self._log.save(delivery)
                if delivery.status == DeliveryStatus.DEAD_LETTERED.value:
                    await audit(
                        action="workflow.notification.dead_lettered",
                        resource_type="workflow_notification",
                        resource_id=delivery.delivery_id,
                        decision="PERMIT",
                        payload={"error": str(exc),
                                 "attempts": delivery.attempts,
                                 "channel": delivery.channel,
                                 "provider": delivery.provider})
                    await increment(
                        "workflow_notification_dead_lettered",
                        labels={"channel": delivery.channel,
                                "provider": delivery.provider})
                else:
                    await increment("workflow_notification_retry",
                                      labels={"channel": delivery.channel,
                                              "provider": delivery.provider})
            else:
                delivery.mark_delivered()
                await self._log.save(delivery)
                await audit(action="workflow.notification.delivered",
                             resource_type="workflow_notification",
                             resource_id=delivery.delivery_id,
                             decision="PERMIT",
                             payload={"channel": delivery.channel,
                                      "provider": delivery.provider})
                await increment("workflow_notification_delivered",
                                  labels={"channel": delivery.channel,
                                          "provider": delivery.provider})
            processed += 1
        return processed
