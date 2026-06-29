# Phase 3.6 Implementation Handoff (Next Session)

*Created*: 2026-06-29 (end of Decisions & Blueprint Checkpoint session)
*Status*: **Awaiting fresh-session implementation. Do NOT split across sessions unless absolutely necessary.**

This document is the **single starting point** for the next session.
Open this file first, then implement Phase 3.6 exactly as specified
below. Every architectural decision is already locked — no further
clarification or operator sign-off is required mid-implementation.

---

## 1. Pre-flight checklist (run these on session open)

```bash
cd /app && cat contracts/VERSION           # must show 1.2.0 — bump to 1.3.0 ONLY at the contract step
cd /app && python -m contracts.generate --check   # must say "Contract freeze OK — no drift."
cd /app/backend && python -m pytest tests/test_evidence_aggregate_invariants.py tests/test_evidence_api_e2e.py tests/test_contract_freeze.py -q
# Expected: 45+ passed. Confirms Phase 3.4+3.5 baseline still green.
```

If any pre-flight check fails, STOP and call `troubleshoot_agent`
before writing any Phase 3.6 code.

---

## 2. Source of truth (read these in order)

1. **`/app/contracts/v1/adr/ADR-0008-evidence-anchoring-and-integrity-saga.md`** — the binding architecture. §15 holds the five operator-locked decisions and the twelve constitutional invariants.
2. **`/app/memory/PHASE3_SPEC.md` §3.6, §3.6.1** — high-level spec; defers to ADR-0008.
3. **`/app/memory/PHASE3_BLUEPRINT.md` §7A–§7D, §8** — domain map, port additions, 12 event types, 4 PDP actions, locked decisions table.
4. **`/app/memory/PRD.md`** — top entry records this checkpoint.

Do NOT re-derive decisions. The five `§15 Decision N` blocks in
ADR-0008 are binding defaults; only the env knobs are variable.

---

## 3. Implementation ordering (within this single session)

| #   | Step                                                                     | Output                                                                                                                | Test gate                                          |
| --- | ------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| 1   | Append-only chain helper                                                 | `backend/contexts/evidence/domain/chain.py` — `compute_entry_hash(prev, payload) → str`                               | unit                                               |
| 2   | `EvidenceLock` aggregate                                                 | `domain/evidence_lock.py` (ADR-0008 §3.1)                                                                             | invariants                                         |
| 3   | `EvidenceIntegrityCheck` aggregate                                       | `domain/integrity_check.py` (ADR-0008 §3.2 — 10-value `triggered_by` enum from §15 Decision 4)                         | chain invariants                                   |
| 4   | `AnchorBatch` aggregate + `AnchorAttempt` value object                   | `domain/anchor_batch.py` (ADR-0008 §3.3, eight-state FSM)                                                              | FSM invariants                                     |
| 5   | New domain events                                                        | extend `domain/events.py` with 12 event factories                                                                     | publish round-trip                                 |
| 6   | `AnchorPort` Protocol                                                    | `ports/anchor.py` (ADR-0008 §5.1)                                                                                     | (interface only)                                   |
| 7   | `CheckpointPublisherPort` Protocol                                       | `ports/checkpoint_publisher.py` (ADR-0008 §5.2)                                                                       | (interface only)                                   |
| 8   | Mongo repositories (insert-only with adapter-level refusal of update/delete except whitelisted CAS) | `adapters/mongo_lock_repository.py`, `adapters/mongo_integrity_repository.py`, `adapters/mongo_anchor_repository.py`  | append-only enforcement                            |
| 9   | `ctlog_internal` adapter (PRIMARY)                                       | `adapters/ctlog_internal.py` — append-only `evidence_ctlog_tree`, JWKS-signed daily heads                              | NIST RFC 6234 vectors + checkpoint signature verify |
| 10  | `ots_v1` adapter (SECONDARY)                                             | `adapters/ots_v1.py` — calendar list + 2-of-N quorum from §15 Decision 2; one-calendar failure does NOT fail saga       | calendar-failure resilience (skipped if network unavailable) |
| 11  | `r2_public_checkpoint` adapter (dev stub)                                | `adapters/r2_public_checkpoint.py` — writes signed heads under `${EVIDENCE_CHECKPOINT_DIR}` locally                    | unit                                               |
| 12  | `AnchorBatcher` background job                                           | `application/anchor_saga.py` — 60s cadence, auto-split at 256 (§15 Decision 5)                                         | scoop + batch + commit                             |
| 13  | `AnchorConfirmer` background job                                         | `application/anchor_saga.py` — CAS claim, backoff `[10s,60s,5m,1h,6h,24h]`, max 12 → DLQ                              | DLQ + replay determinism                           |
| 14  | `IntegrityScheduler` background job                                      | `application/integrity_scheduler.py` — 30d cadence + 7 mandatory triggers (§15 Decision 4)                            | trigger-fanout test                                |
| 15  | `CtlogCheckpointer` background job                                       | `application/ctlog_checkpointer.py` — signs head with platform JWKS                                                    | signed-head verifier                               |
| 16  | API router                                                               | `api/anchor_router.py` — 10 endpoints from ADR-0008 §10                                                               | E2E                                                |
| 17  | PDP policies                                                             | extend `authorization.py` with 4 new actions from PHASE3_BLUEPRINT §7D                                                | role matrix                                        |
| 18  | Wire into `main.py` startup                                              | router include + worker boot + index ensure                                                                            | smoke                                              |
| 19  | **Contract bump 1.2.0 → 1.3.0**                                          | extend `contracts/generate.py` with 12 new events, 8 new request DTOs, 10 new response DTOs, 3 new field-projections, 4 new PDP actions. Refresh fingerprints. ADR-0008 listed in release manifest. Update CHANGELOG. | `python -m contracts.generate && python -m contracts.generate --check` both green |
| 20  | Acceptance tests (~38)                                                   | See ADR-0008 §11 table — one file per row                                                                              | Full suite green                                   |
| 21  | Static-scan tests (constitutional invariants 2, 12)                      | scan `contexts/evidence/` for `landvault_landvaults` references (must be 0); scan event payload schemas for PII fields (must be 0) | green                                              |

---

## 4. The five locked decisions (DO NOT re-litigate)

| # | Topic                          | Locked value                                                                                  | Env knob                                       |
| - | ------------------------------ | --------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| 1 | CheckpointPublisher target     | dev: local-FS; prod: R2 / IPFS / both via fan-out; core domain depends ONLY on the Protocol   | `EVIDENCE_CHECKPOINT_PUBLISHERS` (csv)         |
| 2 | OTS calendars                  | `btc.calendar.opentimestamps.org`, `alice.btc.calendar.opentimestamps.org`, `finney.calendar.eternitywall.com` | `EVIDENCE_OTS_CALENDARS` (csv)                 |
| 2 | OTS quorum                     | 2 of N (one-calendar failure does NOT fail saga)                                              | `EVIDENCE_OTS_CALENDAR_QUORUM=2`               |
| 3 | Batcher cadence                | 60s                                                                                           | `EVIDENCE_ANCHOR_BATCHER_INTERVAL_SECONDS=60`  |
| 3 | Confirmer backoff              | `[10s, 60s, 5min, 1h, 6h, 24h]`                                                               | `EVIDENCE_ANCHOR_BACKOFF_SECONDS`              |
| 3 | Max attempts → DLQ             | 12                                                                                            | `EVIDENCE_ANCHOR_MAX_ATTEMPTS=12`              |
| 4 | Integrity baseline             | 30d per sealed item                                                                           | `EVIDENCE_INTEGRITY_CHECK_INTERVAL_DAYS=30`    |
| 4 | Integrity mandatory triggers   | `scheduled`, `on_demand`, `pre_seal`, `pre_certificate`, `pre_public_verification`, `pre_ownership_transfer`, `pre_subdivision`, `post_storage_migration`, `post_remediation`, `security_incident` | — (domain enum)                                |
| 5 | Max batch size                 | 256 seals, auto-split above                                                                   | `EVIDENCE_ANCHOR_MAX_BATCH_SIZE=256`           |

---

## 5. Constitutional invariants (named tests required)

From ADR-0008 §15. Every release in Phase 3.6+ must keep these green:

1. Evidence remains immutable after sealing.
2. Registry is never mutated by the Evidence context.
3. All cross-context communication occurs only through immutable domain events.
4. Anchor records are append-only.
5. Merkle roots are deterministic.
6. CT-log is the primary trust anchor.
7. OpenTimestamps is a secondary independent anchor (single-calendar failure does NOT fail saga).
8. Replay is idempotent.
9. DLQ is resumable.
10. Complete audit coverage (every FSM edge → outbox event + audit row).
11. No binary data inside MongoDB documents.
12. No PII leakage through checkpoints or anchor metadata.

---

## 6. Acceptance gate (this session terminates ONLY when ALL of these pass)

```bash
cd /app && python -m contracts.generate && python -m contracts.generate --check
# → "Wrote N contract artifacts (version 1.3.0)." + "Contract freeze OK — no drift."

cd /app/backend && python -m pytest \
  tests/test_evidence_lock_invariants.py \
  tests/test_evidence_integrity_check_chain.py \
  tests/test_anchor_batch_fsm.py \
  tests/test_anchor_saga_resumability.py \
  tests/test_anchor_saga_dlq_replay.py \
  tests/test_ctlog_internal_adapter.py \
  tests/test_anchor_api_e2e.py \
  tests/test_evidence_no_registry_writes.py \
  tests/test_contract_freeze.py \
  tests/test_evidence_aggregate_invariants.py \
  tests/test_evidence_api_e2e.py \
  -q
# → ~120 passed (38 new + 82 existing evidence + contracts)
```

OTS adapter network tests (`tests/test_ots_v1_adapter.py`) are
skipped-by-default; runnable with `OTS_NETWORK_TESTS=1` env.

---

## 7. Strict non-goals for this session

These belong to later phases — do NOT implement in Phase 3.6:

* `evidence_timeline`, `evidence_custody`, Legal Hold aggregate → **Phase 3.7**
* Read-model projections + materialized views → **Phase 3.8**
* TypeScript SDK regen + React Evidence UI → **Phase 3.9**
* Court-export bundle + offline verifier + Phase Acceptance Review packet → **Phase 3.10**
* Public verification endpoints → **Phase 5**
* Workflow context, Consent / Survey / Community / Inheritance templates → **Phase 4** (gated on Phase 3.10 sign-off)

---

## 8. Operator escalation triggers

Stop and call `ask_human` if:

* Any of the five locked decisions appear ambiguous in practice.
* The 256-seal auto-split surfaces a Mongo transaction-size concern.
* OTS calendar quorum design fails under realistic network failure modes (e.g. all three calendars down for > backoff window).
* The CT-log checkpoint signing key needs rotation policy beyond what JWKS provides.

Otherwise proceed without interruption to the acceptance gate.
