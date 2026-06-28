"""Audit subsystem — append-only (ADR-005).

There is no update or delete path through this module — even for service
principals. Storage grows monotonically. A SHA-256 hash chain links each entry
to the previous one so any tampering is detectable downstream.
"""
from kernel.audit.store import AuditEntry, AuditStore, audit, configure_audit_store  # noqa: F401
