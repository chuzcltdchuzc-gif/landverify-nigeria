# 02 · Architecture Review

> Cross-links: [01 Executive Summary](01-executive-summary.md) ·
> [03 ADR Compliance](03-adr-compliance-matrix.md) ·
> [08 Projection Verification](08-projection-verification.md)

## 1. Layering

```
backend/
├── kernel/                       — Platform kernel; cross-cutting only
│   ├── audit/                    — Append-only audit log
│   ├── authorization/            — Centralised PEP + policy library
│   ├── errors/                   — Problem-detail factory
│   ├── events/                   — Envelope + Outbox + Publisher
│   ├── observability/            — Metrics
│   ├── persistence/              — ExecutionContext, txn helpers
│   ├── projections/              — Phase 3.8 engine + admin router
│   └── security/                 — JWT, keystore, RBAC seed
├── contexts/
│   ├── identity/                 — Phase 1 (auth, users, sessions)
│   ├── registry/                 — Phase 2 (landvault aggregates)
│   └── evidence/                 — Phases 3.1–3.9 (this audit)
│       ├── domain/               — Pure aggregates + invariants
│       ├── application/          — Services / sagas / projectors
│       ├── adapters/             — Mongo, WORM, OTS, CT-log, KMS
│       └── api/                  — FastAPI routers (thin)
├── routers/                      — Legacy compatibility proxies
└── tests/                        — 147 strict DDD tests
```

The dependency rule is enforced by import discipline: `domain/` imports
nothing from `adapters/` or `api/`. `application/` orchestrates
`domain/` through repository ports. `adapters/` provide concrete
ports. `api/` is the only inbound HTTP surface.

## 2. Aggregates owned by the Evidence context

| Aggregate file | Responsibility |
| --- | --- |
| `evidence_item.py` | The single immutable evidence aggregate (upload → verify → archive_replaced). Owns composite hash, parts metadata, status FSM. |
| `seal.py` | Group-of-evidence merkle seal. WORM-applied is terminal. |
| `anchor_batch.py` | Batched seals submitted to external OTS + internal CT-log. |
| `integrity_check.py` | Single integrity probe result (PASSED / FAILED / ERRORED). |
| `evidence_lock.py` | Retention lock holding an item out of any deletion path. |
| `timeline.py` | Two append-only chained logs: timeline entry + custody entry. |
| `invariants.py` | Cross-aggregate constraints centralised in pure functions. |
| `chain.py` | The chain-hash primitive (`compute_entry_hash`) reused by timeline + custody. |
| `events.py` | Domain event constructors (43 events). |
| `value_objects.py` | Frozen VOs (`Sha256Hex`, `ObjectKey`, `MerkleRoot`, …). |

## 3. Data path — write side

```
HTTP POST /api/v1/evidence/items
        ↓ (api/evidence_router)
EvidenceUploadService.initiate                       ← application/
        ↓ uses repo port
EvidenceItem.create  (domain/)                       ← invariants asserted here
        ↓ repo.save
Mongo `evidence_items` collection
        ↓ same DB session (txn)
publish(EvidenceUploaded)                            ← kernel/events/outbox
        ↓
kernel_outbox row (status=PENDING)
        ↓ background publisher
subscribers in-process (Projection Engine wrapper)
        ↓
TimelineProjector.on_event                           ← contexts/evidence/application
        ↓ from_event(…) — deterministic
evidence_timeline + evidence_custody  (read-side)
```

Two binding properties hold by construction:
- The aggregate save AND the outbox enqueue run in the **same Mongo
  transaction** (replica-set `rs0`). Either both commit or neither.
- The projector calls `TimelineEntry.from_event` /
  `CustodyEntry.from_event` (Phase 3.8), which derive `timeline_id`
  and `occurred_at` deterministically — guaranteeing byte-identical
  replay (proven in [§07](07-replay-verification.md)).

## 4. Data path — read side

```
HTTP GET /api/v1/evidence/items/{id}/timeline
        ↓
TimelineQueryService.get_chain                       ← application/
        ↓ ONLY this projection collection
evidence_timeline.find({...}).sort(seq, 1)
```

Read endpoints **never** join across aggregates and **never** call any
write-side service. This is enforced by the Projection Purity
invariant (ADR-0010 §1, see [§08](08-projection-verification.md)).

## 5. External boundaries

| Boundary | Adapter | Production binding |
| --- | --- | --- |
| WORM storage | `adapters/fs_worm_storage.py` (local) + `adapters/r2_storage.py` (Cloudflare R2) | R2 in prod; local-fs in tests. WORM enforced via `Object Lock`. |
| Time-stamp authority | `adapters/ots_v1.py` | OpenTimestamps — free public protocol. |
| Internal CT-log | `adapters/ctlog_internal.py` | Append-only Merkle log signed by platform KMS key. |
| KMS | `kernel/security/keys.py` + PyNaCl | Software KMS today; switch is a single ADR away. |
| Identity | `contexts/identity/*` | JWT (asymmetric) issued by platform; refresh via http-only cookie. |
| Frontend | `frontend/src/sdk/*` | Hand-derived TS SDK pinned to v1.5.0; zero direct REST in pages. |

## 6. Cross-cutting kernel modules

- **Authorization (PEP)** — every router endpoint goes through
  `await enforce(action, resource=…)`. The policy library is
  centralised; the Projection admin gate (`kernel.projections.admin`)
  was added in Phase 3.8.
- **Outbox** — `kernel/events/outbox.py` is the durable event ledger.
  Unique index on `event_id`. Compound index on
  `(status, occurred_at)`. Indexes are recreated on every boot
  (`ensure_indexes` is idempotent).
- **Audit log** — every state-mutating action emits an `audit_log` row
  with actor, correlation_id, and aggregate ref. Never edited.
- **Problem-detail errors** — `kernel/errors/problem.py` produces
  RFC-7807 responses with `code`, `correlation_id`, machine-readable
  detail.

## 7. What the architecture **prohibits**

- Reading aggregates from projections.
- Writing aggregates from read models.
- Calling external services from inside a domain method.
- Direct collection access outside an adapter.
- HTTP routers carrying business rules (routers are thin).
- The React app talking to anything except its SDK.

These prohibitions are mechanically tested — see
[§04](04-domain-invariant-inventory.md) and the static checks in
`tests/test_sdk_consistency.py`.

## 8. Conclusion

The Evidence context is a textbook hexagonal / DDD implementation
with disciplined CQRS. The projection engine collapsed the remaining
read-side ambiguity (Phase 3.8) and the SDK + UI sealed the consumer
boundary (Phase 3.9). The architecture is ready for production.
