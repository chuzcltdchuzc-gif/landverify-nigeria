# ADR-0010 — Projection Engine, Read Models & Replay (Phase 3.8)

* **Status:** Accepted
* **Contract version introduced:** `1.5.0` (additive minor — see CHANGELOG.md)
* **Authoring phase:** Phase 3.8 — Read Models, Projection Engine, Replay
* **Constitutional Delivery rule:** zero business logic in projections;
  full delete + replay MUST produce byte-identical state.

## Context

The Evidence bounded context now emits a rich event stream (Phases 3.4
through 3.7) covering uploads, hashing, sealing, locking, anchoring,
integrity, timeline, custody, legal-hold, supersession. Several read
surfaces have been built directly off these events (e.g. the
`evidence_timeline` and `evidence_custody` collections, populated by
`TimelineProjector`).

These read models are convenient query stores, but they are NOT a
source of truth. The transactional outbox (`kernel_outbox`) is the
authoritative event ledger; read models exist solely to answer queries
quickly. Without a formal projection engine the platform suffers two
hazards:

1. **Drift** — handlers that quietly mutate aggregates, publish
   commands, or embed business rules turn projections into a parallel
   source of truth.
2. **Opaque health** — operators have no way to inspect cursor
   position, lag, or trigger a deterministic rebuild after a bug fix
   or schema change.

ADR-0010 introduces the binding rules and an in-process Projection
Engine that mechanically enforces them.

## Decision

### 1. Constitutional rules for projections

Every projection registered on the platform MUST satisfy ALL of the
following:

* **No business logic.** A projection contains pure event-to-row
  mapping. It MUST NOT branch on aggregate state, compute new business
  invariants, evaluate authorization, or apply retention policy.
* **No mutation of aggregates.** Projections MUST NEVER call any
  aggregate repository's `save` / `update` / `release` / `archive`
  method. They are READ-side citizens.
* **No command publishing.** Projections MUST NEVER call
  `kernel.events.outbox.publish` or any service that does so. The
  event stream is one-way INTO projections.
* **Idempotent on_event.** Re-delivering the same envelope MUST be
  safe. Adapter-level dedup keys (`evidence_id, seq`) provide this
  guarantee for chain-style projections.
* **Disposable.** Each projection MUST implement `reset()` that
  removes every row it owns. After `reset()` + replay over the outbox
  in `occurred_at` order, the final state MUST be byte-identical to
  the pre-reset state (the **Projection Determinism Gate**).

These rules are mechanically asserted by
`tests/test_phase38_projections.py::test_projection_purity_invariant`.

### 2. The Projection Engine

A new module `kernel.projections` ships with:

* `Projection` (Protocol) — interface every projection implements:
  `name`, `version`, `event_glob`, `async on_event(env)`, `async reset()`.
* `ProjectionEngine` — owns cursor tracking
  (`kernel_projection_cursors` collection), health/lag metrics,
  snapshot timestamps, and the replay command.
* `ProjectionStatus` — dataclass exposing
  `{name, version, cursor_event_id, last_delivered_at,
    last_event_type, delivered_count, lag_events, rebuilding,
    last_snapshot_at}`.

The engine wraps each projection's `on_event` in a cursor-tracking
handler so existing outbox subscriptions become one-liners. Cursor
state is persisted, so engine restarts retain accurate lag
measurements.

### 3. Replay engine

`ProjectionEngine.replay(name)` performs a disposable rebuild:

1. Marks the cursor `rebuilding=true`.
2. Calls `projection.reset()` to delete every row the projection
   owns.
3. Resets the persisted cursor counters.
4. Walks the outbox in `occurred_at` order (filtered by
   `event_glob`, status `DELIVERED`) and invokes `on_event` for each
   matching envelope.
5. Restores cursor + counters + last-event metadata.

Because projections are pure event-to-row, the post-replay state
matches the pre-replay state byte-for-byte. This is the binding
acceptance gate for Phase 3.8.

### 4. Snapshot support

`ProjectionEngine.snapshot(name)` records a snapshot timestamp on the
cursor row. Durable snapshots (when needed) are owned by individual
projections — they collapse their own rows into a snapshot table when
size dictates. The engine never touches a projection's rows; it just
records a recovery baseline.

### 5. Admin surface

New endpoints, ALL gated by `kernel.projections.admin` (super_admin
only):

* `GET  /api/v1/admin/projections`            — health for every projection.
* `GET  /api/v1/admin/projections/{name}`     — single projection status.
* `POST /api/v1/admin/projections/{name}/replay`   — trigger replay.
* `POST /api/v1/admin/projections/{name}/snapshot` — record snapshot.

These are the only new public endpoints in 1.5.0.

### 6. Existing projections

* `evidence.timeline` (was `TimelineProjector`) — formal Projection
  implementation. `version=1`, `event_glob="evidence.*"`. `reset()`
  deletes from `evidence_timeline` + `evidence_custody`. The existing
  domain idempotency (`(evidence_id, seq)` adapter dedup) is unchanged.

## Consequences

* Read-side and write-side become formally separated; the read side
  is provably rebuildable from the durable event ledger.
* Operators gain inspectable projection health + a single replay
  command. Schema migrations on a read store become deterministic.
* A projection that smuggles business logic is now an invariant
  violation in CI rather than a latent design defect.
* SDK consumers gain no surface changes outside of the four new
  admin endpoints (no impact on the v1 client surface; the SDK
  regenerates anyway in Phase 3.9).

## Alternatives considered

* **Event-sourcing the aggregates themselves** — rejected. The
  aggregates already enforce invariants on write; rebuilding them
  from events would require materialising a full history per
  aggregate, doubling the storage cost without solving the read-side
  drift problem.
* **External read-store (e.g. Elasticsearch)** — out of scope for
  Phase 3. ADR-0010 keeps everything in MongoDB; the engine is
  storage-agnostic and a future ADR may add a non-Mongo read store
  without changing this contract.
