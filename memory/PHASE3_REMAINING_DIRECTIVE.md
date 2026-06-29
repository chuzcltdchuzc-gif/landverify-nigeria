# Phase 3 Remaining — Operator Directive (Binding)

*Issued*: 2026-06-29 — locked sequence, no exceptions.

Phase 3 SHALL be completed in this order. No later phase may begin
until the current phase has passed its Acceptance Gate.

```
Phase 3.7  →  Phase 3.8  →  Phase 3.9  →  Phase 3.10  →  Operator Approval  →  Phase 4
```

## Phase 3.7 — Timeline + Custody + Supersession + Legal Hold

* Append-only chronological Evidence Timeline (upload / verify / seal /
  lock / integrity / anchor / version / supersession / legal-hold /
  access events).
* Complete chain-of-custody (actor, role, timestamp, action, previous
  reference, justification, signature metadata).
* Supersession graph (`previous_version_id`, `superseded_by`,
  `superseded_at`, `superseded_reason`). Originals stay immutable.
* Legal Hold as an independent append-only aggregate that overrides
  every retention rule. Removal is itself an immutable event.

**Acceptance gate**: timeline + custody + supersession traversal +
retention override + replay all verified; invariant tests green.

## Phase 3.8 — Events + Read Models + Projection Engine

* Immutable event catalog (already shipped at v1.3.0 — extended in 3.7).
* Projection versioning + replay engine + projection rebuild + snapshot
  support + projection health + lag metrics.
* Read models are **disposable** — full delete + replay must produce
  byte-identical results.
* **NO business logic in projections.**

**Acceptance gate**: full replay succeeds; projection rebuild matches
source; ordering / outbox / idempotency verified.

## Phase 3.9 — SDK + React Evidence UI

* Regenerate SDK from frozen v1.3.0+ contracts.
* React Evidence UI (Upload, List, Detail, Timeline, Seal Status,
  Integrity Status, Version History, Custody Chain, Legal Hold).
* UI consumes SDK only — no direct API calls, no duplicated DTOs, no
  business logic in UI.

**Acceptance gate**: SDK regenerated; TS compile clean; contract drift
zero; React pages complete; E2E tests pass.

## Phase 3.10 — Formal Phase Acceptance Review

Government-grade Acceptance Review Packet covering: Architecture,
ADR compliance, Invariant inventory, Acceptance test report, Security
review, Outstanding risks, Contract verification, Event verification,
Performance summary, Coverage summary.

**Phase 4 GATE**: Phase 4 (Workflows / Consent / Survey / Community /
Inheritance / Notifications) is **prohibited** until **all** of the
following are true:

- [ ] Phase 3.7 accepted
- [ ] Phase 3.8 accepted
- [ ] Phase 3.9 accepted
- [ ] Phase 3.10 accepted
- [ ] Architecture Review approved
- [ ] ADR compliance verified
- [ ] Contract drift = zero
- [ ] Replay verification passed
- [ ] Security review passed
- [ ] Operator explicitly authorises Phase 4

Phase 4 then begins with its own blueprint-first round
(ADR-0019 → ADR-0022).

---

This document is read first by every subsequent session.
