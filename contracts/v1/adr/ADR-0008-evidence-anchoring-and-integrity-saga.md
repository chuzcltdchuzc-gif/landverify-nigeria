# ADR-0008 — Evidence Anchoring & Integrity Saga (Phase 3.6)

*Status*: **Blueprint (proposed)** — pending operator sign-off. No implementation code lands against this ADR until the blueprint is approved.
*Phase*: 3.6 (Locking, Integrity Verification, Merkle Anchoring).
*Depends on*: ADR-0003 (Evidence bounded context), ADR-0004 (server-side hashing), ADR-0005 (Merkle anchor saga — blueprint), ADR-0006 (legal hold + remediation), ADR-0007 (Canonical Evidence Aggregate + Sealing).
*Contract bump target*: `1.2.0 → 1.3.0` (additive minor).

---

## 1. Context

Phase 3.4 + 3.5 produced immutable, WORM-locked `EvidenceItem` and `Seal` aggregates. Sealing pins evidence to a deterministic `merkle_root` + `manifest_hash`, but those roots are still **internal** — anyone trusting the platform must trust the platform's own database for the existence and time of sealing.

Phase 3.6 closes that loop by publishing the seal's Merkle root to **independent, append-only, externally-verifiable transparency logs**. After Phase 3.6, anyone holding the seal manifest + the inclusion proof + the published checkpoint can prove the seal existed at a specific time, regardless of platform availability or operator integrity.

This is the platform's most consequential trust mechanism. It is also the most operationally complex: it spans the platform/external boundary, must survive provider outages, must be resumable across worker crashes, and must never delete or mutate any sealed bytes.

The architectural risk is high enough that the operator has elected **blueprint-only** delivery for this phase. Implementation is deferred until this document and the updated `PHASE3_SPEC.md §3.6` / `PHASE3_BLUEPRINT.md` are approved.

---

## 2. Decision (summary)

1. Introduce two new aggregates: **`EvidenceLock`** (the WORM lock record as a first-class auditable artifact) and **`EvidenceIntegrityCheck`** (the immutable verification log).
2. Introduce **`AnchorBatch`** as a saga aggregate with the eight-state FSM defined in §6.
3. Define **`AnchorPort`** and **`CheckpointPublisherPort`** as the sole external coupling. The domain depends only on these Protocols.
4. Ship two `AnchorPort` adapters in this phase — **`ctlog_internal`** (primary, ships first) and **`ots_v1`** (secondary, ships second). Adding a third (e.g. an external CT log, a blockchain) is additive: new adapter, no domain change.
5. The saga is **resumable, idempotent, retryable, replayable, and DLQ-backed**, mirroring the Phase 3.3 media remediation saga.
6. No registry collection is ever written. No sealed evidence is ever mutated. Failures emit corrective events; they never delete or rewrite history.

---

## 3. New aggregates

### 3.1 `EvidenceLock`

The Phase 3.5 `Seal.apply_worm()` command already calls `StoragePort.apply_object_lock` for every referenced item. Today the lock outcome lives only inside the `evidence.seal.worm_applied.v1` event payload. Phase 3.6 elevates each lock to a first-class auditable aggregate so retention extensions, status queries, and downstream consumers have a stable handle.

#### Fields (`evidence_locks` collection)

| Field                 | Type                  | Notes                                                          |
| --------------------- | --------------------- | -------------------------------------------------------------- |
| `lock_id`             | str, immutable        | `lck_<32hex>`                                                  |
| `evidence_id`         | str, immutable        | Foreign key to `EvidenceItem`                                  |
| `seal_id`             | str, immutable        | The Seal that triggered the lock                               |
| `tenant_id`           | str, immutable        | From ExecutionContext                                          |
| `country_code`        | str, immutable        | From ExecutionContext                                          |
| `storage_provider`    | str, immutable        | `local_fs_worm` \| `r2`                                        |
| `storage_locator`     | str, immutable        | Canonical object key as string                                 |
| `mode`                | enum, immutable       | `compliance` only (governance mode rejected at the port)       |
| `retention_until`     | str ISO8601           | Forward-only (extensions allowed, contractions denied)          |
| `applied_at`          | str ISO8601, immutable |                                                                |
| `applied_by`          | str, immutable        | Principal id                                                   |
| `extensions`          | list[ExtensionRecord] | Append-only history of retention extensions                    |
| `last_status_check`   | str ISO8601?          | Most recent `lock_status` query timestamp                       |
| `version`             | int                   | Monotonic                                                      |
| `schema_version`      | int                   | Starts at 1                                                    |

#### Invariants

* `lock_id`, `evidence_id`, `seal_id`, `storage_provider`, `storage_locator`, `mode`, `applied_at`, `applied_by` are immutable.
* `mode` MUST be `compliance`. Construction rejects any other value.
* `retention_until` is forward-only: `extend_retention(new_until)` requires `new_until > retention_until`. Reduction is structurally impossible — no command on the aggregate even names it.
* `extensions` is append-only and carries `{at, by, previous_until, new_until, reason}`.
* `version` is monotonic.

#### Commands

* `EvidenceLock.create(...)` — factory, called by the Seal application service inside the same transaction as `apply_worm`. Emits `evidence.lock.applied.v1`.
* `extend_retention(new_until, by, reason)` — forward-only retention extension. Emits `evidence.lock.extended.v1`.
* `record_status_check(probed_at, observed_locked, observed_until)` — non-mutating in the security sense but bumps `last_status_check` for operational metrics. Emits no event.

---

### 3.2 `EvidenceIntegrityCheck`

The phase introduces the platform's first **continuous integrity verification** capability: periodic and on-demand re-hashing of stored evidence bytes to detect silent storage corruption, malicious tampering, or backup-restore drift.

#### Fields (`evidence_integrity_checks` collection)

| Field                  | Type                  | Notes                                                            |
| ---------------------- | --------------------- | ---------------------------------------------------------------- |
| `check_id`             | str, immutable        | `chk_<32hex>`                                                    |
| `evidence_id`          | str, immutable        | Foreign key                                                      |
| `tenant_id`            | str, immutable        |                                                                  |
| `country_code`         | str, immutable        |                                                                  |
| `triggered_by`         | enum, immutable       | `scheduled` \| `on_demand` \| `pre_seal` \| `post_remediation`   |
| `triggered_by_principal` | str?, immutable     | Principal id (null for `scheduled`)                              |
| `expected_hash`        | str, immutable        | The `server_hash` recorded on the EvidenceItem                   |
| `observed_hash`        | str?, immutable       | Recomputed from `StoragePort.open_for_streaming_hash`. Null while in-flight. |
| `outcome`              | enum                  | `running → pass` \| `running → fail` \| `error`                  |
| `lock_status_observed` | obj?                  | Snapshot of `ObjectLockStatus` at check time                     |
| `started_at`           | str ISO8601, immutable |                                                                  |
| `completed_at`         | str ISO8601?          | Set when the check terminates                                    |
| `error_summary`        | str?                  | Set only when `outcome == "error"`                               |
| `seq`                  | int, immutable        | Monotonic per-evidence sequence (append-only chain)             |
| `prev_hash`            | str?, immutable       | sha256 of the previous check's `entry_hash` (chain head: null)   |
| `entry_hash`           | str, immutable        | `sha256(prev_hash || canonical_json(check_record))`              |
| `schema_version`       | int                   | Starts at 1                                                      |

#### Invariants

* Every field except `outcome`, `completed_at`, and `error_summary` is immutable at construction. `outcome`, `completed_at`, and `error_summary` are write-once and may only transition from their initial null/`running` values.
* `seq` is strictly monotonic per `evidence_id`: enforced by a unique index `(evidence_id, seq)`.
* `prev_hash` / `entry_hash` form a tamper-evident chain. The repository **refuses `update` and `delete` operations** at the database adapter level. The only legal write is `insert`, and the only legal read pattern is "load the whole chain for `evidence_id`" or "load by `check_id`".
* A failed check (`outcome == "fail"`) emits `evidence.integrity.failed.v1`. It does **not** mutate the `EvidenceItem`. Remediation goes through the existing Phase 3.3 media remediation saga; the Phase 3.6 layer only **detects and records**.
* On `evidence.integrity.failed.v1` the saga proceeds to a manual review queue (Phase 3.10 territory) — Phase 3.6 ships the detection + immutable record, not the remediation trigger.

#### Commands

* `EvidenceIntegrityCheck.start(...)` — factory, emits `evidence.integrity.check_started.v1`.
* `record_pass(observed_hash, lock_status)` — write-once transition `running → pass`. Emits `evidence.integrity.passed.v1`.
* `record_fail(observed_hash, lock_status, reason)` — write-once `running → fail`. Emits `evidence.integrity.failed.v1`.
* `record_error(error_summary)` — write-once `running → error`. Emits `evidence.integrity.check_errored.v1`.

---

### 3.3 `AnchorBatch` (saga aggregate)

The load-bearing aggregate of Phase 3.6. Each `AnchorBatch` represents one Merkle root submitted to one anchor provider. Multiple Seals share a single batch; a single seal participates in N batches (one per provider) — `Seal.anchor_batch_id` is a list, not a scalar, **or** each `(seal_id, provider_id)` produces its own batch — see §5.

#### Fields (`evidence_anchor_batches` collection)

| Field                  | Type                       | Notes                                                                 |
| ---------------------- | -------------------------- | --------------------------------------------------------------------- |
| `batch_id`             | str, immutable             | `bch_<32hex>`                                                         |
| `provider_id`          | enum, immutable            | `ctlog_internal` \| `ots_v1` (extensible)                             |
| `tenant_id`            | str, immutable             | First-tenant of the batched seals (cross-tenant batching disallowed)  |
| `country_code`         | str, immutable             |                                                                       |
| `seal_ids`             | list[str], immutable       | The Seals batched into this anchor; sorted lexicographically          |
| `seal_leaves`          | list[LeafRecord], immutable | `[{seal_id, merkle_root}]` sorted by `seal_id` — feeds tree construction |
| `merkle_root`          | str, immutable             | sha256 of the canonical Merkle tree over `seal_leaves`                |
| `state`                | enum                       | See FSM in §6                                                         |
| `attempts`             | int                        | Monotonic count of all `submit` + `poll` cycles                       |
| `last_attempt_at`      | str ISO8601?               | For backoff scheduling                                                |
| `next_attempt_at`      | str ISO8601?               | Deterministic backoff computation                                     |
| `provider_request_id`  | str?                       | Returned by `AnchorPort.request_anchor`; idempotency anchor           |
| `provider_response`    | obj?                       | Provider-specific payload (e.g. `.ots` bytes, CT-log SCT, checkpoint refs) |
| `inclusion_proofs`     | dict[seal_id, obj]?        | Materialized on `confirmed`: per-seal Merkle path + signed checkpoint |
| `dlq_reason`           | str?                       | Set only on terminal `dead_letter`                                    |
| `replayed_from`        | str?                       | If this batch is a replay, references the original `batch_id`         |
| `created_at`           | str ISO8601, immutable     |                                                                       |
| `version`              | int                        | Monotonic                                                             |
| `schema_version`       | int                        | Starts at 1                                                           |

#### Invariants

* `batch_id`, `provider_id`, `seal_ids`, `seal_leaves`, `merkle_root`, `tenant_id`, `country_code`, `created_at` are immutable after construction.
* `state` transitions are constrained by the FSM in §6. Illegal transitions raise `WorkflowTransitionError → 409`.
* `attempts` is monotonic. `last_attempt_at` and `next_attempt_at` are operational metadata.
* `inclusion_proofs` is write-once — set exactly when the saga reaches `confirmed`.
* `replayed_from` is set exactly when this batch was produced by a `dead_letter → replay → submitted` rotation; never set on first attempts.
* Cross-tenant batching is **forbidden**. Cross-country batching is **forbidden**. The batcher selects only seals matching the running tenant/country scope.

#### Companion log: `AnchorAttempt` (`evidence_anchor_attempts`)

Append-only per-attempt record. Carries `{batch_id, attempt_no, started_at, completed_at, outcome, error_summary, provider_response_snapshot, prev_hash, entry_hash}`. Same append-only contract as `EvidenceIntegrityCheck`: insert-only at the adapter, tamper-evident chain.

---

## 4. Merkle tree construction (canonical, deterministic, NIST-aligned)

The merkle root algorithm MUST be reproducible by an offline verifier (Phase 3.10 territory) and MUST match the algorithm used in Phase 3.5 `Seal.create` so that the per-Seal `merkle_root` and per-Batch `merkle_root` use the same primitive.

### 4.1 Leaf ordering

Leaves are the `merkle_root` of each participating Seal (NOT the individual evidence hashes — Phase 3.6 anchors **seals**, not items). Leaves are sorted lexicographically by `seal_id` so the batch root is deterministic regardless of the order in which the batcher scooped seals.

### 4.2 Hash primitive

SHA-256 only. Inputs are the hex-encoded leaf strings concatenated as ASCII bytes (the existing `compute_merkle_root` primitive shipped in Phase 3.4 / 3.5). No domain-separator prefix is introduced in this phase; the offline verifier matches by reproducing the exact concatenation.

### 4.3 Odd-level duplication

When a level has an odd number of nodes, the last node is duplicated (Bitcoin-style). This matches the existing primitive; documented here for the offline verifier.

### 4.4 Single-leaf batches

A single-seal batch returns the seal's own `merkle_root` as the batch root — no wrapping hash. This is consistent with `compute_merkle_root([leaf]) == leaf`.

### 4.5 Determinism property (tested invariant)

For any two non-empty lists `A` and `B` with the same set membership, `compute_merkle_root(A) == compute_merkle_root(B)`. Test fixture uses NIST RFC 6234 SHA-256 vectors.

---

## 5. Port contracts

### 5.1 `AnchorPort` Protocol

```python
class AnchorPort(Protocol):
    provider_id: str                   # "ctlog_internal" | "ots_v1"

    async def request_anchor(self, *, batch_id: str, root: str
                              ) -> AnchorRequest: ...
    # Idempotent over (batch_id, root). Calling twice MUST return
    # the same AnchorRequest (same provider_request_id).

    async def poll_confirmation(self, request: AnchorRequest
                                 ) -> AnchorState: ...
    # AnchorState ∈ {pending, confirmed, failed_transient, failed_permanent}.

    async def fetch_inclusion_proof(self, request: AnchorRequest,
                                     leaf_hash: str
                                     ) -> InclusionProof: ...
    # InclusionProof carries provider-specific bytes (e.g. CT SCT
    # signature + audit path, OTS proof bytes + calendar refs).
```

The port deliberately exposes **no batch-deletion** or **no provider-side cancellation** verb. Once a batch is submitted to a provider, it is recorded on that provider's append-only log forever — Phase 3.6 cannot retract it.

### 5.2 `CheckpointPublisherPort` Protocol

```python
class CheckpointPublisherPort(Protocol):
    publisher_id: str                  # "r2_public" | "ipfs_pin" | ...

    async def publish_checkpoint(self, *, head: TreeHead,
                                  signature: bytes) -> CheckpointRef: ...
    # Writes the signed tree head to a public, append-only target.
    # Used by ctlog_internal to publish daily heads.

    async def fetch_checkpoint(self, head_seq: int
                                ) -> Optional[CheckpointRef]: ...
    # Read-side for the offline verifier (Phase 3.10).
```

Phase 3.6 ships **one** `CheckpointPublisherPort` adapter (`r2_public_stub`). Production deployments swap in real R2 / IPFS / S3 implementations without touching the saga.

---

## 6. Anchoring saga lifecycle (binding FSM)

The eight states requested:

```text
                    ┌──────────────┐
                    │ pending_batch│   ← created by AnchorBatcher
                    └──────┬───────┘
                           │ build merkle root over selected seals
                           ▼
                    ┌──────────────┐
                    │   sealed     │   ← batch root committed to disk
                    └──────┬───────┘   (seal_ids + leaves + root frozen)
                           │ AnchorConfirmer claims
                           ▼
                    ┌──────────────┐
                    │  submitted   │   ← AnchorPort.request_anchor OK
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
              ┌─────┤  confirming  ├─────┐
              │     └──────────────┘     │
              │ confirm OK               │ transient error
              ▼                          ▼
       ┌────────────┐             ┌────────────┐
       │  confirmed │             │   failed   │  ← attempts++; schedule next_attempt_at
       └────────────┘             └─────┬──────┘
                                        │
                          attempts ≥ MAX_ATTEMPTS
                                        ▼
                                ┌────────────┐
                                │ dead_letter│  ← terminal; super_admin only exit
                                └─────┬──────┘
                                      │ super_admin /replay
                                      ▼
                                ┌────────────┐
                                │   replay   │ ← new batch_id, replayed_from=old
                                └─────┬──────┘
                                      │
                                      ▼
                                 (submitted)
```

### 6.1 State definitions

| State        | Meaning                                                                                            | Permitted exits                                  |
| ------------ | -------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| `pending_batch` | Batcher has selected seals but has NOT yet committed the batch row.                             | → `sealed`                                        |
| `sealed`     | Batch row persisted with `merkle_root` + `seal_leaves`. Awaiting confirmer pickup.                  | → `submitted`                                     |
| `submitted`  | `AnchorPort.request_anchor` returned a `provider_request_id`. Provider has accepted.                | → `confirming`                                    |
| `confirming` | Polling `AnchorPort.poll_confirmation` with exponential backoff.                                    | → `confirmed` \| `failed`                          |
| `confirmed`  | Provider confirmed inclusion. Inclusion proofs materialized; `Seal.attach_anchor_batch` called.    | (terminal positive)                              |
| `failed`     | Transient provider error. Reschedule per backoff. Increment `attempts`.                            | → `submitted` (retry) \| `dead_letter` (max)      |
| `dead_letter`| Terminal negative. Persisted with `dlq_reason`. Emits `evidence.anchor.failed.v1` for monitoring.   | → `replay` (super_admin only)                     |
| `replay`     | Transient marker. A NEW `AnchorBatch` is created with `replayed_from = original.batch_id`. Original stays in `dead_letter` forever. | The new batch goes through `submitted → …` again. |

### 6.2 Backoff schedule (policy-driven, defaults)

`[10s, 60s, 5min, 1h, 6h, 24h]`, capped at 24h thereafter. Default `MAX_ATTEMPTS = 12`. Both values live in `EVIDENCE_ANCHOR_*` env vars so operators can tune without code changes.

### 6.3 Failure semantics (binding)

* `failed_transient` from the port → state `failed`, then `submitted` after backoff. `attempts++`.
* `failed_permanent` from the port → state `dead_letter` immediately.
* Network timeout → treated as `failed_transient`.
* Crash mid-saga: on worker restart, `AnchorConfirmer` re-claims any batch in `submitted` or `confirming` whose `next_attempt_at` is in the past. Idempotency key `(batch_id, provider_request_id)` prevents double-submission.

### 6.4 No-mutation guarantees

* The original `AnchorBatch` row in `dead_letter` is **never mutated** post-terminal. Replay produces a **new** `batch_id`. Anyone auditing the history can see both rows.
* The same applies to `confirmed`: the row is frozen. Re-running confirmation against an already-confirmed batch is a no-op (`AnchorPort.poll_confirmation` is idempotent over `provider_request_id`).
* No `delete` operation exists at the repository layer for `evidence_anchor_batches`. Index plan: `unique(batch_id)`, `compound(state, next_attempt_at)`, `compound(tenant_id, country_code, created_at desc)`.

---

## 7. Adapter ordering

### 7.1 `ctlog_internal` (ships first)

* Append-only `evidence_ctlog_tree` collection — one row per leaf, `{leaf_seq, leaf_hash, batch_id, appended_at}`. Unique index on `leaf_seq`.
* `ctlog_checkpointer` background job appends the current tree head to `evidence_ctlog_checkpoints` daily (operator-configurable cadence). Each checkpoint is signed by the platform's existing JWKS private key — the same key clients fetch from `/api/.well-known/jwks.json`.
* `request_anchor` appends the batch root as a new leaf in a Mongo transaction; returns the leaf's sequence number as the `provider_request_id`.
* `poll_confirmation` returns `confirmed` as soon as the **next checkpoint** publishes a tree head whose sequence is ≥ the batch's leaf sequence. This deliberately mirrors the trust model of an external CT log: confirmation requires a published checkpoint, not just a database insert.
* `fetch_inclusion_proof` computes the audit path from `evidence_ctlog_tree` deterministically. Path validation runs against the most recent checkpoint that includes the batch's leaf sequence.

### 7.2 `ots_v1` (ships second)

* HTTPS POST the batch root to the configured OTS calendar(s). Receives `.ots` proof bytes.
* Initial calendar list: `alice.btc.calendar.opentimestamps.org`, `bob.btc.calendar.opentimestamps.org`, `finney.calendar.eternitywall.com`. Configurable via env.
* `poll_confirmation` polls each calendar for upgrade. `confirmed` requires ≥ N calendars (N=2 by default, policy-driven) to upgrade their proof to a Bitcoin merkle path.
* `fetch_inclusion_proof` returns the upgraded `.ots` bytes verbatim.

### 7.3 Adapter decoupling

The two adapters share **zero domain code**. Both implement `AnchorPort`. The saga is provider-agnostic. Adding a third adapter (e.g. Sigsum, Solana, an external Google CT log) is purely additive — new file in `adapters/`, new env config, new policy entry; no domain change, no saga change.

---

## 8. Saga reliability: replay, retry, idempotency, DLQ, resumability

### 8.1 Replay (event-sourced rebuild)

The `AnchorAttempt` chain (§3.3) is the durable log of every `submit` and `poll` operation. After a Mongo restore or a development reset, replay rebuilds the saga state by walking `evidence_anchor_attempts` in `seq` order per `batch_id` and computing the terminal state. A test fixture proves: rebuild-from-attempts produces a state-identical batch to the original.

### 8.2 Retry

Bounded by `MAX_ATTEMPTS` (default 12). Exponential backoff as in §6.2. Every retry creates a new `AnchorAttempt` row — never mutates an old one.

### 8.3 Idempotency

* `AnchorPort.request_anchor(batch_id, root)` is idempotent over `(batch_id, root)`. Calling twice MUST yield the same `provider_request_id`.
* Each `AnchorAttempt` carries an `idempotency_key = sha256(batch_id || attempt_no)`. The provider call is keyed on this; collisions on the provider side are recovered by reading the existing record.

### 8.4 Dead-letter queue

`dead_letter` is the terminal failure state. A new HTTP endpoint `POST /api/v1/evidence/anchor-batches/{id}/replay` (super_admin only) produces a new `AnchorBatch` with `replayed_from = original.batch_id` and re-runs the saga. The original DLQ row stays for forensics.

### 8.5 Resumability

On worker startup, `AnchorBatcher` and `AnchorConfirmer` query their respective claim conditions:

* `AnchorBatcher`: select seals where `status == worm_applied AND anchor_batch_id is null`, group by `(tenant, country, provider)`, build batches of up to `MAX_BATCH_SIZE` (default 256 seals), persist `pending_batch → sealed` transition.
* `AnchorConfirmer`: select batches where `state IN (sealed, submitted, confirming) AND next_attempt_at <= now`. Claim via `find_one_and_update` with `state` predicate (CAS) to prevent two workers racing on the same batch.

Both workers crash-safe; the only invariant is that a batch in `submitted` or `confirming` will eventually be picked up, and the idempotency key prevents duplicate provider submissions.

---

## 9. Security invariants (proven by tests; binding)

These are the platform-level guarantees Phase 3.6 MUST demonstrate before sign-off. Each maps to one or more acceptance tests (see §11).

### 9.1 Append-only behavior

* `evidence_locks`, `evidence_integrity_checks`, `evidence_anchor_batches`, `evidence_anchor_attempts`, `evidence_ctlog_tree`, `evidence_ctlog_checkpoints` — the repository layer **refuses `update_many`, `update_one` (except for whitelisted CAS predicates on `AnchorBatch.state`), and all `delete_*` operations**. A regression test calls these methods directly through the Mongo adapter and asserts they raise `OperationNotPermitted`.

### 9.2 Deterministic Merkle roots

* `compute_merkle_root(A) == compute_merkle_root(B)` for any set-equal `A, B`. Test fixture from NIST RFC 6234.
* `Seal.merkle_root` (Phase 3.5) is byte-equal to the root recomputed from `Seal.leaf_hashes` via the same primitive (regression test).
* `AnchorBatch.merkle_root` is byte-equal to the root recomputed from `seal_leaves` (regression test).

### 9.3 Immutable anchor records

* Once `AnchorBatch.state == confirmed` or `dead_letter`, the row is **frozen at the adapter layer**: subsequent `replace` calls raise `WormViolationError`. Replay produces a new row, never a mutation.

### 9.4 No registry mutation

* Static-analysis test: scan `backend/contexts/evidence/` for any `db["landvault_landvaults"]` reference or any `client[…]["landvault_*"]` reference. The test asserts zero matches. Mirrors the Phase 3.2 `nacl`-import scan.

### 9.5 No evidence mutation after sealing

* `EvidenceItem.SEALED_LIKE_STATUSES` guard already in Phase 3.4. Phase 3.6 extends the guard to **forbid** the saga from issuing any `EvidenceItem.replace` command — the saga touches `AnchorBatch`, `EvidenceLock`, and `Seal.attach_anchor_batch`; it never crosses into `EvidenceItem`.

### 9.6 Complete audit coverage

* Every state transition in the §6 FSM emits one and only one outbox event. A test enumerates the FSM and asserts the mapping `state_pair → event_type` is exhaustive and unique.
* `evidence_audit_log` (kernel audit) carries an entry per transition with `actor` resolved from the ExecutionContext (or the system worker principal for cron-triggered transitions).
* Coverage threshold: 100% of FSM edges produce at least one audit entry.

---

## 10. API surface (additive, all under `/api/v1/evidence/*`)

| Method | Path                                                       | Purpose                                                                              | Roles                                              |
| ------ | ---------------------------------------------------------- | ------------------------------------------------------------------------------------ | -------------------------------------------------- |
| GET    | `/anchor-batches/{batch_id}`                               | Read batch + state + attempts                                                        | privileged + operational                            |
| GET    | `/anchor-batches/by-seal/{seal_id}`                        | Returns inclusion proof bundle per provider                                          | privileged + operational                            |
| POST   | `/anchor-batches/{batch_id}/replay`                        | Replay a DLQ batch (creates new batch row)                                           | super_admin                                         |
| GET    | `/locks/{lock_id}`                                         | Read EvidenceLock + extension history                                                | privileged + creator                                |
| GET    | `/locks/by-evidence/{evidence_id}`                         | Read lock(s) for an evidence                                                         | privileged + creator                                |
| POST   | `/locks/{lock_id}/extend`                                  | Forward-only retention extension                                                     | super_admin + compliance_officer                    |
| POST   | `/integrity-checks`                                        | Trigger an on-demand integrity check (`triggered_by=on_demand`)                       | super_admin + compliance_officer + government_observer |
| GET    | `/integrity-checks/{check_id}`                             | Read a check                                                                          | privileged                                          |
| GET    | `/integrity-checks/by-evidence/{evidence_id}`              | Read the full check chain for an evidence                                            | privileged                                          |
| GET    | `/ctlog/checkpoints/latest`                                | Read the latest published CT-log tree head (public — Phase 5 verifiers consume this) | authenticated + government_observer + super_admin   |

Cron jobs (`AnchorBatcher`, `AnchorConfirmer`, `IntegrityScheduler`, `CtlogCheckpointer`) have no HTTP surface — they run in the existing background worker shell (`services.worker.start_worker`).

---

## 11. Acceptance tests (target ~30, mapped 1:1 to §9 invariants)

| Test file                                          | Cases | Maps to                                          |
| -------------------------------------------------- | ----- | ------------------------------------------------ |
| `test_evidence_lock_invariants.py`                 | ~6    | §3.1, §9.1, §9.3                                  |
| `test_evidence_integrity_check_chain.py`           | ~6    | §3.2, §9.1, §9.6                                  |
| `test_anchor_batch_fsm.py`                         | ~8    | §6, §9.3, §9.6                                    |
| `test_anchor_saga_resumability.py`                 | ~4    | §8.1, §8.5                                        |
| `test_anchor_saga_dlq_replay.py`                   | ~3    | §8.4, §9.3                                        |
| `test_ctlog_internal_adapter.py`                   | ~4    | §7.1, §4 (merkle determinism)                     |
| `test_ots_v1_adapter.py` (network-skipped by default) | ~2 | §7.2                                              |
| `test_anchor_api_e2e.py`                           | ~4    | §10, full E2E flow                                |
| `test_evidence_no_registry_writes.py`              | 1     | §9.4 (static scan)                                |
| `test_contract_freeze.py` (refresh)                | refresh | drift gate green at 1.3.0                       |

**Total target: ~38 tests** (slightly over the 30 estimate to cover the integrity check chain and CT-log checkpointer separately).

---

## 12. Contract bump 1.2.0 → 1.3.0

Additive minor. New artifacts:

* **8 new request DTOs** frozen as independent schemas (replay, extend, trigger-check, etc.).
* **10 new response DTOs** frozen (anchor batch, lock, integrity check, inclusion proof bundle, checkpoint, etc.).
* **12 new domain events** (`evidence.lock.applied`, `evidence.lock.extended`, `evidence.integrity.check_started`, `evidence.integrity.passed`, `evidence.integrity.failed`, `evidence.integrity.check_errored`, `evidence.anchor.batched`, `evidence.anchor.submitted`, `evidence.anchor.confirmed`, `evidence.anchor.failed`, `evidence.anchor.replayed`, `evidence.ctlog.checkpoint_published`).
* **3 new PDP actions** + role matrix updates.
* **`evidence.lock`, `evidence.integrity_check`, `evidence.anchor_batch`** field projections.
* SHA256 fingerprints refreshed. Drift gate re-greened at 1.3.0.

---

## 13. Out of scope (deferred to later phases)

* Legal Hold aggregate (Phase 3.7 — bundled with timeline + custody).
* Retention sweeper (Phase 3.7).
* Court export bundle + offline verifier (Phase 3.10 — depends on this phase's checkpoints).
* SDK regeneration + React UI (Phase 3.9).
* Public verification endpoints (Phase 5).

---

## 14. References

* `PHASE3_SPEC.md §3.6` (updated alongside this ADR)
* `PHASE3_BLUEPRINT.md §2.3` (`AnchorPort`), `§2.4` (`CheckpointPublisherPort`) — updated alongside this ADR
* ADR-0005 — Merkle anchor saga (this ADR supersedes 0005's saga-state-machine sketch)
* ADR-0006 — Legal hold + remediation
* ADR-0007 — Canonical Evidence Aggregate + Sealing (the Seal aggregate this phase consumes)
* IETF RFC 6962 — Certificate Transparency (model for `ctlog_internal`)
* OpenTimestamps specification — model for `ots_v1`
* NIST FIPS 180-4 — SHA-256 (hash primitive)

---

## 15. Sign-off section — APPROVED 2026-06-29

> Phase 3.6 blueprint approved by operator with the five implementation
> decisions locked below. Implementation proceeds exactly per ADR-0008.

### Decision 1 — CheckpointPublisherPort (R2/IPFS)

* **Default**: disabled. The port must not couple the domain to any
  publishing destination.
* **Dev**: local-filesystem checkpoint exporter (writes signed tree
  heads under `${EVIDENCE_CHECKPOINT_DIR}`).
* **Production**: operator-configurable adapter(s). Supported targets:
  R2 Public bucket, IPFS pin, or both simultaneously (fan-out).
* **Binding rule**: the core domain depends only on the
  `CheckpointPublisherPort` Protocol. Adding a destination is purely
  additive — new adapter file, new env, no domain change.

### Decision 2 — OpenTimestamps calendars + quorum

* **Default calendar list** (env: `EVIDENCE_OTS_CALENDARS`):
  `btc.calendar.opentimestamps.org`,
  `alice.btc.calendar.opentimestamps.org`,
  `finney.calendar.eternitywall.com`.
* **Quorum**: configurable via `EVIDENCE_OTS_CALENDAR_QUORUM` (default
  **2 of N**). Confirmation requires `quorum` calendars to upgrade
  the proof to a Bitcoin merkle path.
* **Single-calendar failure does NOT fail the saga.** The adapter
  records per-calendar attempts; the saga advances to `confirmed` as
  soon as the quorum is met, leaves remaining calendars polling in
  the background for full coverage but does not block.
* OTS remains a pure `AnchorPort` adapter — calendar list and quorum
  are configuration, never code.

### Decision 3 — Saga cadence

* **Batch creation**: every **60s** (env:
  `EVIDENCE_ANCHOR_BATCHER_INTERVAL_SECONDS=60`).
* **Confirmation retry backoff**: `[10s, 60s, 5min, 1h, 6h, 24h]`
  (env: `EVIDENCE_ANCHOR_BACKOFF_SECONDS`, comma-separated).
* **Max retry window**: capped at **24h per attempt** thereafter.
* **Max attempts**: 12 (env: `EVIDENCE_ANCHOR_MAX_ATTEMPTS`). On
  exhaustion → `dead_letter` (terminal). Replay remains fully
  supported via super_admin endpoint.
* All cadences configurable; defaults shipped in `.env.example`.

### Decision 4 — Integrity verification cadence + mandatory triggers

* **Scheduled baseline**: every **30 days** per sealed evidence item
  (env: `EVIDENCE_INTEGRITY_CHECK_INTERVAL_DAYS=30`).
* **Mandatory additional triggers** (each fires an
  `EvidenceIntegrityCheck` with `triggered_by` set accordingly):
  * `pre_certificate` — before any legal certificate generation
    (Phase 6 consumer).
  * `pre_public_verification` — before public verifier publishes a
    record (Phase 5 consumer).
  * `pre_ownership_transfer` — emitted before the Registry's
    `RecordOwnershipTransfer` command (subscriber on
    `registry.ownership.transfer.requested` once Phase 4 lands).
  * `pre_subdivision` — before parent → child LandVault split
    (Phase 4 inheritance template consumer).
  * `post_storage_migration` — after any `MediaRemediationSaga`
    cutover (Phase 3.3 consumer).
  * `on_demand` — operator-triggered via
    `POST /api/v1/evidence/integrity-checks`.
  * `security_incident` — emitted by any subscriber on
    `evidence.signed_url.issued.v1` flagged anomalous or by external
    incident-management hook (operational, not domain).
* **`triggered_by` enum extended** to: `scheduled`, `on_demand`,
  `pre_seal`, `pre_certificate`, `pre_public_verification`,
  `pre_ownership_transfer`, `pre_subdivision`,
  `post_storage_migration`, `post_remediation`, `security_incident`.

### Decision 5 — Maximum Merkle batch size

* **Default**: **256 evidence items** per `AnchorBatch` (env:
  `EVIDENCE_ANCHOR_MAX_BATCH_SIZE=256`).
* **Automatic splitting**: when the batcher scoops > 256 eligible
  seals in a single sweep, it produces ⌈N/256⌉ batches in the same
  transaction. Each batch is independently submittable.
* **Deterministic ordering**: seals within a batch are sorted
  lexicographically by `seal_id` before Merkle construction; batches
  themselves are ordered by `created_at` + tiebreak on `batch_id`.
* **Merkle root determinism**: `compute_merkle_root` is set-equivalent
  on the input list, so root computation is independent of processing
  order.
* **Replay-safe + idempotent**: replay produces a new `batch_id` with
  the same `seal_ids` set → same `merkle_root`. Idempotency keys on
  the provider call prevent double-submission.

### Constitutional invariants (must NEVER be violated)

The implementation MUST continue to enforce, with named tests:

1. Evidence remains immutable after sealing.
2. Registry is never mutated by the Evidence context (static-scan test).
3. All cross-context communication occurs only through immutable domain events.
4. Anchor records are append-only (`evidence_anchor_batches` post-terminal is frozen; `evidence_anchor_attempts` and `evidence_ctlog_tree` insert-only).
5. Merkle roots are deterministic (set-equivalent test, NIST RFC 6234 vectors).
6. CT-log is the primary trust anchor (saga confirms on CT-log checkpoint inclusion; OTS upgrades arrive asynchronously).
7. OpenTimestamps is a secondary independent anchor (failure of OTS does NOT fail the saga; CT-log confirmation is sufficient for `confirmed`).
8. Replay is idempotent (replay of a confirmed/DLQ batch produces a new row with the same root; the original is never mutated).
9. DLQ is resumable (workers re-claim `submitted`/`confirming` rows whose `next_attempt_at` has passed, CAS on `state`).
10. Complete audit coverage (every FSM edge → one outbox event + one audit row; exhaustiveness test).
11. No binary data inside MongoDB documents (binaries live only behind StoragePort).
12. No PII leakage through checkpoints or anchor metadata (checkpoint and anchor payloads carry only `merkle_root` + `seal_id` + provider metadata — no evidence content, no owner names, no addresses; static-scan test on event payload schemas).

### Sequencing (binding)

Phase 3.6 → 3.7 → 3.8 → 3.9 → 3.10 → **Acceptance Review** → Phase 4.
Phase 4 implementation MUST NOT begin until Phase 3.10 passes its
formal Acceptance Review.

*Signed*: Operator, 2026-06-29 — ADR-0008 APPROVED.
