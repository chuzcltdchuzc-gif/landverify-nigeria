# ADR-0009 — Timeline, Custody, Legal Hold, Supersession (Phase 3.7)

*Status*: **Accepted** — landed with contract bump **1.3.0 → 1.4.0**.
*Phase*: 3.7 (Timeline + Custody Chain + Legal Hold + Supersession).
*Depends on*: ADR-0007 (Sealing), ADR-0008 (Anchoring).

## 1. Decision

Phase 3.7 transforms Evidence into a complete legally-auditable record
by adding four interlocking artifacts:

1. **`TimelineEntry`** — append-only chained chronology per evidence_id.
   Auto-projected from the existing event stream. Insert-only at the
   adapter; `prev_hash` / `entry_hash` tamper-evident chain (same
   primitive as the Phase 3.6 integrity chain).
2. **`CustodyEntry`** — append-only chain-of-custody per evidence_id
   with `actor`, `role`, `action`, `previous_custody_id`,
   `justification`, optional `signature` + `signature_kid` metadata.
   Insert-only.
3. **`LegalHold`** — independent aggregate with FSM
   `active → released`. Overrides every retention rule. Both creation
   and release emit immutable events. The aggregate is the system of
   record; the future retention sweeper (Phase 3.8) reads from it.
4. **Supersession graph** — exposed as a read API over the
   `EvidenceItem.replaced_by` chain already persisted by Phase 3.3
   media remediation. New `evidence.supersession.recorded.v1` event
   produced when the chain extends; the entire graph remains navigable
   forever.

## 2. New events (5)

* `evidence.timeline.appended.v1`
* `evidence.custody.appended.v1`
* `evidence.legal_hold.applied.v1`
* `evidence.legal_hold.released.v1`
* `evidence.supersession.recorded.v1`

## 3. New endpoints (8 under `/api/v1/evidence/`)

* `GET  /items/{id}/timeline`
* `GET  /items/{id}/custody`
* `POST /items/{id}/custody`
* `GET  /items/{id}/supersession-chain`
* `GET  /items/{id}/legal-holds`
* `POST /items/{id}/legal-holds`
* `GET  /legal-holds/{hold_id}`
* `POST /legal-holds/{hold_id}/release`

## 4. New PDP actions (6)

`evidence.timeline.read`, `evidence.custody.read`,
`evidence.custody.record`, `evidence.legal_hold.read`,
`evidence.legal_hold.apply`, `evidence.legal_hold.release`. Hold
apply/release restricted to `super_admin` + `compliance_officer`.

## 5. Invariants (binding)

* Timeline and Custody chains are append-only. The repository refuses
  any update or delete operation that would mutate a prior link.
* Each chain link's `entry_hash = sha256(prev_hash || canonical_json(payload))`.
  Independent verification possible offline.
* LegalHold transitions `active → released` exactly once.
  Re-release attempts return `409 evidence.legal_hold.invalid_transition`.
* While at least one LegalHold for an evidence_id is ACTIVE, that
  evidence cannot be archived or have its retention shortened — the
  retention sweeper (Phase 3.8) consults this aggregate first.
* The supersession graph never deletes a predecessor; archived items
  remain readable forever.

## 6. Acceptance gate

All seven of:
* timeline reconstruction verified (chain hash + insert-only adapter)
* custody reconstruction verified
* supersession traversal verified
* retention override verified (LegalHold takes precedence)
* outbox replay produces identical projections
* invariant tests green
* contract drift gate green at 1.4.0
