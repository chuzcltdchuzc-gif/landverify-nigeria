"""Kernel events subsystem — immutable Domain Events + transactional Outbox (ADR-004).

Public surface:
    * `Envelope` — the versioned wrapper every event carries
    * `publish(envelope, session=None)` — insert into the outbox
    * `start_outbox_publisher()` / `stop_outbox_publisher()` — relay loop
    * `EVENT_TYPES` — canonical Phase 1 event-type names

All Phase 1 events are emitted from the Identity context inside the same TX
as the state change they describe, guaranteeing event-state consistency
(transactional outbox pattern).
"""
from kernel.events.envelope import Envelope, new_envelope  # noqa: F401
from kernel.events.outbox import (  # noqa: F401
    EVENT_TYPES,
    Outbox,
    configure_outbox,
    publish,
    start_outbox_publisher,
    stop_outbox_publisher,
    subscribe,
)
