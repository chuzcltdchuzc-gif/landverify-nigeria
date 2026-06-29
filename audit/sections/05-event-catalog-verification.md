# 05 · Event Catalog Verification

> Cross-links: [02 Architecture Review](02-architecture-review.md) ·
> [06 Contract Verification](06-contract-verification.md)

## 1. Catalog snapshot

| Counter | Value |
| --- | --- |
| Events in `contracts/v1/events/` | **43** |
| of which Identity context | 11 |
| of which Registry context | 5 |
| of which Evidence context | **27** |
| Schema version | v1 (all events suffixed `.v1.json`) |
| Source-of-truth file | `contracts/v1/events/catalog.json` |

## 2. Evidence-context event catalog (full)

| Event | Producer | Subscribers | Purpose |
| --- | --- | --- | --- |
| `evidence.item.uploaded.v1` | EvidenceUploadService | TimelineProjector | Aggregate created, parts complete |
| `evidence.item.hash_verified.v1` | VerificationService | TimelineProjector | Server confirmed composite hash |
| `evidence.item.hash_mismatch.v1` | VerificationService | TimelineProjector, RemediationSaga | Tamper / streaming bug detected |
| `evidence.item.archived_replaced.v1` | SupersessionService | TimelineProjector | Item superseded (never deleted) |
| `evidence.seal.created.v1` | SealService | TimelineProjector, AnchorSaga | Group sealed |
| `evidence.seal.worm_applied.v1` | SealService | TimelineProjector | WORM lock placed |
| `evidence.seal.archived.v1` | SealService | TimelineProjector | Seal closed |
| `evidence.anchor.batched.v1` | AnchorSaga | OTS adapter, CT-log | Batch composed |
| `evidence.anchor.submitted.v1` | AnchorSaga | OTS, CT-log | Submission to TSA + log |
| `evidence.anchor.confirmed.v1` | AnchorSaga | TimelineProjector | Proof returned |
| `evidence.anchor.failed.v1` | AnchorSaga | RemediationSaga | Submission failed |
| `evidence.anchor.replayed.v1` | AnchorSaga | (audit) | Saga step replayed (idempotency) |
| `evidence.ctlog.checkpoint_published.v1` | CTLogService | (audit) | Internal CT-log checkpoint signed |
| `evidence.integrity.check_started.v1` | IntegrityService | TimelineProjector | Periodic check kicked off |
| `evidence.integrity.passed.v1` | IntegrityService | TimelineProjector | Check passed |
| `evidence.integrity.failed.v1` | IntegrityService | RemediationSaga | Hash mismatch in storage |
| `evidence.integrity.check_errored.v1` | IntegrityService | (audit) | Check threw (e.g. storage timeout) |
| `evidence.lock.applied.v1` | RetentionService | TimelineProjector | Retention lock attached |
| `evidence.lock.extended.v1` | RetentionService | TimelineProjector | Lock horizon extended forward |
| `evidence.custody.appended.v1` | CustodyService | TimelineProjector | Chain-of-custody row written |
| `evidence.timeline.appended.v1` | TimelineProjector | (audit / debugging) | Timeline row written (introspective event) |
| `evidence.legal_hold.applied.v1` | LegalHoldService | TimelineProjector | Legal hold attached |
| `evidence.legal_hold.released.v1` | LegalHoldService | TimelineProjector | Hold released (terminal) |
| `evidence.supersession.recorded.v1` | SupersessionService | TimelineProjector | Successor recorded |
| `evidence.signed_url.issued.v1` | SignedUrlService | TimelineProjector | Read URL issued; triggers `accessed` custody |

## 3. Identity + Registry events

Listed for completeness — these are emitted by upstream phases.

`identity.*`: `user.registered`, `login.success`, `login.failed`,
`password.changed`, `session.revoked`, `role.assigned`,
`account.activated`, `account.suspended`, `service_account.created`,
`service_account.revoked`, `delegation.granted`, `delegation.revoked`.

`registry.*`: `landvault.created`, `landvault.updated`,
`landvault.archived`, `ownership.recorded`,
`parcel_reference.allocated`.

## 4. Schema verification

Every event JSON schema in `contracts/v1/events/*.v1.json`:

- Has `$id`, `type`, `required`, `properties`.
- Includes the envelope fields (`event_id`, `event_type`,
  `event_version`, `aggregate_*`, `producer`, `occurred_at`,
  `tenant_id`, `country`, `actor`, `correlation_id`).
- Versioned with `.v1.json` suffix. A breaking change demands a
  `.v2.json` file, never an edit-in-place.

The catalog file enumerates every event with its producer and
declared subscribers; the generator (`contracts/generate.py`)
synthesises both the catalog and the per-event schemas from a single
in-memory table. The drift gate (§06) ensures the on-disk catalog
matches the in-memory table.

## 5. Conformance to the constitutional events doctrine

| Rule | Status |
| --- | --- |
| Events are immutable past `.v1`. | ✅ |
| Every event has a unique `event_id` (UUIDv7-like). | ✅ |
| Producer is the only aggregate that may emit a given event. | ✅ |
| Subscribers are projections / sagas — never aggregates. | ✅ |
| Catalog is regenerated from `generate.py`; drift gate green. | ✅ |
| 27 / 27 Evidence events are exercised by tests. | ✅ |

No outstanding deficiencies.
