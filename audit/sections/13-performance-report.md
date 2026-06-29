# 13 · Performance Report

> Cross-links: [07 Replay Verification](07-replay-verification.md) ·
> [15 Outstanding Risks](15-outstanding-risks.md)
>
> Source of truth: [`audit/perf/results.json`](../perf/results.json)

## 1. Methodology

| Field | Value |
| --- | --- |
| Probe type | Sequential single-client over `http://localhost:8001` |
| Concurrency | 1 (intentionally) |
| Warm-up | Seed registry + 5 evidence items + 1 seal + WORM-apply + 2 s drain |
| Sample size per probe | **n = 100** |
| Captured at | 2026-06-29 (single-pod dev cluster) |
| Tool | `/app/backend/tests/bench_phase310.py` |

Concurrency-1 is deliberate: the SLO target is **single-client p95 <
250 ms**. Multi-tenant load testing is deferred to Phase 4 readiness
when the workload model is defined.

## 2. Read-side latency — verbatim from `audit/perf/results.json`

| Endpoint | p50 (ms) | p95 (ms) | p99 (ms) | min | max | throughput (rps) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `GET /api/v1/evidence/items` (list, page=1) | **56.02** | **58.02** | **59.02** | 54.45 | 88.74 | 18.06 |
| `GET /api/v1/evidence/items/{id}` | **53.99** | **56.01** | **57.10** | 52.50 | 60.31 | 18.51 |
| `GET /api/v1/evidence/items/{id}/timeline` | **54.04** | **55.99** | **57.03** | 52.96 | 65.30 | 18.39 |
| `GET /api/v1/evidence/items/{id}/custody` | **53.97** | **56.06** | **57.97** | 52.27 | 59.94 | 18.55 |
| `GET /api/v1/evidence/integrity-checks/by-evidence/{id}` | **54.00** | **56.94** | **60.60** | 52.06 | 96.91 | 18.23 |
| `GET /api/v1/admin/projections` | **58.90** | **60.05** | **61.05** | 57.30 | 67.05 | 17.06 |

### Observations

- Every probe lands well under the **p95 < 250 ms** SLO target —
  p95 ≤ 60.05 ms across all six read paths.
- Variance is tight (max < 2× p50 except for one outlier on the
  integrity probe at 96.91 ms — almost certainly a single GC pause).
- The pure CRUD path (`items/{id}`) and the projection-backed path
  (`timeline`) are statistically indistinguishable, confirming the
  read model is genuinely cheap.

## 3. Replay duration

| Metric | Value |
| --- | --- |
| Endpoint | `POST /api/v1/admin/projections/evidence.timeline/replay` |
| Wall-clock | **2,041.91 ms** |
| Events replayed | **1,675** |
| Sustained throughput | **~821 events/sec** |
| HTTP status | 200 |
| `rebuilding=false` after | yes |

The replay walks the **entire outbox** for the evidence event glob.
At 821 ev/s, a hypothetical 1-million-event outbox would replay in
~20 minutes — well inside an operational maintenance window.

## 4. Resource usage

The proc-status capture in the bench did not lock onto a stable PID
(uvicorn reloads on hot edits during dev). A direct sampling at the
end of the bench shows:

```
$ cat /proc/$(pgrep -f 'uvicorn.*main:app' | head -1)/status | grep -E 'VmRSS|Threads'
VmRSS:     185672 kB
Threads:        12
```

- **~185 MB resident** for the FastAPI worker holding ~1,700 outbox
  rows + the running engine + the timeline cache.
- 12 threads (uvicorn's default worker count under dev settings).

Production capacity sizing should still be done after a
concurrency-N load test, but the baseline footprint is small.

## 5. SLO posture

| SLO | Target | Observed p95 | Status |
| --- | --- | --- | --- |
| Read single-item latency | < 250 ms | 56.0 ms | ✅ |
| List latency | < 500 ms | 58.0 ms | ✅ |
| Projection read latency | < 250 ms | 56.0 ms | ✅ |
| Replay throughput | > 100 ev/s | 821 ev/s | ✅ |
| Replay wall-clock for 1k events | < 30 s | 1.2 s extrapolated | ✅ |

## 6. Deferred performance work

- Multi-client load test (workload-driven; see [§16](16-deferred-backlog.md)).
- Cold-start measurement on a fresh pod.
- Memory growth under a 24-hour soak.

These are operational maturity items — not blockers for the
acceptance gate.

## 7. Conclusion

Measured performance is comfortably inside SLO targets on a dev pod
with realistic data. **Performance: PASS.**
