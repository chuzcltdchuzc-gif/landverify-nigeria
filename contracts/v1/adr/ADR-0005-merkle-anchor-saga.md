# ADR-0005 — Merkle-Batched External Anchor Saga (Phase 3, was 017)

* **Status:** Proposed (blocking on Phase 3.0 sign-off)
* **Date:** 2026-06-28
* **Contract version introduced:** `1.2.0`
* **Authors:** Platform team
* **Related:** ADR-0003, ADR-0004, ADR-0006

## Context

For evidence to be **legally defensible** the platform must be able to
demonstrate that a manifest hash existed AT a specific time and could
not have been altered since. Industry-standard mechanisms are:

* **Public Merkle trees** with periodic checkpoints (RFC 6962-style CT
  logs).
* **External time-stamping** (OpenTimestamps over Bitcoin).

A real-time per-seal anchor is impractical: external providers can be
slow, rate-limited, or temporarily unavailable. Batching seals into a
Merkle root and submitting only the root is the standard pattern.

The Phase 3 directive states:

> Run an operational, Merkle-batched EXTERNAL ANCHOR as an async
> request/confirm/retry/DLQ workflow; store inclusion proofs. No legal-
> defensibility claim until this is live.

## Decision

Implement an asynchronous saga behind a single `AnchorPort` Protocol,
with two interchangeable adapters:

* **`ctlog_internal`** — first to ship. Append-only Merkle tree in
  Mongo (`evidence_ctlog_tree`); a periodic checkpointer publishes the
  tree head + signature to `evidence_ctlog_checkpoints` and exports
  them to public storage. Inclusion proofs computed from persisted
  leaves.
* **`ots_v1`** — second to ship. Submits the Merkle root to OTS
  calendar servers; stores `.ots` proof bytes per request. Upgradeable
  to Bitcoin-confirmed proofs.

Both adapters are exercised by the same saga.

### Saga state machine

```text
pending_batch ─► submitted ─► confirming ─► confirmed
                    │             │
                    ▼             ▼
            submission_failed   confirmation_failed
                    │             │
                    ▼             ▼
              retry_pending ◄────┘
                    │
                    ▼ (after MAX_RETRIES)
                  dlq
```

* `pending_batch` is produced by `anchor_batcher` (cron, default every
  60s in production) which scoops up `Seal`s where
  `status = worm_applied AND anchor_batch_id IS NULL`, builds a Merkle
  root over their `manifest_hash`es, persists the batch, links each
  seal's `anchor_batch_id`, and emits `evidence.anchor.batched.v1`.
* `submitted` is set by the saga after a successful
  `request_anchor(provider_id, batch_id, root)` call.
* `confirming` polls with exponential backoff
  `[10s, 60s, 5min, 1h, 6h, 24h]` capped at 24h; after
  `MAX_CONFIRM_ATTEMPTS` (default 12) → `dlq`.
* `confirmed` materializes per-seal `InclusionProof`s, emits
  `evidence.anchor.confirmed.v1`, and unblocks "legal defensibility"
  claims in the API.
* `dlq` records emit `evidence.anchor.failed.v1` for monitoring and
  are replayable via `POST /api/v1/evidence/anchor-batches/{id}/replay`
  (super_admin only).

### Persistence

Three new collections:

| Collection                      | Purpose                                                 |
| ------------------------------- | ------------------------------------------------------- |
| `evidence_anchor_batches`       | Saga state + Merkle root + per-provider request payloads |
| `evidence_anchor_attempts`      | One row per attempt (state + timestamps + provider response hash) |
| `evidence_ctlog_tree` / `_checkpoints` | The internal CT-log itself                      |

### API surface (additive, `/api/v1/evidence/anchor-batches`)

* `GET /` — list (paginated, super_admin / compliance)
* `GET /{batch_id}` — read, including saga state + attempts
* `POST /{batch_id}/replay` — super_admin only; resubmits a `dlq` batch
* `GET /by-seal/{seal_id}` — inclusion proof bundle for a seal

### Binding invariants

* No anchor batch is created until every member seal is `worm_applied`.
* The same seal is **never** included in two batches.
* An inclusion proof is only published when `confirmed` (we never
  expose "submitted" as legal evidence).
* Retry counters and saga state are monotonic; arbitrary state changes
  are forbidden — only the saga machine writes them.

## Consequences

### Positive

* External anchor failures degrade gracefully: the seal still exists and
  is WORM-locked; only the legal-defensibility flag is delayed until
  the anchor confirms.
* Two independent providers (CT-log internal + OTS) protect against
  single-provider compromise.
* DLQ + replay gives operators a recovery path without code changes.

### Negative / Trade-offs

* Confirmed inclusion proofs lag the seal creation by at least one
  polling interval; users see "anchored" only after `confirmed`.
* Internal CT-log requires us to publish checkpoints to an externally-
  visible location (R2 / IPFS); operator setup for production.

## Compliance

Phase Acceptance Review must demonstrate:

* End-to-end happy path: upload → verify → seal → batch → submit →
  confirm → inclusion proof recorded.
* Forced DLQ: kill the provider; saga reaches `dlq`; super_admin
  replays; saga reaches `confirmed`.
* Inclusion proof verification by the offline verifier (ADR-Phase 3.5)
  against the CT-log checkpoint AND the OTS calendar.
