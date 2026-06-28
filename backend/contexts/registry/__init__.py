"""Aquasavannah LandVault — Registry Bounded Context.

The single authoritative aggregate root for every land record in the
platform. Per ADR-001 and ADR-014:

* `LandVault` is the ONLY aggregate root for land records.
* `registry_id` (UUID/ULID) is the immutable internal identity.
* `parcel_number` (STATE-LGA-WARD-PROPTYPE-NNNNNN) is the immutable
  public reference.
* `legacy_aliases[]` are lookup-only, never authoritative.
* All writes occur through this bounded context; cross-context
  communication is exclusively via immutable versioned domain events
  published through the transactional outbox.
"""
