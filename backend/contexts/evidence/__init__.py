"""Aquasavannah LandVault — Evidence Bounded Context (Phase 3).

This package owns all evidence aggregates (`EvidenceItem`, `Seal`,
`LegalHold`, `AnchorBatch`, `RemediationSaga`). It references LandVault
records by `registry_id` but **never** writes Registry collections —
cross-context coupling is via the transactional outbox only.

Implementation is sequenced per the Phase 3 Definitive Delivery Spec:

    3.1  Storage foundation        ← (this commit)
    3.2  PII encryption
    3.3  Media remediation
    3.4  Evidence aggregate
    3.5  Sealing
    3.6  Locking + integrity + anchoring
    3.7  Timeline + versioning
    3.8  Events + projections
    3.9  SDK + React UI
    3.10 Acceptance Review

Each step ships independently and must pass its acceptance gate before
the next step starts.
"""
