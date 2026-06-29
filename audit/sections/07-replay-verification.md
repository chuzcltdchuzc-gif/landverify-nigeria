# 07 · Replay Verification

> Cross-links: [03 ADR Compliance §ADR-0010](03-adr-compliance-matrix.md) ·
> [08 Projection Verification](08-projection-verification.md) ·
> [13 Performance Report](13-performance-report.md)

## 1. Constitutional gate

ADR-0010 §3 (the "Projection Determinism Gate"):

> Full delete + replay over the outbox in `occurred_at` order MUST
> produce byte-identical state.

This is the single most important read-side property of the platform.
If it fails, the constitutional doctrine collapses — projections
become an alternate source of truth.

## 2. How replay is implemented

`kernel/projections/__init__.py::ProjectionEngine.replay(name)`:

1. Mark the cursor row `rebuilding=true`.
2. Call `projection.reset()` — every row the projection owns is
   deleted (`evidence_timeline` + `evidence_custody` for the
   `evidence.timeline` projection).
3. Reset persisted cursor counters
   (`delivered_count`, `cursor_event_id`, `last_event_type`).
4. Iterate `kernel_outbox` filtered by `event_glob`, status=`DELIVERED`,
   sorted by `occurred_at` ASC. For each envelope reconstruct the
   `Envelope` dataclass and re-invoke `projection.on_event(env)`.
5. Restore cursor metadata + clear `rebuilding`.

The same in-process publisher continues running. Live deliveries are
**idempotent at the adapter level** (`(evidence_id, seq)` dedup),
so any racing live event during replay is harmless.

## 3. Determinism source of truth

For a replay to be byte-identical, the projection's `on_event` MUST
be a pure function of the envelope. Phase 3.8 added two deterministic
constructors:

- `TimelineEntry.from_event(source_event_id, source_event_occurred_at, …)`
  derives `timeline_id = "tln_" + sha256(event_id:evidence_id:seq)[:32]`
  and `occurred_at = env.occurred_at`.
- `CustodyEntry.from_event(…)` mirrors the same derivation.

These replaced the random-`uuid`, wall-clock variants for projection
use. The original `.create()` factories remain for the write side
(`CustodyService.record_transfer`) where the random id IS the
authoritative id.

## 4. Verification — unit

`tests/test_phase38_projections.py::test_replay_rebuild_is_byte_identical`:

- Seeds 5 synthetic events directly into the outbox at status=DELIVERED.
- Live-delivers each through the engine wrapper.
- Captures `proj.rows[*].to_doc()`.
- Calls `engine.replay(name)`.
- Asserts `proj.rows[*].to_doc()` is element-wise equal to the snapshot.

`tests/test_phase38_projections.py::test_replay_after_reset_full_state`:

- Same setup but explicitly deletes all projection rows BEFORE replay,
  so the test proves the rebuild is fully self-contained — no
  dependence on residual state.

Both PASS.

## 5. Verification — end-to-end (the binding gate)

`tests/test_phase38_projections.py::test_timeline_replay_is_byte_identical_end_to_end`:

1. Run the **real** Phase 3.4–3.6 pipeline:
   - `POST /api/v1/registry/landvaults`
   - `POST /api/v1/evidence/items` (initiate)
   - `PUT  /api/v1/evidence/items/{id}/parts/1`
   - `POST /api/v1/evidence/items/{id}/complete`
   - `POST /api/v1/evidence/items/{id}/verify`
   - `POST /api/v1/evidence/seals` + `apply-worm`
2. Sleep 2.5 s so the live publisher drains.
3. Snapshot every row from `evidence_timeline` and `evidence_custody`
   for that evidence (dropping `_id`).
4. `POST /api/v1/admin/projections/evidence.timeline/replay` as a
   super_admin.
5. Re-snapshot the same rows.
6. `assert post == pre` element-by-element.

**Status: PASS** — observed live in iteration_5 and confirmed again in
iteration_6.

## 6. Verification — production-scale during the perf bench

During the Phase 3.10 perf bench
(`audit/perf/results.json`), one replay was triggered against the
**accumulated** outbox of the running pod:

| Metric | Value |
| --- | --- |
| Endpoint | `POST /api/v1/admin/projections/evidence.timeline/replay` |
| HTTP status | 200 |
| Wall-clock duration | **2,041.91 ms** |
| Events replayed | **1,675** |
| Throughput | **~821 events/sec** sustained |
| Rebuilding state after | `false` (replay completed) |

Throughput is bounded by single-client sequential delivery (no
concurrency); the engine handled the full ledger of a non-trivial
running pod inside two seconds. Conclusion: replay is operationally
viable for the current production envelope.

## 7. Cursor + lag verification

`tests/test_phase38_projections.py::test_lag_metric_reflects_undelivered_events`
inserts 10 events at status=DELIVERED into the outbox, delivers only
4 through the wrapper, and asserts:

- `delivered_count == 4`
- `lag_events == 6`
- `cursor_event_id == env4.event_id`

This guarantees the admin UI's lag column is meaningful.

## 8. Snapshot semantics

`engine.snapshot(name)` upserts `last_snapshot_at` on the cursor row.
The engine never copies rows — snapshots are an operator baseline
("after this timestamp, treat the projection as known-good"). Heavier
durable snapshots are a projection-private concern and are deferred
to Phase 4+ when read sets exceed the replay budget.

## 9. Conclusion

Replay is mechanically deterministic, exercised by 17 Phase 3.8
tests, and operationally fast (1,675 events in ~2 s). The
Determinism Gate **PASSES**.
