# Phase 4 — Security Model

> **Status:** DRAFT — part of the Phase 4 Blueprint Package.
> **Scope:** the security architecture for the Workflow bounded
> context. **Inherits and extends** the R-2 Security Readiness
> Report and the Phase 3 Security Review (§09 of the Acceptance Packet).
> **Authority:** ADR-0019 / 0020 / 0021 / 0022 and PHASE4_SPEC §6 / §9.8.

This document declares the security model that Phase 4 implementation
will be required to satisfy. It is **architecture only**.

---

## 1. Inheritance from Phase 3

Phase 4 inherits, unchanged:

- HTTP security headers (R-2 §1.1) — CSP L3, HSTS, COOP, COEP, CORP,
  Referrer-Policy, X-Content-Type-Options, X-Frame-Options,
  Permissions-Policy.
- Rate limiting middleware (R-2 §1.2) — additional buckets per §3 below.
- Authentication (JWT RS256 + refresh cookie + bcrypt + JWKS).
- Centralised PEP (`kernel/authorization/pep.py`) — every Phase 4
  command handler MUST call `await enforce(<action>, …)`.
- Audit log (`kernel/audit/*`) — append-only.
- Encryption inventory unchanged (SHA-256, Ed25519, RS256, AES-256-GCM).
- Tenant isolation enforced at the repository layer.
- Signed-URL TTL ≤ 600 s.
- WORM dual-layer enforcement (Phase 3.5).

None of the above is weakened.

## 2. New attack surfaces introduced by Phase 4

| Surface | Why it's new | Mitigation |
| --- | --- | --- |
| Workflow command endpoints (`/api/v1/workflow/*`) | Citizens / officials triggering state transitions. | PEP-gated per action; rate limits per role per path. |
| Consent witness slate | Witness identity is sensitive; impersonation must be impossible. | Witness must be authenticated via JWT; attestation is itself an Evidence item signed by the witness's KMS key. |
| Community attestation queue | Attestations may attract coercion. | PEP scoping; audit-log row per attestation with originating IP + actor id. |
| Inheritance court order ingestion | Court orders carry the highest legal weight. | Court orders are typed Evidence items; only `compliance_officer` may record; enumerated directive verbs only (no free text execution). |
| Saga composer DSL | A maliciously-authored `WorkflowDefinition` could trigger unbounded spawns. | DSL is content-frozen (loaded from `contracts/v1/workflow_definitions/`); load-time validator rejects cycles without guards (RB-5). |
| Timer queue | A misconfigured timer fires unwanted commands. | Timer service requires the originating workflow instance to be ACTIVE; orphaned timers drop silently. |

## 3. New rate-limit buckets

Extending `RATE_LIMITS` from R-2 §1.2:

| Path prefix | Limit | Window | Justification |
| --- | ---: | ---: | --- |
| `/api/v1/workflow/instances` (POST) | 30 | 60 s | citizens may file workflows; brute force attempted |
| `/api/v1/workflow/instances/{id}/commands` (POST) | 60 | 60 s | hot path during witness sessions |
| `/api/v1/workflow/admin/queues` (GET) | 60 | 60 s | dashboard polling |
| `/api/v1/consent/captures` (POST) | 20 | 60 s | upload-heavy; protect storage |
| `/api/v1/community/attestations` (POST) | 30 | 60 s | one attestation per actor per request; bursts blocked |
| `/api/v1/inheritance/cases` (POST) | 10 | 60 s | filing a case is non-trivial |
| `/api/v1/inheritance/court-orders` (POST) | 20 | 60 s | compliance_officer only |

Production manifest continues to require `RATE_LIMIT_ENABLED=1`.

## 4. Authorization matrix (consolidated)

The full PEP table lives in `PHASE4_SPEC §6`. Here is the
security-critical subset — the actions that, if mis-authorized,
have the largest legal blast radius:

| Action | Required role(s) | Bypass via super_admin? | Audit row required? |
| --- | --- | --- | --- |
| `workflow.start.inheritance.v1` | `compliance_officer`, identified `next_of_kin` | Yes (break-glass) | Yes |
| `consent.revoke` | the principal ONLY | **No** — even super_admin cannot revoke on someone's behalf | Yes |
| `community_validation.attest` | declared slate role only | Yes (break-glass) | Yes |
| `community_validation.attest as traditional_authority` | role `traditional_authority` only | **No** — traditional authority is identity-bound | Yes |
| `compliance_review.decide` | `compliance_officer` | Yes (audit row carries break-glass marker) | Yes |
| `surveyor_general_review.decide` | `surveyor_general` ONLY | **No** — this is the only role that may emit `registry.command.commit_parcel` | Yes |
| `court_order.record` | `compliance_officer` | Yes | Yes |
| `inheritance.commit` | system (saga) | n/a | Yes |
| `kernel.projections.admin` (Phase 4 read models) | `super_admin` | n/a | Yes |
| `workflow.suspend` / `workflow.reactivate` | `super_admin` | n/a | Yes |

Constitutional vows that cannot be broken by ANY role, including
`super_admin`:

1. The Surveyor General is the only emitter of
   `registry.command.commit_parcel` (C-21.1).
2. A consent revocation can only be issued by the original
   principal (C-20.5).
3. A traditional authority attestation can only be issued by that
   identified `traditional_authority` (C-21.6).
4. No AI / LLM may issue a workflow command (C-19.8).

`super_admin` is power, not bypass: break-glass invocations are
fully audited and time-boxed (15 minutes per RUNBOOK §10), AND the
above vows still hold inside a break-glass window.

## 5. Threat model

| Threat | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| Coerced attestation | Medium | High | Audit row carries originating IP, device id, session id. Compliance review may invalidate downstream. Appeals are first-class. |
| Compromised `surveyor_general` JWT | Low | Catastrophic | RS256 key rotation 90-day (R-2 §1.6 / RUNBOOK §11); MFA required (operator config); break-glass revocation. |
| Impersonated witness | Low | High | Witness authenticates via JWT + signs attestation with KMS key tied to their identity. |
| Saga spawn-storm DoS | Low | Medium | Engine load-time validator rejects unguarded cycles; per-instance spawn budget. |
| Replay attack of a stale command | Low | Medium | Every command carries a unique `command_id`; duplicates rejected at the engine entry. |
| Court order forgery | Medium | Catastrophic | Court orders are Evidence items with WORM lock + OTS anchor + manual `compliance_officer` ingest with cross-check against external case-management system (out-of-band). |
| AI scoring drift | n/a | Catastrophic | **No AI in any decision** (constitutional vow C-19.8). |
| Cross-tenant escalation | Low | High | Repository-layer tenant scoping inherited from Phase 3. |
| Outbox event replay tampering | Low | High | Outbox is append-only; idempotency on `event_id`; replay-byte-identical determinism gate. |
| Definition mutation in-flight | n/a | Catastrophic | `WorkflowDefinition` is frozen content; live mutation forbidden (C-19.5). |

## 6. Data classification

| Class | Examples | Handling |
| --- | --- | --- |
| **L1 — Legally consequential** | inheritance case, ownership transfer, court order | WORM-locked Evidence, OTS-anchored, dual-witness, compliance officer in the loop. |
| **L2 — Personally identifying** | beneficiary names, witness identities | Encrypted at rest (Phase 3.1 PII subsystem); access logged. |
| **L3 — Operational** | task queue rows, projection rows | Disposable (replayable); no encryption beyond TLS in transit. |
| **L4 — Public** | aggregated, anonymised dashboards | n/a. |

No L1 or L2 data leaves the platform without an explicit signed
operator action. Public verifier endpoint (D-8 in backlog) is
strictly L3/L4 only.

## 7. Audit invariants

In addition to the kernel audit log (inherited), Phase 4 declares:

| Invariant | Enforcement |
| --- | --- |
| Every state transition emits an `audit_log` row AND an event. | Engine layer; tested. |
| Every break-glass invocation carries `reason`, `ticket_id`, `actor`, and is paged to compliance. | Break-glass adapter; tested. |
| Every cross-context command emission is logged with `correlation_id` linking back to the workflow instance. | Outbox wrapper. |
| Every consent revocation is paged to compliance. | Domain event subscriber. |
| Every court order ingest is paged to compliance + legal. | Domain event subscriber. |

## 8. Cryptographic posture

Unchanged from Phase 3 except:

- **New domain events** carry the existing envelope's
  `event_id` + `correlation_id` for tamper-evident causality.
- **Saga composer** does not introduce a new key; it composes
  existing outbox-signed events.
- **Court order ingest** binds the order Evidence id to the
  `CourtOrder` aggregate via a hash chain — tamper-evident across
  the case lifecycle.

The CT-log key migration to a hardware-backed KMS (R-4 / Phase
backlog) is the only outstanding cryptographic upgrade; Phase 4
does NOT depend on its completion but benefits from it when done.

## 9. Operational safeguards

- **Two-person rule** for `surveyor_general_review.approved`: the
  SG and a separate `compliance_officer` must both sign. Enforced
  at the engine layer.
- **Cooling-off period:** any `surveyor_general_review.approved`
  takes effect after a 24-hour delay during which a court order
  may halt it. Enforced via a Timer; can be waived only by
  `super_admin` break-glass with audit.
- **Replay drills:** quarterly operator-driven replay of a random
  in-flight workflow instance to confirm determinism gate.
- **Independent rebuild:** the entire Workflow read side is
  rebuildable from `workflow_event_log` + the outbox in
  ≤ 30 minutes (extrapolated from the 821 ev/s Phase 3 replay
  throughput).

## 10. Acceptance criteria (security-specific)

These extend `PHASE4_SPEC §9.8`:

- [ ] Every new endpoint carries the 9 R-2 headers.
- [ ] Every new endpoint is in the rate-limit table.
- [ ] No new endpoint allows anonymous mutation.
- [ ] PEP denies every action whose policy does not explicitly permit.
- [ ] Every constitutional vow in §4 has a binding test.
- [ ] No new secret hardcoded.
- [ ] Audit log row exists for every state-mutating command.
- [ ] Court order ingest path is exercised by an end-to-end test.
- [ ] Two-person rule enforcement tested.
- [ ] Cooling-off timer tested.
- [ ] Break-glass invocation triggers compliance page.
- [ ] CSP / HSTS / headers regression test included in Phase 4 suite.

## 11. Cross-references

- R-2 Security Readiness Report — `/app/audit/R-2-SECURITY-READINESS-REPORT.md`
- Phase 3 Security Review §09 — `/app/audit/sections/09-security-review.md`
- Operational Runbook §14 (Incident Response) — `/app/audit/RUNBOOK.md`
- ADR-0019 §2.10 (Constitutional Constraints)
- ADR-0020 §3 (Consent Constraints)
- ADR-0021 §3 (Community Validation Constraints)
- ADR-0022 §3 (Inheritance Constraints)
- PHASE4_SPEC §6 (Authorization Matrix)
- PHASE4_SPEC §9.8 (Security Acceptance Gate)
