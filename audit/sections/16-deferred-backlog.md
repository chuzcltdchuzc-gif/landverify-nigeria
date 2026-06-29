# 16 · Deferred Backlog

> Cross-links: [15 Outstanding Risks](15-outstanding-risks.md) ·
> [17 Production Readiness](17-production-readiness.md)

Items deferred OUT of Phase 3 with intent. These are NOT acceptance
blockers — they are scheduled follow-ups.

## D-1 · Workflow / Consent / Inheritance bounded context (Phase 4)

**Constitutionally gated** until the operator approves this Phase 3
Acceptance Review. Will require:

- ADR-0019 Workflow Engine
- ADR-0020 Consent State Machine
- ADR-0021 Survey / Field Capture
- ADR-0022 Community / Inheritance / Notifications

No code may be written until those ADRs are accepted.

## D-2 · CSP hardening

See [R-2](15-outstanding-risks.md). Two-day effort.

## D-3 · Hardware-backed KMS migration

See [R-4](15-outstanding-risks.md). Single-adapter swap in
`kernel/security/keys.py` — already designed for substitution.

## D-4 · Multi-client load test

See [R-5](15-outstanding-risks.md). Use the existing seed harness in
`tests/bench_phase310.py`, parameterise `n_clients`.

## D-5 · Excise the legacy `/api/parcels` demo path

The pre-Phase-3 demo routes still live under
`backend/routers/parcels.py`. They predate the DDD migration, fail
tests, and confuse operators. Remove in a single PR; restore the
legacy tests to green by deletion.

## D-6 · React UI translations

Phase 3.9 ships English-only. Government clients in NG / KE / GH will
want Yoruba, Hausa, Swahili, Twi. Adopt `i18next` against the
existing string table; no SDK change needed.

## D-7 · WCAG 2.2 AAA upgrade

Phase 3.9 lands at WCAG 2.2 AA (verified). Some government tenders
require AAA contrast + 7:1. A theming pass is straightforward — the
current palette already uses solid colours over slate-950.

## D-8 · Public verifier endpoint

A small `/api/v1/evidence/verify-proof` endpoint that accepts an OTS
artifact + composite hash and returns a verification result without
requiring auth. Useful for third-party verifiers. Estimated 1 day.

## D-9 · Projection lag SLO alarm

A `kernel.projections.lag_alert` event when any projection's
`lag_events` exceeds a configurable threshold (default 1,000). Pairs
with an external alarm channel (Slack / PagerDuty). Estimated 0.5 day.

## D-10 · Operator runbook

Operations documentation describing:

- How to trigger a replay safely.
- How to interpret a projection cursor + lag.
- How to extend an EvidenceLock retention.
- How to release a Legal Hold (with reason template).
- How to roll the JWT signing key.

Currently lives implicitly in the ADRs + tests. Should be lifted out
into a dedicated `RUNBOOK.md` before public launch.

---

## Summary

| ID | Title | Estimate | Class |
| --- | --- | ---: | --- |
| D-1 | Phase 4 (Workflow) | weeks | Roadmap |
| D-2 | CSP hardening | 2 days | Security |
| D-3 | KMS migration | 3 days | Infra |
| D-4 | Multi-client load test | 1 day | Performance |
| D-5 | Excise legacy demo | 0.5 day | Cleanup |
| D-6 | UI translations | 3 days | Localisation |
| D-7 | WCAG AAA | 2 days | Accessibility |
| D-8 | Public verifier | 1 day | Feature |
| D-9 | Projection lag alarm | 0.5 day | Observability |
| D-10 | Operator runbook | 2 days | Documentation |

Total ≈ 14 engineer-days excluding Phase 4. None are acceptance
blockers.
