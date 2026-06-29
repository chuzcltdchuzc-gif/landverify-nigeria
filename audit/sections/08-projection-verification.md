# 08 · Projection Verification

> Cross-links: [07 Replay Verification](07-replay-verification.md) ·
> [03 ADR Compliance §ADR-0010](03-adr-compliance-matrix.md)

## 1. Registered projections (live)

| Name | Version | Event glob | Reset target collections |
| --- | --- | --- | --- |
| `evidence.timeline` | 1 | `evidence.*` | `evidence_timeline`, `evidence_custody` |

Future projections (Phase 4+) will register through the same engine.
Currently exactly **one** projection is wired.

## 2. Purity invariant — mechanical enforcement

`kernel/projections/__init__.py::assert_projection_purity()` runs at
**registration time** AND in dedicated tests. It scans the
projection's class source (`inspect.getsource(cls)`) for these
forbidden tokens:

```
"kernel.events.outbox.publish"
"await publish("
".save_seal("
".save_item("
".archive("
```

If any token appears, registration raises `InvariantError` and the
process refuses to boot. The check is intentionally a coarse
source-scan — it is the **fast feedback loop**, not the binding rule.
The binding rule is the ADR + test suite.

| Test | Verifies | Status |
| --- | --- | --- |
| `test_purity_accepts_pure_projection` | a clean projection passes. | ✅ |
| `test_purity_rejects_aggregate_mutation_token` | `.archive(` triggers `InvariantError`. | ✅ |
| `test_purity_rejects_publish_token` | `await publish(` triggers `InvariantError`. | ✅ |

## 3. Cursor + lag tracking

Every projection has a row in `kernel_projection_cursors`:

```jsonc
{
  "name": "evidence.timeline",
  "version": 1,
  "cursor_event_id": "evt_…",
  "last_delivered_at": "2026-06-29T13:47:03Z",
  "last_event_type": "evidence.seal.worm_applied",
  "delivered_count": 1675,
  "lag_events": 0,
  "rebuilding": false,
  "last_snapshot_at": null
}
```

The engine wraps each projection's `on_event` so the cursor advances
atomically with delivery. `lag_events` is computed against the
outbox (`COUNT(outbox WHERE status=DELIVERED AND event_glob match) -
delivered_count`).

## 4. Admin surface (super_admin only)

| Endpoint | Test |
| --- | --- |
| `GET /api/v1/admin/projections` | `test_admin_projections_list_super_admin` |
| `GET /api/v1/admin/projections/{name}` | `test_admin_projection_get_unknown_returns_404` |
| `POST /api/v1/admin/projections/{name}/replay` | `test_timeline_replay_is_byte_identical_end_to_end` |
| `POST /api/v1/admin/projections/{name}/snapshot` | `test_admin_projection_snapshot_records_timestamp` |

Authorization:

| Caller | Outcome | Test |
| --- | --- | --- |
| Anonymous | 401 | `test_admin_projections_requires_auth` |
| Authenticated non-super_admin | 403 | `test_admin_projections_denies_non_super_admin` |
| super_admin | 200 | `test_admin_projections_list_super_admin` |

The deny is produced by the `kernel.projections.admin` policy
registered in `kernel/projections/authorization.py` (priority 100, see
[§09 Security Review](09-security-review.md)).

## 5. SDK consumption

The TypeScript SDK exposes the four endpoints via
`ProjectionsAdminClient` (`frontend/src/sdk/projections.ts`). The
`ProjectionsAdmin.jsx` page consumes them through the SDK only.
Static check
`tests/test_sdk_consistency.py::test_sdk_covers_phase38_admin_projection_endpoints`
guarantees no admin endpoint can disappear from the SDK without the
gate firing.

## 6. Idempotency

Live deliveries during a replay are safe because the
projection-specific dedup key
(`evidence_id, seq`) lives in the timeline / custody adapter and
silently drops duplicate inserts (`upsert={"on": (eid, seq)}`). The
Phase 3.7 chain integrity test (`test_chain_invariants`) covers this
edge.

## 7. Verdict

The projection layer is provably:

- pure (purity invariant enforced),
- replayable (determinism gate, §07),
- inspectable (cursor / lag / snapshot UX),
- gated (super_admin-only mutations).

**Projection verification: PASS.**
