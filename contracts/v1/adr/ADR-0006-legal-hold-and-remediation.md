# ADR-0006 — Legal Hold + Retention Precedence + Verify-Then-Cutover Remediation (Phase 3, was 018)

* **Status:** Proposed (blocking on Phase 3.0 sign-off)
* **Date:** 2026-06-28
* **Contract version introduced:** `1.2.0`
* **Authors:** Platform team
* **Related:** ADR-0003, ADR-0004, ADR-0005

## Context

Two failure modes are unacceptable for a land registry:

1. **Retention-driven deletion** of evidence that's under legal
   investigation. Once a court / regulator says "preserve everything
   about parcel X", retention timers must yield.
2. **In-place rewrites** of sealed evidence. Migrating, re-encrypting,
   or relocating sealed bytes must never produce a window where the
   only copy is unverified or where the source bytes vanish before the
   destination is proved correct.

The Phase 3 directive states:

> Implement LEGAL HOLD that overrides retention.
>
> Remediation is a VERIFY-THEN-CUTOVER saga: move → read back → re-hash
> → match → create evidence item → only then null the inline source.
> Never delete a source before verification.

## Decision

### Legal Hold

* New aggregate `LegalHold` (`evidence_holds` collection). Scope is
  either a list of `evidence_ids` or `{registry_id, all_evidence:
  true}`.
* `place_hold()` is allowed regardless of current retention; the
  retention sweeper consults `evidence_holds` and skips any item whose
  `evidence_id` matches an active (un-lifted) hold.
* `set_retention()` cannot truncate the effective retention while an
  active hold matches; the operator must lift the hold first.
* `lift_hold()` requires the same role tier as the placer or higher.
  Each lift logs `lifted_by`, `lifted_at`, and a mandatory reason.
* Place + lift both write to `evidence_timeline` and
  `evidence_custody`; both emit domain events.

### Retention precedence

```text
effective_retention(item) = max(item.retention_expires_at,
                                {hold.lifted_at for hold in active_holds(item)})

if any active hold exists for item: SKIP retention sweep
```

Implementation: the retention sweeper joins `evidence_items` with
`evidence_holds` on `tenant_id` AND (`evidence_id ∈ hold.scope` OR
`registry_id = hold.scope.registry_id`). Anything matched is skipped
and logged as `skipped_due_to_legal_hold`.

### Verify-then-cutover remediation saga

For any operation that must change the physical location, encryption
envelope, or storage provider of a sealed `EvidenceItem`, the
`RemediationSaga` is the only legal path. Direct adapter mutations are
forbidden by the application service and by repository checks.

#### State machine

```text
requested ─► src_locked ─► moving ─► moved ─► reverified ─► cutover_committed
                                       │
                                       ▼
                                reverification_failed ─► src_unlocked ─► failed
```

Mandatory ordering:

1. **`requested`** — super_admin calls
   `POST /api/v1/evidence/items/{id}/remediate` with `target` and
   `reason`. A `RemediationRequest` aggregate is created.
2. **`src_locked`** — a read-lock is recorded on the source item; any
   concurrent state-changing call (re-encrypt, archive, etc.) rejects
   with `409 evidence.remediation_in_progress`.
3. **`moving`** — `StoragePort.move(src, dst, verify_callback)` streams
   bytes to the destination. The `verify_callback` is invoked with the
   streamed bytes during the write and computes a running SHA-256 of
   the destination.
4. **`moved`** — source still exists (untouched, WORM-locked).
5. **`reverified`** — an INDEPENDENT read from `dst` (not the running
   counter from step 3) recomputes the SHA-256 from scratch and
   compares it to the original `server_hash`. **If mismatch → abort,
   leave source intact, record `reverification_failed`, emit
   `evidence.remediation.failed.v1`.**
6. **`cutover_committed`** — only on reverify success — a NEW
   `EvidenceItem` aggregate is created with `replaces` pointing to the
   original. The original moves to `archived_replaced`, with
   `replaced_by` set to the new aggregate's id. **Only then** does the
   saga null the original's inline `storage_locator` (the WORM-locked
   bytes remain in storage — we never delete WORM bytes; we unlink the
   reference). Emit `evidence.remediation.committed.v1`.

#### Binding invariants

* **No state transition past `moved` deletes anything in the source
  path.** Only `cutover_committed` is allowed to null the source
  locator, and only after `reverified`.
* The saga is durable in `evidence_remediation_sagas` (one document
  per saga; state transitions are append-only).
* A crash mid-saga is recoverable: a startup worker resumes any saga
  not in a terminal state.

### Orphan reconciliation

A separate worker (`orphan_reconciliation`) runs hourly. It enumerates
storage objects (per tenant, per provider) and checks for the absence
of a corresponding `evidence_items` row. Orphans are quarantined in
`evidence_orphans` and an `evidence.orphan.detected.v1` event is
emitted. Resolution is operator-driven (ingest, destroy under
retention, or escalate).

## Consequences

### Positive

* Legal holds are unambiguous and one source of truth.
* Remediation is provably loss-free under failure injection (the test
  suite injects crashes between every saga transition; the source
  remains readable in every failure path).
* Orphan reconciliation closes the loop between storage and
  application state.

### Negative / Trade-offs

* Storage costs grow until WORM retention expires (we never delete
  sealed bytes mid-flight). This is by design — the cost of legal
  defensibility.
* Operators must explicitly lift holds before retention can take
  effect; lazy operators can keep evidence pinned forever. Mitigation:
  hold dashboards + reminders in Phase 6.

## Compliance

Phase Acceptance Review must demonstrate:

* Legal hold prevents retention sweep (test forces retention expiry +
  active hold + sweep → item still present).
* Remediation reverify-fail test: corrupt the destination mid-saga;
  saga reaches `reverification_failed`; source intact; emit
  `evidence.remediation.failed.v1`.
* Remediation crash-recovery test: kill the worker between any two
  transitions; restart; saga completes correctly.
* Orphan worker test: insert an unmodeled storage object; worker
  detects + quarantines + emits event within one cycle.
