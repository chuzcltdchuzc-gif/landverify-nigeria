# 14 · Test Coverage Report

> Cross-links: [03 ADR Compliance](03-adr-compliance-matrix.md) ·
> [04 Domain Invariants](04-domain-invariant-inventory.md)

## 1. Strict Constitutional DDD Suite — 147 / 147 PASSING

| Suite file | Test count | Phase / context | Status |
| --- | ---: | --- | --- |
| `tests/test_phase1_identity.py` | 22 | Phase 1 — Identity | ✅ |
| `tests/test_registry_aggregate_invariants.py` | 11 | Phase 2 — Registry | ✅ |
| `tests/test_evidence_aggregate_invariants.py` | 13 | Phase 3.4–3.5 — Evidence aggregate | ✅ |
| `tests/test_evidence_storage_foundation.py` | 9 | Phase 3.1 — Storage / PII | ✅ |
| `tests/test_phase36_aggregates.py` | 23 | Phase 3.6 — Anchoring + Integrity + Locks | ✅ |
| `tests/test_phase37_timeline.py` | 18 | Phase 3.7 — Timeline + Custody + Legal Hold + Supersession | ✅ |
| `tests/test_phase38_projections.py` | 17 | Phase 3.8 — Projection Engine + Replay | ✅ |
| `tests/test_contract_freeze.py` | 8 | Contract drift gate | ✅ |
| `tests/test_sdk_consistency.py` | 7 | Phase 3.9 — SDK zero-drift | ✅ |
| Other Evidence integration tests | 19 | mixed (e.g. `test_phase36_e2e`, `test_evidence_e2e`) | ✅ |

**Total: 147 strict DDD tests · 100 % green.**

(The wider repo also has ~50 legacy integration tests under
`backend/tests/backend_test.py`, `test_concurrency.py`,
`test_tenant_isolation.py`, `test_worker_reports.py` that exercise
the **legacy** `/api/parcels` demo path. These are out of scope for
the constitutional Evidence acceptance and are explicitly excluded.)

## 2. Coverage by ADR

| ADR | Tests dedicated |
| --- | ---: |
| 0001 (Contract Freeze) | 8 |
| 0002 (Registry) | 11 |
| 0003 (Bounded Context) | 6 |
| 0004 (Server-side Hashing) | 4 |
| 0005 (Merkle Anchor) | 9 |
| 0006 (Legal Hold + Remediation) | 6 |
| 0007 (Evidence Aggregate + Sealing) | 13 |
| 0008 (Anchoring + Integrity Saga) | 14 |
| 0009 (Timeline + Custody + Legal Hold + Supersession) | 18 |
| 0010 (Projection Engine + Read Models) | 17 + 7 = 24 |

Every ADR has both positive AND negative-path tests (a `permit` case
and at least one `deny` / `InvariantViolation` case).

## 3. Coverage by invariant family

See [§04 Domain Invariant Inventory](04-domain-invariant-inventory.md)
for the per-invariant test map.

## 4. Latest testing agent runs

| Iteration | Phase under test | Backend | Frontend | Outcome |
| --- | --- | --- | --- | --- |
| 5 | Phase 3.8 acceptance | 100 % | n/a | ✅ |
| 6 | Phase 3.9 acceptance | 100 % | 100 % | ✅ |

Both reports live in `/app/test_reports/iteration_{5,6}.json`.

## 5. Pre-existing legacy failures — explicitly out of scope

The following test files target the legacy `/api/parcels` demo path
and are NOT part of the constitutional Evidence surface:

- `tests/backend_test.py::test_insufficient_credits_returns_402`
- `tests/test_concurrency.py`
- `tests/test_tenant_isolation.py`
- `tests/test_worker_reports.py`

They were failing prior to Phase 3.8 (verified by `git stash` +
re-run). They are documented in [§16](16-deferred-backlog.md) as
deferred cleanup, not as regressions.

## 6. Conclusion

The constitutional DDD test suite is **100 % green** at v1.5.0 with
147 binding tests. Coverage is broad (every ADR + every invariant
family) and deep (positive + negative paths). **Test coverage: PASS.**
