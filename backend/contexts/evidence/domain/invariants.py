"""Domain-level exceptions for the Evidence context (Phase 3.4)."""
from __future__ import annotations


class EvidenceError(Exception):
    """Base for any evidence-context domain error."""


class InvariantViolation(EvidenceError):
    """Aggregate invariant would be violated by an operation."""


class ImmutableFieldError(InvariantViolation):
    """Attempt to change a field that is immutable after construction."""


class SealedItemError(InvariantViolation):
    """Operation rejected because the EvidenceItem is sealed (WORM)."""


class HashMismatchError(InvariantViolation):
    """Server-computed read-back hash did not match the streamed hash, or
    the client claim disagrees with the server-computed value."""


class WormViolationError(InvariantViolation):
    """Operation would mutate a WORM-locked artifact."""


class ConcurrencyConflict(EvidenceError):
    """Optimistic concurrency check failed."""


class TransitionError(InvariantViolation):
    """The requested status transition is not legal."""
