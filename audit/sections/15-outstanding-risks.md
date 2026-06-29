# 15 · Outstanding Risks

> Cross-links: [09 Security Review](09-security-review.md) ·
> [16 Deferred Backlog](16-deferred-backlog.md) ·
> [17 Production Readiness](17-production-readiness.md)

Risks are tracked even when residual; severity is operator-facing.

## R-1 · Contract drift gate must remain enabled in CI · LOW

| Field | Detail |
| --- | --- |
| Source | ADR-0001 |
| Impact | If `test_contract_freeze.py` is disabled, a contract regen mismatch could ship undetected. |
| Likelihood | Low — gate is a hard-fail in the pytest run that every commit triggers. |
| Mitigation | Document in CI handbook that the freeze test cannot be skipped. Add a meta-test that asserts the gate is part of the strict run. |
| Owner | Platform / DevOps |
| Status | Tracked. Recommend addition of a CI-config assertion before public launch. |

## R-2 · Browser-side CSP not yet hardened · MEDIUM

| Field | Detail |
| --- | --- |
| Source | §09 Security Review |
| Impact | A malicious browser extension or XSS sink could intercept upload bytes before they reach the network. Server-side hashing still defeats tampering of the **stored** artifact, but a confidentiality breach is possible. |
| Likelihood | Medium for public-facing surfaces; low for hardened gov endpoints. |
| Mitigation | Ship `Content-Security-Policy` headers from the ingress + restrict frame-ancestors + require Trusted-Types. Two-day effort. |
| Owner | Frontend + DevOps |
| Status | Open. Schedule as a P1 follow-up before broad public rollout. |

## R-3 · OTS adapter currently runs in dry-run-fast mode in the dev cluster · LOW

| Field | Detail |
| --- | --- |
| Source | ADR-0005 |
| Impact | OTS proofs in dev are not network-submitted to the public TSA; production requires the network adapter mode. |
| Likelihood | Operational only — irrelevant unless dev artifacts are mistakenly treated as production. |
| Mitigation | Configuration flag `OTS_MODE=public` is environment-driven. Production manifest must set it. |
| Owner | DevOps |
| Status | Tracked. Confirm in production env-vars before launch. |

## R-4 · CT-log signing key in software KMS · MEDIUM

| Field | Detail |
| --- | --- |
| Source | §09 Security Review |
| Impact | A compromise of the pod's process memory could leak the Ed25519 private key used to sign internal CT-log checkpoints. Forensic value of the log would degrade. |
| Likelihood | Low (memory-scoped, no disk persistence outside encrypted env). |
| Mitigation | Migrate to hardware-backed KMS (AWS KMS / Cloud HSM). Designed as a single-adapter swap in `kernel/security/keys.py`. |
| Owner | Security + Platform |
| Status | Phase 4+ infra task. |

## R-5 · Multi-client load profile not yet measured · LOW

| Field | Detail |
| --- | --- |
| Source | §13 Performance Report |
| Impact | Sizing decisions for production replicas are based on single-client p95. Concurrency-N behaviour (lock contention on `kernel_outbox`, DB pool) is unmeasured. |
| Likelihood | Medium — Mongo write concurrency can surprise. |
| Mitigation | Schedule a 50-client, 5-minute load test using the existing seed harness. |
| Owner | Performance / DevOps |
| Status | Backlogged; not blocking acceptance. |

## R-6 · Legacy `/api/parcels` test failures · LOW

| Field | Detail |
| --- | --- |
| Source | §14 Test Coverage Report |
| Impact | The legacy demo path has 4 pre-existing failing tests. They predate Phase 3.0 and exercise a code path slated for removal. |
| Mitigation | Excise the legacy router in a follow-up sweep. |
| Owner | Maintainer |
| Status | Deferred per [§16](16-deferred-backlog.md). |

---

## Summary

| Severity | Open | Action expected before launch? |
| --- | ---: | --- |
| High | 0 | n/a |
| Medium | 2 (R-2, R-4) | R-2 yes (CSP), R-4 can be Phase 4+ infra |
| Low | 4 (R-1, R-3, R-5, R-6) | Operational; not blockers |

**No High-severity risk is open.** R-2 is the only one with a
launch-blocking flavour, and it is a 2-day fix.
