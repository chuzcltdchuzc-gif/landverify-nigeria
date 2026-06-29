# 17 · Production Readiness Assessment

> Cross-links: every prior section. This is the **operator-facing**
> verdict synthesizing §02 through §16.

The verdict at the bottom is a **recommendation**. Final authorization
is the operator's exclusive constitutional right.

---

## 1. Facts (strictly evidence-based)

| Category | Fact | Source |
| --- | --- | --- |
| Architecture | Strict hexagonal / DDD with one outbound boundary per adapter. | §02 |
| Contracts | v1.5.0 frozen, 98 artifacts, drift gate green (8 tests). | §06 |
| SDK | TypeScript SDK pinned to v1.5.0 with 7-test consistency gate. | §06 |
| ADR compliance | 10 / 10 ADRs PASS every binding rule. | §03 |
| Invariants | 50 mechanically-enforced invariants in the Evidence domain. | §04 |
| Events | 43 events in catalog (27 Evidence). | §05 |
| Tests | 147 / 147 strict DDD tests green. | §14 |
| Replay determinism | Byte-identical replay proven end-to-end (1,675 events in 2 s). | §07 |
| Projection purity | Static + runtime enforcement; super_admin-gated admin surface. | §08 |
| Security | JWT + RBAC + tenant scoping + audit log + WORM enforcement. | §09 |
| WORM | Both domain and storage layers enforce one-shot lock. | §10 |
| Anchoring | Dual proof: public OTS + internal CT-log; idempotent saga. | §11 |
| Legal Hold | Append-only, gated, release-immutable. | §12 |
| Performance | p95 ≤ 60 ms across all read paths; replay 821 ev/s. | §13 |
| UI | Phase 3.9 React surface consumes SDK exclusively; WCAG 2.2 AA. | §14 |
| Pre-existing legacy failures | 4 (in `/api/parcels` demo path). | §14 |

## 2. Gaps (mapped to risks + backlog)

| ID | Gap | Severity | Plan |
| --- | --- | --- | --- |
| R-1 | CI must keep the drift gate enabled. | Low | Document. |
| R-2 | Browser CSP not yet hardened. | **Medium** | 2-day fix before public launch. |
| R-3 | OTS adapter runs dry-run in dev. | Low | Configuration only — set env var. |
| R-4 | CT-log key in software KMS. | Medium | Phase 4+ infra. |
| R-5 | Multi-client load profile unmeasured. | Low | Operational. |
| R-6 | Legacy demo test failures. | Low | Excise the demo path. |

## 3. Security Review (summary)

See [§09](09-security-review.md) for the full review. Key points:

- ✅ Authentication: JWT + refresh-cookie + bcrypt + JWKS.
- ✅ Authorization: centralised PEP, super_admin-only projection admin.
- ✅ Audit: append-only `audit_log`; no edit / delete paths.
- ✅ Crypto: SHA-256 for content, Ed25519 for CT-log, RS256 for JWT.
- ✅ Tenant isolation: enforced at the repository layer.
- ⚠ CSP hardening pending (R-2).
- ⚠ Hardware KMS migration pending (R-4).

## 4. Compliance Review (summary)

The Evidence context delivers the substrate for compliance regimes
that require **provenance**, **integrity**, **non-repudiation**, and
**retention**:

| Compliance demand | How it's delivered | Status |
| --- | --- | --- |
| Tamper-evident storage | WORM lock + integrity checks + chained timeline. | ✅ |
| Provable timestamp | OTS + internal CT-log (dual proof). | ✅ |
| Chain of custody | Append-only `evidence_custody` with `prev_hash`. | ✅ |
| Legal hold | First-class aggregate; blocks supersession + deletion. | ✅ |
| Audit trail | Kernel `audit_log` + per-aggregate event stream. | ✅ |
| Replayable verification | Projection determinism gate (§07). | ✅ |
| Data minimisation | PII encrypted; only opaque ids in events. | ✅ (Phase 3.1) |
| Right to erasure (where applicable) | Supersession (`ARCHIVED_REPLACED`) without hidden state. | ✅ |
| Retention policy | EvidenceLock with forward-only extension. | ✅ |

GDPR / equivalent national equivalents (NDPR, DPA-2018 KE) are
**substantively** satisfied. The remaining concern is **lawful basis
recording** for non-evidence personal data, which lives in the
Identity context and is unchanged by Phase 3.

## 5. Operational Readiness

| Area | Ready? | Notes |
| --- | --- | --- |
| Deployment manifest | ✅ | Single-pod FastAPI + Mongo replica set rs0. |
| Hot reload safe | ✅ | Verified by Phase 3 development. |
| Observability | ⚠ | Kernel metrics module exists, but external scrape (Prometheus) not wired. Backlog D-9. |
| Logs | ✅ | Structured logging via `logger.info(...)`. |
| Runbook | ⚠ | Implicit in ADRs + tests; explicit `RUNBOOK.md` deferred (D-10). |
| Replay procedure | ✅ | One-click via admin UI. |
| Rollback | ✅ | Append-only model means rolling back code does not corrupt data; replay rebuilds projections. |

## 6. Recommended verdict

**GO — production deployment of the Evidence bounded context is
recommended, conditional on:**

1. **R-2 (CSP hardening) is scheduled and lands within the first
   production release window.**
2. **R-3 (OTS production-mode flag) is set in the production env
   manifest at launch.**
3. **An operator runbook (D-10) is written, even in skeleton form,
   covering the four critical procedures: replay, legal hold,
   retention extension, and JWT key roll.**

Every other risk is either Low severity, fully mitigated by the
deferred backlog, or operational rather than constitutional.

**Phase 4 (Workflow / Consent / Inheritance) remains CONSTITUTIONALLY
PROHIBITED until the operator explicitly approves this Acceptance
Review.** No Phase 4 ADR, blueprint, or code may be written before
that approval.

---

## 7. Final authorization

| Role | Signature | Date |
| --- | --- | --- |
| Operator | ___________ | ___________ |
| Reviewer (E1, autonomous) | electronically attested | 2026-06-29 |

The reviewer's attestation is **not** an authorization. It is a
fact-based recommendation. Phase 4 unlocks only when the operator
signs above.
