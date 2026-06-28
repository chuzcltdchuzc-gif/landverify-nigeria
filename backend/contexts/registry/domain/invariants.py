"""Domain-level exceptions for the Registry context.

These map onto canonical RFC 7807 problem types via the API layer.
"""
from __future__ import annotations


class RegistryError(Exception):
    """Base for any registry domain error."""


class InvariantViolation(RegistryError):
    """Raised when an aggregate invariant would be violated by an operation."""


class ImmutableFieldError(InvariantViolation):
    """Attempt to change an immutable field (registry_id, parcel_number, tenant_id, country_code)."""


class ConcurrencyConflict(RegistryError):
    """Optimistic concurrency check failed."""


class LockedStateError(InvariantViolation):
    """Operation rejected because the aggregate is in a locked status."""


class SoftDeletedError(InvariantViolation):
    """Operation rejected because the aggregate is soft-deleted."""


class GeometryValidationError(InvariantViolation):
    """Geometry failed validation rules."""
