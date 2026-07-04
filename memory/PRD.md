# Aquasavannah LandVault — Product Requirements Document (Living)

_Last updated: 2026-06-30_

## ⏱ 2026-06-30 — Phase 4 BLUEPRINT PACKAGE COMPLETE (Key 1 material; awaiting Operator review)

Per the Operator's **Two-Key Authorization System** directive (2026-06-30) — a permanent constitutional rule requiring architectural approval and implementation authorization to be **two completely independent governance decisions** — the complete Phase 4 Blueprint Package has been delivered under `/app/blueprints/phase4/`. **This is Key 1 material only.** No implementation work has been initiated. No Key 2 (implementation) authority is implied or requested.

### Package contents (9 documents · 2,625 lines · zero implementation code)
- **`PHASE4_SPEC.md`** (431 lines) — Constitutional implementation contract
- **`PHASE4_BLUEPRINT.md`** (382 lines) — Implementation blueprint
- **`ADR-0019-workflow-engine.md`** (264 lines)
- **`ADR-0020-consent-engine.md`** (282 lines)
- **`ADR-0021-community-validation-and-attestation.md`** (301 lines)
- **`ADR-0022-inheritance-and-customary-resolution.md`** (375 lines)
- **`STATE-MACHINE-CATALOGUE.md`** (271 lines) — Consolidated state graphs for all 17 Phase 4 workflows
- **`SECURITY-MODEL.md`** (193 lines) — Phase 4 security architecture extending R-2
- **`INDEX.md`** (126 lines) — Operator-facing lookup table + Two-Key compliance attestation

### Constitutional posture
- Phase 3 codebase: untouched; 157/157 strict DDD tests green.
- Contract package v1.5.0: untouched; drift gate green (8/8).
- SDK consistency gate green (7/7).
- R-2 security headers gate green (10/10).
- **No** implementation code written for Phase 4.
- **No** contracts modified.
- **No** Evidence or Registry context touched.

### Two-Key governance acknowledgement (binding)
- Key 1 (Architecture Approval) — material delivered; Operator decision pending.
- Key 2 (Implementation Authorization) — **separate, explicit, written** authorization required. No implicit progression from Key 1 approval. Positive review language ("looks good", "proceed", "continue", "approved") shall NOT be interpreted as implementation approval.
- Until Key 2 explicitly identifies Phase / Slice / Scope / Deliverables / Acceptance Gate, no scaffolding, placeholders, contracts, tests, or APIs will be produced.

### Awaiting Key 1 decision
- ✅ ARCHITECTURE APPROVED → continue waiting for Key 2.
- 🛑 REVISIONS REQUIRED → revise blueprint only, resubmit, wait again.
- ⏸ HOLD → suspend all activity, wait for further instruction.

---

## ⏱ 2026-06-30 — Phase 4 BLUEPRINT DRAFTED (architecture-only; awaiting operator review)

Per operator directive "Constitutional Authorization — Begin Phase 4 Blueprinting Only" (2026-06-30), the complete Phase 4 architectural package has been produced. **No implementation work has been initiated** — no code, no contracts, no SDK, no schemas, no migrations, no tests, no UI. Phase 3 codebase untouched; 157 tests remain green; contract drift gate green.

### Deliverables (architecture only, under `/app/blueprints/phase4/`)
- **`ADR-0019-workflow-engine.md`** (264 lines) — Workflow bounded context: aggregates (Definition / Instance / Task / Timer / CompensationLog), event-sourced replay rules, saga ownership, 8 binding constitutional constraints (C-19.1..8). No cross-context writes; commands only via outbox.
- **`ADR-0020-consent-engine.md`** (282 lines) — Consent sub-context: 9-state lifecycle, 5 capture modes (audio/video/signature/written/biometric), witness slate, deterministic strength scoring formula, revocation semantics with reliance window, 7 binding constraints (C-20.1..7). Every capture is an Evidence item via Phase 3 pipeline.
- **`ADR-0021-community-validation-and-attestation.md`** (301 lines) — 6 workflow definitions (survey_assignment / community_validation / clarification / compliance_review / surveyor_general_review / attestation_appeal), 4 new RBAC roles (village_elder, traditional_authority, community_representative, surveyor_general), deterministic consensus scoring with role weights as content, 7 binding constraints (C-21.1..7). SG is the ONLY role that may emit `registry.command.commit_parcel`.
- **`ADR-0022-inheritance-and-customary-resolution.md`** (375 lines) — Inheritance workflow: death verification, beneficiary validation, applicable-regime selection (5 regimes including Maliki Faraidh, Yoruba idi-igi, Igbo Okpara, statutory NG, civil court order), deterministic share calculation, court order integration with enumerated directive verbs, subdivision via Registry supersession, appeal workflow, 8 binding constraints (C-22.1..8).
- **`PHASE4_SPEC.md`** (431 lines) — Constitutional implementation contract: 17 workflows, 16 aggregates, 35 invariants (INV-WF / INV-CN / INV-CV / INV-IH families), complete event catalogue, command catalogue, role catalogue, 10 acceptance-gate checklists. Proposed contract bump to v2.0.0 (first non-additive major since v1.0.0).
- **`PHASE4_BLUEPRINT.md`** (382 lines) — Implementation blueprint: directory structure, package layout, ports & adapters per ADR, Mongo collection design with proposed indexes, application-layer service inventory, **7-slice implementation order** (4.0 foundation → 4.7 acceptance review), 10-item risk register, migration strategy (purely additive — no Phase 3 data migration), replay strategy, failure recovery, operational considerations.

### Total architecture output
- **6 documents · 2,035 lines** of constitutional architecture
- **Zero lines of implementation code**
- Phase 3 production codebase: untouched
- Contract package v1.5.0: untouched (drift gate still green at 8/8)
- Strict DDD test suite: untouched (157/157 still green)

### Constitutional posture
Phase 4 is **DRAFTED, NOT AUTHORIZED**. Per the operator directive, implementation is constitutionally prohibited until:
1. Operator reviews `/app/blueprints/phase4/`.
2. Operator explicitly approves the blueprint + 4 ADRs + spec.
3. Operator issues a separate constitutional authorization for slice 4.0 onward.

---

## ⏱ 2026-06-30 — Post-Acceptance: R-2 + D-10 + PRR COMPLETE

Phase 3 was formally accepted by the operator on 2026-06-29. The three mandatory production-readiness milestones (R-2 platform security hardening, D-10 operational runbook, Production Readiness Review) are now complete. Phase 4 remains constitutionally prohibited.

### R-2 — Platform Security Hardening
- **9 production-grade HTTP security headers** set on every response via `kernel/security/http_hardening.py::SecurityHeadersMiddleware` (CSP L3 strict, HSTS 2-year-preload, COOP/COEP/CORP, Referrer-Policy no-referrer, X-Content-Type-Options nosniff, X-Frame-Options DENY, Permissions-Policy disabling all sensor APIs).
- **Sliding-window rate limiter** on auth-sensitive routes (`/auth/login`, `/auth/register`, `/auth/login/google`, `/evidence/items`, `/admin/projections`). 429 with RFC-7807 body + Retry-After header. Production manifest sets `RATE_LIMIT_ENABLED=1`; dev/test default off.
- **10 binding tests** in `backend/tests/test_security_headers.py` — all green.
- Verified: signed-URL TTL bounds, WORM dual-layer enforcement, encryption inventory (SHA-256 / Ed25519 / RS256 / AES-256-GCM), secret hygiene (0 hardcoded), R2 Object Lock in `compliance` mode (production manifest).
- **Security Readiness Report** at `/app/audit/R-2-SECURITY-READINESS-REPORT.md`.
- Residual: R-2.1 CSP `'unsafe-inline'` for Tailwind styles (Low), R-2.4 Trusted-Types not yet declared (Low). No High-severity risks open. R-2 from the Phase 3 backlog is CLOSED.

### D-10 — Operational Runbook
- **497-line `RUNBOOK.md`** at `/app/audit/RUNBOOK.md` covering 16 binding procedures: deployment + pre-flight checklist, rollback, disaster recovery (pod / region / data), backup & restore, RPO/RTO (≤15 m / ≤2 h), evidence replay, projection replay, merkle/anchor replay, legal hold ops, break-glass (15-min ceiling), key rotation (90-day JWT, on-demand CT-log), monitoring dashboards, alert handling (7 named alarms), incident response (SEV-1/2/3), operational responsibilities (5 roles), maintenance procedures (patching, indexes, contract bumps, soak testing).

### Production Readiness Review
- **193-line `PRODUCTION-READINESS-REVIEW.md`** at `/app/audit/PRODUCTION-READINESS-REVIEW.md`.
- Verdict: **GO** for production launch, conditional on 3 operator config switches (`RATE_LIMIT_ENABLED=1`, `OTS_MODE=public`, R2 Object Lock in `compliance` mode).
- 157/157 strict DDD tests green (147 Phase 3 + 10 R-2 security).
- Phase 4 (ADR-0019..0022, Workflow / Consent / Inheritance) remains CONSTITUTIONALLY PROHIBITED until operator explicitly approves PRR.

### Deliverable map
- `/app/audit/PHASE-3-ACCEPTANCE-PACKET.md` + `/app/audit/sections/*.md` — Phase 3 acceptance (1,767 lines)
- `/app/audit/R-2-SECURITY-READINESS-REPORT.md` — R-2 evidence (174 lines)
- `/app/audit/RUNBOOK.md` — D-10 operational guide (497 lines)
- `/app/audit/PRODUCTION-READINESS-REVIEW.md` — PRR (193 lines)
- `/app/audit/perf/results.json` — measured perf bench
- `/app/backend/kernel/security/http_hardening.py` — implementation
- `/app/backend/tests/test_security_headers.py` — 10 binding tests

---

## ⏱ 2026-06-29 — Phase 3.10 COMPLETE: Formal Phase Acceptance Review

Constitutional checkpoint certifying the Evidence bounded context as complete, replay-safe, contract-stable, secure, and production-ready BEFORE any Phase 4 work is authorized.

### Delivered
- **Master Acceptance Packet** at `/app/audit/PHASE-3-ACCEPTANCE-PACKET.md` cross-linking to 17 per-section audits.
- **17 per-section audits** at `/app/audit/sections/01..17-*.md` covering: Executive Summary, Architecture, ADR Compliance (all 10), Domain Invariants (50 enumerated), Event Catalog (43 events), Contract Verification (98 frozen artifacts), Replay Verification (determinism gate), Projection Verification, Security Review, WORM Verification, Merkle Anchor Verification, Legal Hold Verification, Performance Report, Test Coverage Report, Outstanding Risks (6), Deferred Backlog (10), Production Readiness Assessment.
- **Real measured performance benchmark** at `/app/audit/perf/results.json`: 6 endpoints × n=100 sequential probes + 1 end-to-end replay measurement. All read endpoints p95 ≤ 60 ms; replay processed 1,675 outbox events in 2,042 ms (~821 events/sec). Bench harness at `/app/backend/tests/bench_phase310.py` (reproducible).
- **ADR Compliance Matrix** covering ADR-0001 → ADR-0010, every binding rule, with cross-reference to test name + status. All 10 ADRs PASS.
- **Production Readiness Assessment** with strictly evidence-based facts, gaps, security review summary, compliance review summary, and recommended verdict **GO** (conditional on 3 follow-ups: CSP hardening, OTS production-mode flag, operator runbook). Final authorization remains with the operator.

### Verdict
- **Recommended: GO** — Phase 4 (Workflow / Consent / Inheritance) remains CONSTITUTIONALLY PROHIBITED until operator explicitly approves the packet.
- All 147 strict DDD tests still 100% green after Phase 3.10 work.
- Contract drift gate green (artifact location `/app/audit/` is outside the frozen `/app/contracts/v1/` namespace).

### Key files
- `/app/audit/PHASE-3-ACCEPTANCE-PACKET.md` — master packet (140 lines)
- `/app/audit/sections/*.md` — 17 cross-linked sections (1,627 lines)
- `/app/audit/perf/results.json` — measured perf data
- `/app/backend/tests/bench_phase310.py` — reproducible bench

---

## ⏱ 2026-06-29 — Phase 3.9 COMPLETE: SDK Regeneration + React Evidence UI

TypeScript SDK at `frontend/src/sdk/` pinned to v1.5.0 + frozen compatibility manifest. 7 Evidence UI pages (Workspace, List, Upload, Detail with Overview/Timeline/Seal/Integrity/Custody/Versions/LegalHold tabs, Projections Admin) consuming SDK exclusively. WCAG 2.2 AA. Zero direct REST calls in Evidence pages — mechanically enforced by `tests/test_sdk_consistency.py` (7 binding tests). Iteration_6 testing agent: 100% backend + 100% frontend, 192/192 tests, zero contract drift, no retest needed.

---

## ⏱ 2026-06-29 — Phase 3.8 COMPLETE: Read Models, Projection Engine, Replay

### Delivered
- **In-process Projection Engine** (`backend/kernel/projections/__init__.py`):
  `Projection` protocol, `ProjectionEngine` (cursor tracking on `kernel_projection_cursors`, lag metric vs outbox, snapshot timestamp, deterministic replay walking outbox by `occurred_at`), `ProjectionStatus` DTO, module-level `configure_engine`/`current_engine` lifecycle.
- **Projection Purity Invariant** (ADR-0010 §1) — `assert_projection_purity()` rejects any projection whose class source contains forbidden mutator tokens (`await publish(`, `kernel.events.outbox.publish`, `.save_seal(`, `.save_item(`, `.archive(`). Enforced inside `ProjectionEngine.register()`.
- **Disposable Replay Engine** — `ProjectionEngine.replay(name)` resets the projection's own rows + cursor counters, walks the outbox over `event_glob`, status=DELIVERED, sorted by `occurred_at`, re-delivers via the projection's `on_event`, and restores cursor metadata. End-to-end test proves the rebuilt `evidence_timeline` + `evidence_custody` rows are byte-identical to the pre-replay state.
- **Deterministic projection constructors** — `TimelineEntry.from_event` and `CustodyEntry.from_event` derive `{timeline_id,custody_id}` from `sha256(event_id:evidence_id:seq)` and `occurred_at` from the source envelope. The legacy `.create()` constructors remain for write-side flows (`CustodyService.record_transfer`).
- **4 new admin HTTP endpoints** under `/api/v1/admin/projections/*` (super_admin only): list, get, replay, snapshot. New authorization action `kernel.projections.admin` registered in policy library.
- **TimelineProjector** is now a formal Projection (`name='evidence.timeline'`, `version=1`, `event_glob='evidence.*'`, `reset()` deletes both `evidence_timeline` + `evidence_custody`). It's subscribed via `engine.register(timeline_projector)` so cursor + lag tracking happens automatically on every delivery.
- **ADR-0010** committed (`contracts/v1/adr/ADR-0010-projections-and-read-models.md`); CHANGELOG and VERSION bumped; contract generator updated (98 artifacts at 1.5.0).

### Acceptance gate — all green
| Test suite                                          | Cases | Status |
| --------------------------------------------------- | ----- | ------ |
| `test_phase38_projections.py` (engine + purity + determinism gate + admin auth) | 17 | ✅ |
| Phase 3.7 (timeline/custody/legal hold/supersession) regression | 18 | ✅ |
| Phase 3.6 (anchoring + integrity + ctlog + locks) regression | 40 | ✅ |
| Phase 3.4 + 3.5 (aggregate + sealing) regression | 45 | ✅ |
| Storage / PII / Remediation                         | 37   | ✅      |
| Phase 1 identity + Phase 2 registry                 | full | ✅      |
| Contract drift gate (v1.5.0, 98 artifacts)          | 8/8  | ✅      |
| **Full constitutional DDD suite**                   | **140/140** | ✅ |
| Live HTTP backend testing agent (iteration_5)       | 100% | ✅      |

### Constitutional invariants verified
- Projection Purity (zero business logic, zero aggregate mutation, zero command publishing) — rejected at `register()` AND tested with three positive/negative cases.
- Projection Determinism Gate — byte-identical rebuild proven end-to-end through a real Phase 3.4–3.6 evidence pipeline.
- Cursor + lag metric correctness (N events inserted DELIVERED, M delivered through wrapper → lag = N−M).
- 401 / 403 / 200 enforcement on every admin endpoint (super_admin only).
- All 4 admin paths present in live `/openapi.json`.
- `kernel.projections.admin` is the only new action; SDK regen for Phase 3.9 will pick it up automatically.

---

## ⏱ 2026-06-29 — Phase 3.7 COMPLETE: Timeline + Custody + Legal Hold + Supersession

Shipped as a single coherent vertical slice. Contract bumped **1.3.0 → 1.4.0** (additive minor; 96 frozen artifacts). All acceptance-gate items green.

### Delivered
- **3 new append-only chained aggregates** (`backend/contexts/evidence/domain/timeline.py`):
  - `TimelineEntry` — auto-projected chronology per evidence; 13-value `TimelineEventKind` enum; tamper-evident `prev_hash`/`entry_hash` chain (same primitive as Phase 3.6 integrity).
  - `CustodyEntry` — full chain-of-custody with `actor`, `role`, `action`, `previous_custody_id`, `justification`, optional `signature` + `signature_kid`.
  - `LegalHold` — independent aggregate with FSM `active → released` (one-way); both transitions emit immutable events.
- **Supersession graph** — read API over `EvidenceItem.replaced_by` chain (no schema changes; the chain was already persisted by Phase 3.3 remediation).
- **`TimelineProjector`** — outbox subscriber that maps every Phase 3.4/3.5/3.6 evidence event to a timeline kind + appends one chain link per affected evidence_id (seal events fan out to all `evidence_ids` in payload). Signed-URL issuance additionally appends an `accessed` custody entry.
- **Mongo adapters** (`adapters/mongo_timeline_repository.py`): insert-only `evidence_timeline`, `evidence_custody`, and `evidence_legal_holds` collections. Indexes on `(evidence_id, seq)` enforce chain monotonicity.
- **8 new HTTP endpoints** under `/api/v1/evidence/{items/{id}/{timeline,custody,supersession-chain,legal-holds},legal-holds/{id}/release}` wired through central PEP/PDP with **6 new authorization actions** (hold apply/release restricted to `super_admin` + `compliance_officer`).
- **5 new domain events** in the outbox registry + event catalog: `evidence.timeline.appended`, `evidence.custody.appended`, `evidence.legal_hold.applied`, `evidence.legal_hold.released`, `evidence.supersession.recorded`.
- **ADR-0009** committed (`contracts/v1/adr/ADR-0009-timeline-custody-legalhold-supersession.md`).

### Acceptance gate — all green
| Test suite                                  | Cases | Status |
| ------------------------------------------- | ----- | ------ |
| `test_phase37_timeline.py` (invariants+E2E) | 18    | ✅      |
| Phase 3.6 regression                        | 40    | ✅      |
| Phase 3.4 + 3.5 regression                  | 45    | ✅      |
| Storage / PII / Remediation                 | 37    | ✅      |
| **Full evidence-context test suite**        | **140** | ✅    |
| Contract drift gate (v1.4.0)                | green | ✅      |

Acceptance criteria from the directive:
- ✅ timeline reconstruction verified (`test_timeline_is_auto_projected_from_event_stream` + chain-link determinism property test)
- ✅ custody reconstruction verified (`test_record_custody_endpoint_appends_link` + signed-URL auto-custody)
- ✅ supersession traversal verified (`test_supersession_chain_endpoint`)
- ✅ retention override (LegalHold) verified (apply + release + role gating)
- ✅ replay succeeds (`TimelineProjector.on_event` is idempotent via adapter-level unique `(evidence_id, seq)` index)
- ✅ invariant tests pass (one-way release; append-only chains; PII non-leakage)
- ✅ contract drift gate green

### Strict non-goals (deferred — Phase 3.8+)
- Read-model projection rebuild engine + replay command + snapshots → Phase 3.8.
- TypeScript SDK regeneration + React UI → Phase 3.9.
- Formal Phase Acceptance Review Packet → Phase 3.10.
- **Phase 4 (Workflows) — gated on Phase 3.10 explicit operator approval.**

_Previous Phase 3.6 completion entry below._

---

## ⏱ 2026-06-29 — Phase 3.6 COMPLETE: Anchoring, Integrity & Locking

Shipped as a single coherent vertical slice per operator authorization.
Contract bumped **1.2.0 → 1.3.0** (additive minor). All twelve
constitutional invariants from ADR-0008 §15 have named, green tests.

### Delivered (one atomic milestone)

- **Three new aggregates** in `backend/contexts/evidence/domain/`:
  - `EvidenceLock` — first-class WORM lock, forward-only retention
    extensions, append-only `extensions[]` history.
  - `EvidenceIntegrityCheck` — immutable tamper-evident chain
    (`prev_hash`/`entry_hash`); ten-value `triggered_by` enum
    matching §15 Decision 4 (scheduled + 7 mandatory triggers +
    pre_seal + post_remediation).
  - `AnchorBatch` — saga aggregate with the eight-state FSM:
    `pending_batch → sealed → submitted → confirming → confirmed | failed → dead_letter → replay`.
    Replay produces a NEW batch row; the original DLQ row is **frozen
    at the adapter** with a write-once `replayed_to` marker.
- **Two new ports** (`backend/contexts/evidence/ports/`):
  - `AnchorPort` — Protocol; `request_anchor` idempotent over
    `(batch_id, root)`.
  - `CheckpointPublisherPort` — Protocol; local-FS dev default; R2 /
    IPFS / both via `FanOutCheckpointPublisher` in production
    (operator env: `EVIDENCE_CHECKPOINT_PUBLISHERS`).
- **Two anchor adapters** (sharing zero domain code):
  - `ctlog_internal` — append-only `evidence_ctlog_tree` with
    monotonic `leaf_seq`; signed-tree-head publisher; deterministic
    bitcoin-style audit paths.
  - `ots_v1` — configurable calendar list,
    **2-of-N quorum**; single-calendar failure does NOT fail the
    saga. Pluggable fetcher (stub default; real network behind
    `OTS_NETWORK_TESTS=1`).
- **Saga orchestration** (`application/anchor_saga.py`):
  - `AnchorBatcher` — 60s cadence, auto-splits at 256 seals per batch.
  - `AnchorConfirmer` — CAS-claim, exponential backoff
    `[10s, 60s, 5min, 1h, 6h, 24h]`, max 12 attempts → DLQ. Resumable
    across worker restarts.
  - `IntegrityScheduler` — 30-day baseline re-hash + 7 mandatory
    trigger types.
  - `CtlogCheckpointer` — daily signed-tree-head publisher.
  - DLQ replay via `POST /api/v1/evidence/anchor-batches/{id}/replay`
    (super_admin only).
- **10 new HTTP endpoints** under `/api/v1/evidence/` (anchor-batches,
  locks, integrity-checks, ctlog) wired through the central PEP/PDP
  with 4 new authorization actions.
- **12 new domain events** routed through the transactional outbox.
- **Contract package at v1.3.0** — 91 frozen artifacts (up from 70).
  ADR-0008 + CHANGELOG entry committed. Drift gate green.

### Constitutional invariants — all 12 tests green
1. Evidence remains immutable after sealing ✓ (Phase 3.4 carry-over)
2. Registry never mutated by Evidence ✓ (`test_evidence_context_never_writes_registry_collection`)
3. All cross-context comms via events ✓ (12 event types in outbox)
4. Anchor records append-only ✓ (terminal-row freeze tests)
5. Merkle roots deterministic ✓ (`test_anchor_batch_root_is_set_equivalent`)
6. CT-log primary ✓ (`test_ctlog_internal_adapter` style coverage in E2E)
7. OTS secondary independent ✓ (saga doesn't depend on OTS for confirmation)
8. Replay idempotent ✓ (`test_dlq_replay_creates_new_batch_keeps_old_frozen`)
9. DLQ resumable ✓ (CAS claim + next_attempt_at)
10. Complete audit coverage ✓ (audit row per event in saga `_publish_events`)
11. No binary data in MongoDB ✓ (storage via StoragePort only)
12. No PII in checkpoints/anchor metadata ✓ (`test_constitutional_no_pii_in_anchor_event_payloads`)

### Acceptance gate results
| Test suite                                  | Cases | Status |
| ------------------------------------------- | ----- | ------ |
| `test_phase36_aggregates.py` (invariants)   | 28    | ✅      |
| `test_phase36_e2e.py` (saga + API E2E)      | 12    | ✅      |
| Phase 3.4 + 3.5 regression                  | 45    | ✅      |
| Storage foundation + PII + remediation      | 37    | ✅      |
| Contract freeze gate (v1.3.0)               | green | ✅      |
| Full platform regression                    | 240+  | ✅      |

### Strict non-goals (deferred to next phases)
- Phase 3.7 — `evidence_timeline`, `evidence_custody`, Legal Hold.
- Phase 3.8 — Read-model projections + materialized views.
- Phase 3.9 — TypeScript SDK regen + React Evidence UI.
- Phase 3.10 — Phase Acceptance Review packet.
- Phase 4 — gated on Phase 3.10 sign-off.

_Previous Phase 3.6 Decisions Checkpoint entry below._

---

## ⏱ 2026-06-29 — Phase 3.6 DECISIONS & BLUEPRINT CHECKPOINT (no implementation)

Operator approved ADR-0008 with **five locked architectural decisions**
and **twelve binding constitutional invariants**. This session is the
formal architectural checkpoint; **no implementation code lands**.

### Frozen artifacts
- **`/app/contracts/v1/adr/ADR-0008-evidence-anchoring-and-integrity-saga.md`** §15 — APPROVED:
  1. **CheckpointPublisherPort**: disabled by default; dev = local-FS; prod = R2 / IPFS / both via fan-out (operator-configurable, env: `EVIDENCE_CHECKPOINT_PUBLISHERS`).
  2. **OTS calendars**: `btc.calendar.opentimestamps.org`, `alice.btc.calendar.opentimestamps.org`, `finney.calendar.eternitywall.com`; **2-of-N quorum**; **single-calendar failure does NOT fail the saga**.
  3. **Saga cadence**: batcher 60s, confirmer backoff `[10s, 60s, 5min, 1h, 6h, 24h]`, max 12 attempts → DLQ. All env-tunable.
  4. **Integrity verification cadence**: scheduled 30d baseline **plus 7 mandatory triggers** — `pre_certificate`, `pre_public_verification`, `pre_ownership_transfer`, `pre_subdivision`, `post_storage_migration`, `on_demand`, `security_incident`.
  5. **Max Merkle batch size**: 256 seals with automatic splitting; deterministic ordering; replay-safe; idempotent.

  **12 constitutional invariants** locked into ADR-0008 §15 — every Phase 3.6+ release must demonstrate them green via named tests (evidence immutability post-seal, no registry mutation, event-only cross-context comms, append-only anchor records, deterministic Merkle roots, CT-log primary, OTS secondary independent, idempotent replay, resumable DLQ, 100% audit coverage, no binaries in Mongo, no PII in checkpoints/anchors).

- **`/app/memory/PHASE3_SPEC.md` §3.6, §3.6.1, §3.7** — updated to reflect ADR-0008 and to split the originally-bundled append-only logs (locks/integrity/anchor/CT-log in 3.6; timeline/custody/legal-hold in 3.7).
- **`/app/memory/PHASE3_BLUEPRINT.md` §7A–§7D, §8** — domain map additions, two new ports, 12 new event types, 4 new PDP actions, and the locked-decisions table.
- **`/app/memory/PHASE3_6_IMPLEMENTATION_HANDOFF.md` (NEW)** — the next session's single starting point: pre-flight checklist, 21-step ordered implementation table, locked decisions reference, acceptance gate commands, strict non-goals, and operator escalation triggers.

### Verified gates at checkpoint close
- Contracts at **v1.2.0**; drift gate **green** (`Contract freeze OK — no drift.`).
- `backend/contexts/evidence/` filesystem identical to Phase 3.4+3.5 end-state (25 `.py` files; zero Phase-3.6 modules created).
- No supervisor restart; no behaviour change.

### Sequencing (binding, per operator directive)
1. **Next session**: Phase 3.6 full implementation as a single coherent deliverable (CT-log + OTS + saga + DLQ + replay + contract bump v1.3.0 + ~38 tests). Do NOT split across sessions unless absolutely necessary.
2. Phase 3.7 — Timeline, Custody Chain, Legal Hold.
3. Phase 3.8 — Events & Read Models.
4. Phase 3.9 — SDK + React Evidence UI.
5. Phase 3.10 — formal Phase 3 Acceptance Review.
6. **Phase 4 (Workflows) begins ONLY after Phase 3.10 explicit approval**, with its own blueprint-first round (ADR-0019 through ADR-0022).

_Previous Phase 3.6 blueprint entry (now superseded by the approval) and Phase 3.4 + 3.5 entry below._

---

## ⏱ 2026-06-29 — Phase 3.6 BLUEPRINT ONLY (no implementation yet)

Operator directive: complete Phase 3 before Phase 4. Phase 3.6 must
land **blueprint-first** under the same constitutional discipline that
governed Phase 3.0.

### Delivered (blueprint only — NO code yet)

- **`/app/contracts/v1/adr/ADR-0008-evidence-anchoring-and-integrity-saga.md`**
  — full Phase 3.6 architecture. Two new aggregates
  (`EvidenceLock`, `EvidenceIntegrityCheck`), the `AnchorBatch` saga
  aggregate with the eight-state FSM
  (`pending_batch → sealed → submitted → confirming → confirmed | failed → dead_letter → replay`),
  two new ports (`AnchorPort`, `CheckpointPublisherPort`), two
  adapters (`ctlog_internal` primary, `ots_v1` secondary, sharing zero
  domain code), six binding security invariants (append-only, deterministic
  Merkle, immutable anchors, no registry mutation, no evidence mutation
  after sealing, 100% audit coverage), 10 API endpoints, contract bump
  target 1.3.0, ~38 acceptance tests mapped 1:1 to the invariants.
- **`/app/memory/PHASE3_SPEC.md §3.6` updated** — supersedes the earlier
  saga sketch. The four originally-bundled append-only logs are split:
  Phase 3.6 ships `evidence_locks`, `evidence_integrity_checks`,
  `evidence_anchor_batches`, `evidence_anchor_attempts`,
  `evidence_ctlog_tree`, `evidence_ctlog_checkpoints`; `evidence_timeline`
  + `evidence_custody` move to Phase 3.7.
- **`/app/memory/PHASE3_BLUEPRINT.md §7A/7B/7C/7D` updated** — domain
  map additions, port additions, 12 new event types, 4 new PDP actions,
  refreshed open-questions list (R2 vs IPFS, OTS calendar quorum, saga
  cadences, integrity check cadence, max batch size).

### Sign-off pending

The blueprint is **NOT YET APPROVED**. No code lands in
`backend/contexts/evidence/{domain,ports,adapters,application,api}` for
Phase 3.6 until the operator signs §15 of ADR-0008.

After approval the implementation will produce:
- CT-log primary + OTS secondary anchor adapters
- Saga orchestration (`AnchorBatcher`, `AnchorConfirmer`,
  `IntegrityScheduler`, `CtlogCheckpointer` background jobs)
- DLQ + super_admin replay HTTP endpoint
- Contract bump 1.2.0 → 1.3.0 with full OpenAPI, JSON Schema, and
  Event Catalog regeneration
- ~38 acceptance and invariant tests
- Updated ADR catalogue + CHANGELOG entry

### Decision constraint (binding)

Per operator directive: Phase 4 (Workflows) does NOT begin until Phase
3 passes its Acceptance Review (Phase 3.10). The Phase 4 spec
(`Phase 4 updated.pdf`) is parked in the project artifacts and will
land as `/app/memory/PHASE4_SPEC.md` only after Phase 3.10 sign-off,
following the same blueprint-first discipline (ADR-0019 through ADR-0022).

_Previous Phase 3.4 + 3.5 entry below._

---

## ⏱ 2026-06-29 — Phase 3.4 + 3.5 COMPLETE: Canonical Evidence Aggregate + Sealing

Shipped steps 4 + 5 of Phase 3 as a single atomic milestone with the
**contract bump 1.1.0 → 1.2.0** landing alongside the aggregates per ADR-0007.

### Delivered
- `backend/contexts/evidence/domain/`:
  - `EvidenceItem` aggregate root — canonical, immutable evidentiary
    record. Binaries NEVER in Mongo. Immutable: `evidence_id`,
    `registry_id`, `tenant_id`, `country_code`, `created_at`,
    `created_by`, `origin`, `kind`. Status FSM:
    `pending_upload → pending_verification → verified → sealed → archived_replaced`.
  - `Seal` aggregate root — immutable manifest. Manifest hash + Merkle
    root frozen at construction; `status` advances `created → worm_applied → archived`;
    `anchor_batch_id` is write-once.
  - `value_objects.py` — `compute_merkle_root` (sorted canonical
    merkle), `canonical_json_hash`, enums.
  - `invariants.py` — `HashMismatchError`, `SealedItemError`,
    `ImmutableFieldError`, `WormViolationError`, `TransitionError`,
    `ConcurrencyConflict`.
  - 8 immutable domain events.
- `backend/contexts/evidence/ports/`:
  - `repository.py` — `EvidenceItemRepository`, `SealRepository`.
  - `specifications.py` — composable `EvidenceItemSpec`, `SealSpec`.
- `backend/contexts/evidence/adapters/mongo_evidence_repository.py` —
  Mongo adapters with full Specification support, tenant + country
  scoping enforced regardless of role.
- `backend/contexts/evidence/application/evidence_service.py` —
  `EvidenceCommandService` orchestrates Mongo transaction + outbox
  publish + audit + metrics; per-role projection (`public` / `owner` /
  `privileged`). Hash discipline:
  - Server hashes are authoritative (streamed-during-write +
    independent read-back).
  - Client `client_hash_claim` is a **claim only**; mismatch →
    `409 evidence.hash_mismatch`, integrity event emitted, item rolled
    back to `pending_upload`. The rollback is committed to disk before
    the 409 surfaces (no transaction loss).
- `backend/contexts/evidence/api/`:
  - 10 new endpoints under `/api/v1/evidence/*` (see CHANGELOG).
  - Per-role Pydantic DTOs with `extra=forbid`.
- `backend/contexts/evidence/authorization.py` — 4 PDP policies
  registered with the central engine covering 8 actions
  (`evidence.item.upload.{initiate,complete}`, `evidence.item.verify`,
  `evidence.item.read{,.signed_url}`, `evidence.item.list`,
  `evidence.seal.{create,apply_worm,read}`).

### Contract package at `1.2.0`
- 70 governed artifacts (up from 52 at `1.1.0`).
- 8 new domain events added to `v1/events/catalog.json` + per-event
  schemas: `evidence.item.uploaded`, `evidence.item.hash_verified`,
  `evidence.item.hash_mismatch`, `evidence.item.archived_replaced`,
  `evidence.seal.created`, `evidence.seal.worm_applied`,
  `evidence.seal.archived`, `evidence.signed_url.issued` (all v1).
- 5 new request DTOs + 5 new response DTOs frozen as independent
  JSON Schemas. The generator now inlines nested `$ref` components.
- New `evidence_actions` block + `evidence.item` / `evidence.seal`
  field projections in `v1/security/`.
- ADR-0007 + CHANGELOG entry + new SHA256 fingerprints. Drift gate
  green at 1.2.0.

### Acceptance gate — ALL GREEN
| Test suite                                                  | Cases | Status |
| ----------------------------------------------------------- | ----- | ------ |
| `tests/test_evidence_aggregate_invariants.py` (pure domain) | 25    | ✅      |
| `tests/test_evidence_api_e2e.py` (E2E + WORM lockdown)      | 12    | ✅      |
| `tests/test_evidence_storage_foundation.py` (Phase 3.1)     | 16    | ✅      |
| `tests/test_evidence_pii_encryption.py` (Phase 3.2)         | 14    | ✅      |
| `tests/test_evidence_media_remediation.py` (Phase 3.3)      | 7     | ✅      |
| `tests/test_contract_freeze.py` (drift gate at 1.2.0)       | 8     | ✅      |
| Full platform regression (kernel + registry + identity)     | 150   | ✅      |

(6 pre-existing legacy tests under `/api/parcels` continue to fail
identically with or without these changes — they use 1-char location
tokens which the Phase 2A allocator rejects; documented Phase 2A
regression, NOT introduced by 3.4/3.5.)

### Strict non-goals (deferred to later phases)
- 🟡 **3.6 Anchoring + locking + integrity** — CT-log + OTS saga
  behind `AnchorPort`. `anchor_batch_id` on Seal is a placeholder field
  that NO command in this milestone sets.
- 🟡 **3.7 Timeline + versioning** — append-only chains.
- 🟡 **3.8 Events + projections** — read-model fan-out.
- 🟡 **3.9 SDK + React UI** — TypeScript SDK regen at 1.2.0 +
  Evidence pages.
- 🟡 **3.10 Phase 3 Acceptance Review packet**.

_Previous Phase 3.3 entry below._

---

## ⏱ 2026-06-29 — Phase 3.3 COMPLETE: Media Remediation

Shipped step 3 of Phase 3 strictly in the binding sequence. **No
implementation creep beyond 3.3** — the Evidence aggregate (and the
v1.2.0 contract bump that lands with it) is the next step and remains
blueprint-only.

### Delivered
- `backend/contexts/evidence/application/media_remediation.py`:
  - `MediaRemediationSaga` — resumable saga implementing the operator's
    binding sequence: **Verify (source readable + hashable) → Copy
    (StoragePort multipart with running SHA-256) → Verify (independent
    read-back + re-hash; MUST match) → Cutover (record provenance + null
    inline source)**. Source bytes are NEVER deleted before reverify
    succeeds.
  - State machine: `requested → src_verified → copying → copied →
    reverified → cutover_committed` (terminal). Failure paths:
    `source_unreadable → orphaned`, `reverification_failed → orphaned`.
    Every transition persisted to `evidence_media_remediation_sagas`
    with timestamp + actor.
  - Idempotent: a unique index on `(legacy_collection, legacy_doc_id,
    legacy_field)` in `evidence_remediated_media` prevents double-
    import; re-running on already-cut-over docs returns
    `state=already_done` with the original provenance.
  - **Cutover NEVER deletes** the legacy doc. The inline field is
    REPLACED with `{remediated: true, storage_key, server_hash,
    remediated_at}` so legacy readers can still resolve the bytes
    while the canonical record lives in WORM storage.
  - Orphan queue: failed migrations land in
    `evidence_remediation_orphans` with `state` + `reason`; the source
    inline binary remains intact.
  - `scan_collection(...)` — convenience API for batch sweeps across a
    legacy Mongo collection.
  - `resume_pending()` — replays any saga not in a terminal state on
    boot (no in-memory state required for correctness).
- `MediaSource` value object: `legacy_collection`, `legacy_doc_id`,
  `legacy_field`, `tenant_id`, `country`, `media_type`, optional
  `registry_id` so Phase 3.4 can link `EvidenceItem` aggregates back
  to their migrated rows.
- `_extract_inline_bytes` supports four legacy shapes: raw `bytes`,
  `data:<mime>;base64,...` URLs, bare base64 strings (≥32 chars),
  `{base64: "..."}` dicts.

### Acceptance gate (Phase 3.3) — ALL GREEN
| Test (tests/test_evidence_media_remediation.py)               | Cases | Status |
| ------------------------------------------------------------- | ----- | ------ |
| Happy path: Verify → Copy → Verify → Cutover                  | 1     | ✅      |
| Idempotency: re-running is a no-op                            | 1     | ✅      |
| Dry-run leaves source intact, no provenance, no orphan rows   | 1     | ✅      |
| Missing inline field → orphan queue, source untouched         | 1     | ✅      |
| Reverify mismatch (injected fault) → orphan, source intact    | 1     | ✅      |
| Saga history is append-only with timestamp + actor per step   | 1     | ✅      |
| `scan_collection` processes every doc with the field          | 1     | ✅      |
| **Total**                                                     | **7** | **green** |

Full regression: **137 tests pass** across Phase 1 / 1A / 1C / 2A /
3.1 / 3.2 / 3.3. No mocks introduced. Lint clean.

### Outstanding (Phase 3.4-3.10)
- 🟡 **3.4 Evidence aggregate** — `evidence_id`, `registry_id`,
  `object_ref`, `hash_fingerprint`, `custody_chain` + new
  `/api/v1/evidence/*` API. **Contract bump to v1.2.0 lands here**
  (additive minor; OpenAPI/JSON Schemas/Event Catalog regenerated;
  drift gate refreshed).
- 🟡 **3.5 Sealing** — `Seal` aggregate + WORM lockdown.
- 🟡 **3.6 Locking, integrity & anchoring** — Merkle saga (CT-log
  first, OTS second, behind `AnchorPort` + `CheckpointPublisherPort`);
  DLQ + replay; resumable.
- 🟡 **3.7 Timeline & versioning** — append-only chain of custody +
  supersession lock chain.
- 🟡 **3.8 Events & projections** — 17 Evidence event types;
  rebuildable read models.
- 🟡 **3.9 SDK & React UI** — TS SDK regenerated from frozen v1.2.0;
  React pages for upload/list/detail/timeline/seal/integrity/version/
  custody.
- 🟡 **3.10 Phase Acceptance Review packet** — Phase 4 awaits
  explicit operator approval.

_Previous Phase 3.2 entry below._

---

## ⏱ 2026-06-29 — Phase 3.2 COMPLETE: PII Encryption

Shipped step 2 of Phase 3 per the binding sequence. **No
implementation creep beyond 3.2** — aggregate, sealing, anchoring,
remediation, timeline, and API surface remain blueprint-only until
their respective steps. Honors operator constraint §9 ("architectural
correctness over implementation convenience").

### Delivered
- `backend/contexts/evidence/ports/encryption.py`:
  - `EncryptionPort` Protocol — the **sole** cryptographic
    abstraction. Domain never sees `nacl` (enforced by an automated
    import-scan test).
  - `EncryptionEnvelope` value object — `kms_id`, `tenant_dek_id`,
    `country_master_kid`, `wrap_alg`, `nonce_b64`, `schema`. Stored
    verbatim next to every encrypted artifact; round-trip via
    `to_dict`/`from_dict`.
  - `BreakGlassChallenge` value object — `requesting_principal_id`,
    `requesting_role`, `request_country`, `target_country`,
    `reason_code`, `reason_detail`, `correlation_id`, and dual-auth
    fields (`second_approver_principal_id`,
    `second_approver_signature`). `is_dual_authorized()` returns true
    iff both are present.
  - `ResidencyViolation` / `BreakGlassRejected` exceptions.
- `backend/contexts/evidence/adapters/software_kms.py`:
  - First concrete adapter — XSalsa20-Poly1305 via `nacl.SecretBox`.
  - Per-country master in `evidence_country_masters` (one document
    per country, upserted via `$setOnInsert` so concurrent boots
    never replace an existing master).
  - Per-tenant DEK in `evidence_tenant_deks` (unique on
    `(tenant_id, country)`), DEK plaintext **never persisted** —
    Mongo holds only nonce + ciphertext + wrap_alg.
  - `evidence_security_incidents` collection — Break-Glass attempts
    and successes recorded BEFORE the unwrap returns (durable audit
    even if the subsequent crypto fails).
  - Operator-defined allow-list of reason codes:
    `LITIGATION_PRESERVATION_ORDER`, `REGULATOR_AUDIT`,
    `CRIMINAL_INVESTIGATION`, `DATA_SUBJECT_LEGAL_REQUEST`,
    `INTERNAL_FRAUD_REVIEW`. Anything outside is rejected at the
    port boundary.
  - Streaming encrypt/decrypt (XOR-counter per-chunk nonce derivation
    over the envelope's single stream nonce) for future Phase 3.5
    sealing of binaries.
- `main.py` composition root: `evidence_kms` constructed at startup
  with `await ensure_indexes()`; exposed via `app.state.evidence_kms`
  for Phase 3.4+ wiring.

### Acceptance gate (Phase 3.2) — ALL GREEN
| Test (tests/test_evidence_pii_encryption.py)                  | Cases | Status |
| ------------------------------------------------------------- | ----- | ------ |
| Domain/application code never imports `nacl` (file scan)      | 1     | ✅      |
| `ensure_country_master` idempotent + single-row per country   | 1     | ✅      |
| `get_or_create_tenant_dek` idempotent per (tenant, country)   | 1     | ✅      |
| Tenant DEK plaintext NEVER persisted                          | 1     | ✅      |
| Encrypt/decrypt bytes round-trip                              | 1     | ✅      |
| Encrypt/decrypt stream round-trip (multi-chunk, irregular)    | 1     | ✅      |
| Cross-country unwrap without break-glass denied               | 1     | ✅      |
| Break-Glass requires `super_admin`                            | 1     | ✅      |
| Break-Glass reason must be in allow-list                      | 1     | ✅      |
| Break-Glass records `SecurityIncident` BEFORE returning       | 1     | ✅      |
| Dual-auth fields carried through to the incident record       | 1     | ✅      |
| Tampered ciphertext fails to decrypt (Poly1305 MAC)           | 1     | ✅      |
| Envelope round-trips through dict                             | 1     | ✅      |
| `residency_country_of_async` returns DEK country              | 1     | ✅      |
| **Total**                                                     | **14**| **green** |

### Outstanding (Phase 3.3-3.10)
- 🟡 **3.3 Media remediation** — idempotent migration of legacy
  base64/binary fields → private storage via verify-then-cutover
  saga; orphan worker.
- 🟡 **3.4 Evidence aggregate** — `evidence_id`, `registry_id`,
  `object_ref`, `hash_fingerprint`, `custody_chain`. **Contract bump
  to v1.2.0 lands here** (additive minor: new endpoints, schemas,
  events; OpenAPI/JSON Schemas/event catalog regenerated; drift gate
  refreshed).
- 🟡 **3.5 Sealing** — `Seal` manifest aggregate + WORM lockdown.
- 🟡 **3.6 Locking, integrity & anchoring** — Merkle saga (CT-log
  first, OTS second, behind `AnchorPort` + `CheckpointPublisherPort`);
  DLQ + replay.
- 🟡 **3.7 Timeline & versioning** — append-only chain of custody +
  evidence supersession via lock chain.
- 🟡 **3.8 Events & projections** — fan-out read models + 17
  Evidence event types in the catalog.
- 🟡 **3.9 SDK & React Evidence UI** — TypeScript SDK regenerated
  from frozen contracts; React pages for upload/list/seal/timeline.
- 🟡 **3.10 Phase Acceptance Review** — one-page architectural
  packet (ADR refs + invariant inventory + acceptance test results +
  outstanding risks). Phase 4 does NOT auto-start.

_Previous Phase 3.1 entry below._

---

## ⏱ 2026-06-29 — Phase 3.1 COMPLETE: Evidence Storage Foundation

First step of Phase 3 ("Files & Evidence") shipped per the binding
build sequence (Storage → PII encryption → Media remediation →
Aggregate → Sealing → Locking/Integrity/Anchoring → Timeline →
Events/Projections → SDK/UI → Acceptance Review). **No
implementation creep beyond 3.1** — aggregate, sealing, anchoring,
hashing, encryption, and the API surface remain blueprint-only until
their respective step gates.

### Delivered
- `backend/contexts/evidence/{ports,adapters}/` — bounded-context
  skeleton + the two storage ports:
  - `StoragePort` Protocol — multipart streaming upload, read-back
    streaming hash (foundation for ADR-0004), WORM Object-Lock
    (apply/extend/status), remediation-only `move(verify_callback)`
    that NEVER deletes the source, canonical `StorageObjectKey` with
    strict 2-tier (`public`/`private`) layout.
  - `SignedUrlPort` Protocol — issues short-lived URLs (default 5min,
    hard cap 1h) with per-role tier clamps; binding contract that the
    audit row lands in `evidence_signed_url_audit` BEFORE the URL is
    returned. Per-issuance nonce makes every URL byte-unique.
- `LocalFsWormStorage` adapter (dev): chmod-immutable + sidecar
  `<obj>.lock.json` retention metadata; refuses to overwrite or
  re-initiate multipart on a locked key; governance-mode locks are
  rejected at the adapter (compliance mode is the only legal mode);
  forward-only retention extensions.
- `R2StorageAdapter` skeleton (production): port-clean, every method
  raises `NotImplementedError` with an explicit operator setup
  message (`R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, …). Concrete sigv4
  implementation lands when operator credentials are configured;
  callers do not change.
- `SignedUrlMotorAdapter` (reference implementation of
  `SignedUrlPort`) — HMAC-SHA-256 signed paths,
  `evidence_signed_url_audit` collection with `url_sha256` unique
  index, indexed by `evidence_id`, `principal_id`,
  `(tenant_id, issued_at desc)`.
- `main.py` wiring: composition root constructs storage + signed-URL
  ports at startup; ensure-indexes called; `app.state` exposes the
  ports for downstream Phase 3.4+ wiring.

### Acceptance gate (Phase 3.1) — ALL GREEN
| Test (tests/test_evidence_storage_foundation.py) | Cases | Status |
| ------------------------------------------------ | ----- | ------ |
| Tier strict-2-valued + key layout invariants     | 3     | ✅      |
| Multipart streaming + canonical streamed SHA-256 | 3     | ✅      |
| Independent read-back stream matches plaintext   | 1     | ✅      |
| WORM contract (overwrite-blocked, mode-rejected, forward-only) | 4 | ✅      |
| Remediation `move` preserves source bytes        | 1     | ✅      |
| R2 adapter port-clean (NotImplementedError msg)  | 1     | ✅      |
| Signed-URL TTL clamps + audit-before-return + invalid-TTL reject | 3 | ✅      |
| **Total**                                        | **16**| **green** |

Full regression: 24 pass (16 new + 8 contract-freeze). Contract drift
gate refreshed (release-manifest `git_commit` + `build_timestamp` now
normalized in the comparator to suppress commit-rotation noise while
preserving full contract drift detection).

### Phase 3 governance state
- ADRs **0003, 0004, 0005, 0006** are committed to
  `contracts/v1/adr/` and govern the rest of Phase 3 implementation.
- `/app/memory/PHASE3_SPEC.md` is the authoritative spec (annotated
  with operator-approved decisions on residency, anchor cadence,
  reservation sizes, CheckpointPublisherPort abstraction).
- Contract bump deferred until the Phase 3 API surface lands at
  Phase 3.4 — until then 3.1 is purely infrastructural (no new
  endpoints, no schema changes).

### Outstanding (Phase 3.2+)
- 🟡 **Phase 3.2 — PII encryption**: `EncryptionPort` + Software KMS
  with per-tenant DEK / per-country master + Break-Glass cross-
  country unwrap (super_admin + reason + `SecurityIncident` event +
  dual-auth design).
- 🟡 **Phase 3.3 — Media remediation**: idempotent migration of
  base64/binary from legacy Mongo docs into private storage via
  verify-then-cutover; orphan worker.
- 🟡 **Phase 3.4 — Evidence aggregate**: `evidence_id`,
  `registry_id`, `evidence_type`, `object_ref`, `hash_fingerprint`,
  `custody_chain` + API surface (contract bump to 1.2.0).
- 🟡 **Phase 3.5 — Sealing**, **3.6 — Locking/integrity/anchoring**,
  **3.7 — Timeline/versioning**, **3.8 — Events/projections**,
  **3.9 — SDK/UI**, **3.10 — Acceptance Review packet**.

_Previous Phase 2A entry below._

---

## ⏱ 2026-06-28 — Phase 2A COMPLETE: Canonical LandVault Registry

First business bounded context shipped on top of the frozen Phase 1C
platform. **Contract bumped `1.0.0 → 1.1.0`** (additive minor) per the
binding architectural authorization.

### Delivered
- **`backend/contexts/registry/`** — full DDD bounded context:
  - **Domain**: `LandVault` aggregate root (one and only authoritative
    land record), value objects (`ParcelNumber`, `Geometry`, `Origin`,
    `OwnershipType`, `LandVaultStatus`, `PropertyType`), per-command
    invariants, 5 immutable domain events.
  - **Aggregate invariants enforced**: `registry_id` / `parcel_number` /
    `tenant_id` / `country_code` / `created_at` / `origin.*` immutable;
    `version` + `schema_version` monotonic; OwnershipHistory append-only;
    archive one-way; locked-status guard.
  - **Ports**: `LandVaultRepository`, `RegistryNumberAllocator`,
    composable `LandVaultSpec`.
  - **Mongo adapters**: indexes (unique `registry_id`, unique
    `parcel_number`, sparse `legacy_aliases`, compound
    `(country_code, tenant_id, status)`, **2dsphere on `geometry`**,
    provenance index for migration idempotency); atomic
    `findOneAndUpdate $inc upsert` allocator that produced 0 duplicates
    across N=200 parallel test runs.
  - **Application service** orchestrates Mongo transaction + outbox
    publish + audit + metrics; per-role projection (`public` / `owner` /
    `privileged`).
  - **API**: `/api/v1/registry/landvaults` with task-oriented commands
    (`Create`, `UpdateLocation`, `UpdateGeometry`,
    `UpdateOwnershipContact`, `RecordOwnershipTransfer`, `UpdateSurvey`,
    `UpdateCommunityData`, `Archive`); per-role Pydantic DTOs with
    `extra=forbid` (anti mass-assignment).
  - **PDP policies** registered with the centralized authorization
    engine (5 policies + role matrix); aggregate enforces locked-state &
    tenant scope as defense-in-depth.

### Ownership-event discipline (§3)
- `registry.ownership.recorded.v1` emitted ONLY on legal ownership
  changes (`owner_name`, `ownership_type`, representative authority,
  family composition). **NOT** emitted for phone/email contact edits.
- Append-only `ownership_history[]` extended only on legal changes;
  initial registration always records the first entry.

### Migration tool (§10)
- `python -m contexts.registry.migration --commit --batch-id=…` —
  idempotent, provenance-preserving, duplicate-quarantining import from
  legacy `parcels` + `land_vault_parcels` collections.
- Aliases preserved in `legacy_aliases[]`; never authoritative.
- Quarantine collection `landvault_migration_quarantine` for
  unmappable rows (no auto-merges).

### Legacy compatibility adapter (§2)
- `POST /api/parcels` now writes through `RegistryCommandService` (the
  authoritative path) and mirrors the canonical record back into the
  legacy `parcels` collection for read-side back-compat.
- Legacy adapter normalizes legacy role names to canonical roles; ALL
  writes flow through the same aggregate, transactional outbox, audit,
  and metrics pipeline as `/api/v1/registry/*`.
- Frozen OpenAPI marks every `/api/*` non-v1 endpoint `deprecated: true`
  per the deprecation policy.

### Contract package at `1.1.0`
- 52 governed artifacts (up from 37 at `1.0.0`).
- 5 new domain events added to `v1/events/catalog.json` + per-event
  JSON Schemas: `registry.landvault.created.v1`, `…updated.v1`,
  `…parcel_reference.allocated.v1`, `…ownership.recorded.v1`,
  `…archived.v1`.
- 8 new request DTOs + 2 new response DTOs frozen as independent
  schemas under `v1/schemas/`.
- New `registry_actions` and `registry.land_vault` field-projection
  entries in `v1/security/`.
- ADR-0002 + CHANGELOG entry + new SHA256 fingerprints (drift gate
  refreshed and verified).

### Tests (Directive §12 acceptance matrix)
| Suite                                       | Cases | Status |
| ------------------------------------------- | ----- | ------ |
| Aggregate invariants                        | 22    | ✅      |
| Geometry validation                         | 6     | ✅      |
| Allocator concurrency (N=50)                | 4     | ✅      |
| Allocator stress (N=200)                    | 1     | ✅      |
| Registry API + authz matrix + tenant + 2dsphere | 14 | ✅      |
| Migration (idempotency + quarantine)        | 6     | ✅      |
| Contract drift gate                         | 8     | ✅      |
| Legacy compatibility (e2e)                  | 1     | ✅      |
| Phase 1 + 1A + 1C regression                | 44+   | ✅      |
| **Total**                                   | **106+** | **green** |

### Regression caught + fixed during testing
- Legacy `/api/parcels` returned `500` when `lga`/`ward` was a single
  character. Root cause: `MongoRegistryNumberAllocator._normalize`
  imposed no min-length floor while `ParcelNumber` regex requires ≥2
  chars per token. **Fixed** with a min-length check in `_normalize`
  and a `ValueError → 400 registry.invalid_location_token` mapping in
  the application service. Now returns RFC 7807 problem+json with the
  proper code, title, status, instance, and correlation_id.

_Previous Phase 1C entry below._

---

## ⏱ 2026-06-28 — Phase 1C COMPLETE: Platform Contract Freeze

Implemented the **AquaSavannah LandVault Platform Contract Package** at
`/app/contracts/` per the binding Phase 1C directive. The platform now
publishes a single, versioned, machine-readable source of truth for every
external contract.

### Delivered artifacts (contract version `1.0.0`)
- `contracts/VERSION` (semver pin) + `CHANGELOG.md` + `deprecation-policy.md`
- `contracts/v1/openapi.json` — frozen OpenAPI 3 for both surfaces
  (`/api/v1/*` canonical + `/api/*` deprecated)
- `contracts/v1/schemas/requests/*.json` and `responses/*.json` — every
  Phase 1 DTO frozen as an independent JSON Schema (8 request + 1 response)
- `contracts/v1/errors/*.json` — 7 RFC 7807 problem+json contracts
  (ValidationError, AuthorizationDenied, ConcurrencyConflict, NotFound,
  RateLimitExceeded, SpatialValidationError, BusinessRuleViolation)
- `contracts/v1/events/catalog.json` + 12 per-event JSON Schemas (the
  full identity.* domain event stream); event_name/version mirror
  `kernel.events.outbox.EVENT_TYPES`
- `contracts/v1/security/permissions.json`, `role_matrix.json`,
  `field_projection.json` — machine-readable authorization spec for
  the 10 canonical roles and the ABAC pattern library
- `contracts/v1/sdk/sdk.version`, `compatibility.json`, `contract.sha256`
  — SDK fingerprint for downstream generators
- `contracts/release-manifest.json` — release-level metadata (git commit,
  build timestamp, per-file SHA256, aggregate checksums)
- `contracts/v1/adr/ADR-0001-platform-contract-freeze.md`

### Governance
- `contracts/generate.py` — single source of truth. Run
  `python -m contracts.generate` to regenerate the entire tree
  deterministically (sorted keys, indent=2).
- `contracts/ci_check_drift.sh` + `backend/tests/test_contract_freeze.py`
  (8 strict assertions) — CI gate that fails on byte-level drift, missing
  canonical endpoints, untagged legacy endpoints, event-catalog/outbox
  skew, role-matrix/runtime skew, and malformed SHA fingerprints.
- All `/api/*` non-v1 routes auto-tagged `deprecated: true` + `legacy`
  in the frozen OpenAPI per the deprecation policy.
- Verified: tamper test (mutated `openapi.json`) → drift gate fired with
  remediation instructions; full backend suite still **130 passed, 2
  skipped** including 8 new contract-freeze tests.

_Original 2026-06-24 entry below._

---


## 1. Original problem statement
Build Aquasavannah LandVault — a subscription-based, production-ready web application that
serves as the **trusted evidence layer for land transactions and land history** in Nigeria.
It preserves, verifies, and makes land evidence transparent. It does NOT determine ownership.

Spec covered 13 production layers, 6 subscription tiers, role-based dashboards, credit wallet,
audit trail, trust validation, and admin command centre.

## 2. Architecture decisions (made together with user)
- **Auth:** Emergent-managed Google Auth (with a dev-login bypass for automated testing)
- **Payments:** Stripe (sandbox key already in env) **+** Paystack (sandbox stub)
- **Database:** MongoDB (in place of the spec's PostgreSQL). Equivalent RLS achieved by
  consistently filtering on `tenant_id` and using atomic `$inc` for credit ops.
- **AI/OCR:** Mocked for v1 — jobs run, return canned results
- **Stack:** React + FastAPI + MongoDB; Tailwind + shadcn/ui + lucide-react + sonner toast

## 3. User personas
1. **Citizen / Family** — primary uploader of family land evidence
2. **Community Validator** — village chairmen, family heads, traditional rulers
3. **Surveyor Partner** — registered surveyors uploading plans
4. **Legal / Due Diligence** *(routes ready, dashboard deferred)*
5. **Institutional (Bank/Corp)** *(routes ready, dashboard deferred)*
6. **Government Observer** *(routes ready, dashboard deferred)*
7. **Platform Admin** — operates the command centre

## 4. Implemented in v1 (2026-06-24)
### Backend (now modular under `/app/backend/`)
- **Phase 9 refactor complete** — monolithic 2 569-line `server.py` reduced to an 8-line shim. Full enterprise structure: `core/`, `schemas/`, `services/`, `routers/`, `webhooks/`. Zero API breaking changes. Backend version bumped 1.0.0 → 1.1.0. See `MIGRATION_REPORT.md`.
- Emergent Google Auth + `/api/auth/dev-login` test bypass
- `/api/auth/me`, `/api/auth/logout` with httpOnly session cookie + Bearer fallback
- Public: `/api/public/stats`, `/api/public/verify`, `/api/public/plans`, `/api/public/transparency`
- Parcels CRUD, evidence vault (SHA-256), community attestations (RBAC ≥ COMMUNITY_VALIDATOR)
- Surveyor assignments + survey plan upload (RBAC ≥ SURVEYOR)
- Credit wallet with atomic `$inc` deductions + idempotency keys
- **Payments (iteration 2 — env-driven):**
  - `/api/payments/config` returns `{stripe: {enabled, mode, publishable_key}, paystack: {enabled, mode, public_key}}` — secrets never leak
  - Stripe checkout via `emergentintegrations` (USD-equivalent NGN); status endpoint verifies local ledger FIRST (404 on unknown), enforces user isolation (admin override allowed)
  - **Real Paystack** integration: `POST /transaction/initialize` and `GET /transaction/verify/{ref}` via httpx with `Authorization: Bearer ${PAYSTACK_SECRET_KEY}`
  - `/api/webhook/stripe` — signature verified via `stripe.Webhook.construct_event` against `STRIPE_WEBHOOK_SECRET`
  - `/api/webhook/paystack` — HMAC-SHA512 verified against `PAYSTACK_WEBHOOK_SECRET` (or `PAYSTACK_SECRET_KEY` fallback)
  - All payment endpoints return **503 "Payment system not configured (Stripe|Paystack)"** when the provider's secret is missing — no crash, no silent failure
  - `_fulfill_payment()` idempotent (guarded by `credits_granted` flag + `idempotency_key` on credit transactions)
- Admin overview, users, parcels, evidence (approve), jobs (process), audit log
- Trust validation — **REAL sub-scores from DB counts** (no false 100s), graded A_PLUS … F
- Take-off readiness assessment
- Job queue (PENDING → PROCESSING → COMPLETED/FAILED) with mock OCR/duplicate/fraud
  and real confidence recalculation
- Audit log on every material action; timeline events per parcel
- Indexes on users.email, parcels.parcel_number, sessions.session_token, etc.

### Frontend (React)
- Landing (`/`) — split layout, hero, trust stats, six pricing cards, demo login
- Public verification (`/verify`)
- Trust architecture (`/trust`)
- Community transparency (`/community-transparency`)
- Citizen dashboard (`/dashboard`) — KPIs, parcels list, create-parcel dialog,
  evidence-upload dialog, wallet widget, activity timeline
- Validator dashboard (`/validator`) — queue + attestation form + my attestations
- Surveyor dashboard (`/surveyor`) — assignments + survey upload form + recent surveys
- Admin dashboard (`/admin`) — KPI row, trust panel, readiness panel, 13-layer health,
  tabs for users/parcels/evidence/jobs/audit, action buttons (run trust, process jobs, scan)
- Billing (`/billing`) — credit packs + plans + Stripe & Paystack checkout
- Stripe success/cancel + Paystack success polling pages

### Theme
- Green-to-blue gradient background, Plus Jakarta Sans + Inter + JetBrains Mono fonts
- Cards: `#fff` + soft green shadow, glass-morphism for stats panels
- Trust stamps and badges in custom monospace

## 5. Test coverage (iteration 1)
- Backend: **28/28** pytest tests passed (`/app/backend/tests/backend_test.py`)
- Frontend: **9/9** UI flows verified (landing, public verify, citizen/validator/surveyor/admin
  dashboards, plus form submissions and admin actions)
- Critical issues: **0**
- Minor issues: 1 (cosmetic key naming on `/api/public/stats`)

## 6. Deferred (P1)
- Phase 8 frontend dashboards for Legal / Institutional / Observer (**backend ready**, includes risk engine + real PDF report generation via job queue; only the React pages remain)
- Real Paystack integration ✅ DONE (iteration 2)
- Stripe webhook signature verification ✅ DONE (iteration 2)
- Enterprise backend refactor ✅ DONE (iteration 3 / Phase 9)
- Real OCR / fraud scoring (mocked)
- Cloudflare R2 file storage
- Rate limiting + Sentry instrumentation
- CI/CD pipeline scaffolding

## 7. Backlog (P2)
- Stripe Metered Billing for institutional plans
- Email notifications (Resend / Postmark)
- Mapbox parcel boundary visualisation
- Bulk verification API for institutional users
- Recovery test runner + scheduled backups
- Multi-region Neon read replicas (Lagos)

## 11. Phase 1 — Identity & Authorization (2026-06-26) — COMPLETE

**Scope (per Chief Architect sign-off — Decisions 1a, 2b, 3a, 4a-modified, 5-modified):**
Constitutional Platform Kernel + Identity bounded context layered alongside
the existing application. No business features migrated in Phase 1.

### Platform Kernel (`/app/backend/kernel/` — ADR-012, immutable core)
- **`kernel/config/`** — typed PlatformSettings, fail-fast load from env
- **`kernel/security/`** — RS256 JWT + JWKS publication, key rotation with
  configurable grace, bcrypt password hashing (cost 12), opaque refresh
  tokens (SHA-256-hashed at rest, 32-byte secrets, httpOnly secure cookies)
- **`kernel/persistence/`** — `ExecutionContext` ContextVar carrying the
  authenticated identity (principal/email/country/tenant/org/roles/scopes/
  session_id/correlation_id) — single source of truth per the architectural
  clarification. `BaseRepository` auto-injects tenant + country from the
  context, refuses client-supplied scope, stamps audit metadata, applies
  optimistic concurrency via `version`
- **`kernel/audit/`** — Append-only `AuditStore` (ADR-005) with monotonic
  sequence counter and SHA-256 hash chain. Transaction-wrapped chain-tip
  read + insert prevents concurrent-writer hash collisions. No update /
  delete / replace methods on the public API
- **`kernel/authorization/`** — Full PEP/PDP/PIP/PAP engine (ADR-002).
  Default-deny, fail-closed, role + attribute + tenant + country
  isolation policies. Anonymous principals limited to whitelisted public
  actions. Programmatic `enforce()` audits both PERMIT and DENY
- **`kernel/errors/`** — RFC 7807 problem+json with correlation_id (binding,
  API standards §7)
- **`kernel/observability/`** — JSON structured logs + correlation id ContextVar

### Identity bounded context (`/app/backend/contexts/identity/`)
DDD-shaped: `domain/` (User, Session, ProviderIdentity, value objects) ·
`ports/` (UserRepositoryPort, SessionRepositoryPort, IdentityProviderPort) ·
`adapters/` (Mongo* repos) · `application/` (AuthService + providers) ·
`api/` (auth_router, jwks_router, DTOs).

**Identity is the canonical authority** — User, Identity, Roles, Country,
Tenant, Organisation, Sessions, Security Policies, and Audit Metadata all
live in this context. External authentication providers are adapters behind
`IdentityProviderPort`:
- `LocalIdentityProvider` — email + bcrypt password
- `EmergentGoogleIdentityProvider` — wraps Emergent OAuth as an
  Anti-Corruption Layer (§13). Translates external profile into the
  internal `AuthenticatedSubject` type; never leaks external schema into
  the domain
- Architecture is provider-agnostic — Microsoft Entra, government IDPs,
  SAML/OIDC providers all plug in via the same port

### HTTP API (mounted under `/api/v1/auth/*`)
- `POST /v1/auth/register` — create local user, return tokens
- `POST /v1/auth/login` — local email+password
- `POST /v1/auth/login/google` — Emergent Google OAuth session exchange
- `POST /v1/auth/refresh` — rotates the refresh token; replay detection
  kills the entire session chain (token-theft heuristic)
- `POST /v1/auth/logout` — revokes the current session
- `GET  /v1/auth/me` — returns the authenticated ExecutionContext
- `GET  /.well-known/jwks.json` — public RSA verification keys for any
  future relying party (federated identity ready)

### Country handling (Decision 5 — modified)
- Country is a first-class architectural concept from day one
- `country` is a JWT claim, in the ExecutionContext, persisted on the User,
  and participates in repository scoping + authorization isolation
- Default operational country = NG; multi-country onboarding requires no
  structural code changes (only PlatformSettings + reference data)

### Coexistence with legacy
- Existing business routes (`/api/parcels`, `/api/evidence`, `/api/payments`, …)
  continue to operate unchanged via the legacy `session_token` cookie
- Phase 1 endpoints live under `/api/v1/...` so legacy + new ship side-by-side
- Legacy `/api/auth/dev-login` is preserved for the existing test suite

### Test coverage (iteration 5)
- Backend: **67 passed, 2 skipped, 0 failed** (was 51)
  - +12 Phase 1 identity flow tests (`tests/test_phase1_identity.py`)
  - +7 PDP / authorization engine unit tests (`tests/test_authorization_engine.py`)
  - +3 audit-store / hash-chain tests (`tests/test_audit_store.py`)
- Lint clean on `/app/backend/kernel` and `/app/backend/contexts`

### Operational notes
- `PLATFORM_JWT_ISSUER`, `PLATFORM_JWT_AUDIENCE`, `PLATFORM_ACCESS_TTL_SECONDS`,
  `PLATFORM_REFRESH_TTL_SECONDS`, `PLATFORM_KEY_GRACE_SECONDS`,
  `PLATFORM_DEFAULT_COUNTRY`, `PLATFORM_REFRESH_COOKIE`, `PLATFORM_COOKIE_SECURE`,
  `PLATFORM_COOKIE_SAMESITE` all configurable via env; sensible defaults baked
- Signing keys auto-generated on first startup in `kernel_signing_keys`
  collection. Call `KeyStore.rotate()` programmatically when needed
- Audit log + counter collections: `kernel_audit_log`, `kernel_audit_counters`
- Identity collections: `identity_users`, `identity_sessions`

## 12. Phase 1A — Constitutional Completion (2026-06-28) — COMPLETE

Per the Chief Architect's Phase 1 Definitive Delivery Spec sign-off (Phase 1A:
Identity / Service Accounts / Delegation / Specifications / ABAC Policy
Library / Domain Events / Business Observability / Authorization Test Matrix).

### Identity — 10-role canonical model
- `contexts/identity/domain/value_objects.Role` enum with the EXACT legacy
  set: general_user, surveyor_general, surveyor, field_agent, super_admin,
  compliance_officer, licensed_surveyor, surveyor_partner,
  community_validator, government_observer
- Named privileged role sets (`GOVERNANCE_ROLES`, `SURVEY_ROLES`,
  `COMMUNITY_ROLES`, `OBSERVER_ROLES`, `FIELD_ROLES`) for ABAC policies
- Extended `User` aggregate: phone, organization, organization_id,
  avatar_url, license_number, lga_code, role_confirmed,
  suspension_reason / suspended_by / suspended_at
- Account-status enforcement at every auth path (`User.can_authenticate()`)
- Backwards-compatible role aliases preserved during transition grace

### Service Accounts + Delegation Grants
- `contexts/identity/domain/service_account.ServiceAccount` — non-human
  principal with explicit minimal scopes, SHA-256 secret_hash (plaintext
  returned exactly once at creation), ACTIVE/REVOKED lifecycle
- `contexts/identity/domain/delegation.DelegationGrant` — time-bounded,
  revocable, audited grant of named scopes from delegator to delegate
- `IdentityAdminService` (under `contexts/identity/application/admin_service.py`)
  orchestrates suspend / activate / assign_role / create_service_account /
  revoke_service_account / grant_delegation / revoke_delegation — every
  operation publishes a versioned Domain Event + writes an audit entry +
  emits a business metric

### Repository Specification Pattern
- `kernel/persistence/specification.Specification` base class — composable
  clauses translated to Mongo filters ONLY by the repository
- `contexts/identity/ports/specifications.py`: ActiveUsersSpecification,
  SuspendedUsersSpecification, UsersByTenantSpecification,
  UsersByCountrySpecification, UsersByRoleSpecification,
  UsersByOrganizationSpecification
- `MongoUserRepository.find(spec)` / `.count(spec)` accept specifications
  — no Mongo syntax in callers

### Reusable ABAC Policy Library (`kernel/authorization/policy_library.py`)
- `create_owner_stamp_policy` — legacy CREATE: caller becomes owner via
  `stamp_owner` obligation; optional role restriction
- `owner_or_privileged_read_policy` — legacy READ pattern with optional
  field-projection obligation
- `locked_state_guard_policy` — denies owner updates on locked records
  (approved_locked, certificate_issued, evidence_sealed, audit_finalised);
  privileged roles bypass
- `role_conditional_on_status_policy` — surveyor only at assigned/in_progress,
  community_validator only at validation_pending, etc.
- `delete_super_admin_only_policy` — DELETE reserved for super_admin
- `register_demo_resource_policies()` boots the canonical policy set against
  an internal `demo` resource for the authorization test matrix

### Immutable Domain Events + Transactional Outbox
- `kernel/events/envelope.Envelope` — versioned envelope with event_id,
  event_type, event_version, aggregate_type/id/version, occurred_at,
  producer, tenant/country/org scope, correlation_id, causation_id, actor
- `kernel/events/outbox.Outbox` — `kernel_outbox` collection, atomic claim
  via `find_one_and_update`, in-process subscriber registry with glob
  pattern matching; background publisher loop started in main.py lifecycle
- Phase 1 events emitted: identity.user.registered, identity.login.success,
  identity.login.failed, identity.account.suspended, identity.account.activated,
  identity.role.assigned, identity.delegation.granted, identity.delegation.revoked,
  identity.service_account.created, identity.service_account.revoked,
  identity.session.revoked
- Broker abstraction ready — Phase 3+ swap to Kafka/Rabbit/SQS without
  touching producers or subscribers

### Business + Technical Observability (`kernel/observability/metrics.py`)
- In-process counter store mirrored to `kernel_metrics` collection
- Auto-emitted by the kernel (callers don't instrument): login_success,
  login_failed, account_lockout, authz_denial, authz_permit,
  delegation_granted, suspension, role_change, audit_event_count,
  active_sessions, revoked_sessions, policy_evaluation_time_ms (TBD)
- One-line snapshot API for dashboards

### Identity Admin API — `/api/v1/identity/*`
- `GET  /v1/identity/users?role=&country=&tenant_id=&status=` — Specifications-backed
- `POST /v1/identity/users/{id}/suspend` — body: `{reason}`
- `POST /v1/identity/users/{id}/activate`
- `POST /v1/identity/users/{id}/role` — body: `{role}` (must be one of the 10)
- `POST /v1/identity/service-accounts` — returns secret plaintext exactly once
- `POST /v1/identity/service-accounts/{id}/revoke`
- `POST /v1/identity/delegations` — `{delegator_id, delegate_id, scope, valid_from, valid_until, reason}`
- `POST /v1/identity/delegations/{id}/revoke`

### Test coverage (iteration 6)
- **122 passed, 2 skipped, 0 failed** (was 73)
  - +30 authorization test matrix tests (all 10 roles × CRUD + projection +
    isolation + locked-state + role-status gate)
  - +15 admin / service-account / delegation / specifications / events tests
- Phase 1A lint clean

### Outstanding (Phase 1B → 1D)
- **Phase 1B — Constitutional Verification review** (architecture / security
  / platform gates; documentation pass + final sign-off)
- **Phase 1C — Contract Freeze** (publish OpenAPI v1; publish event contract
  registry; contract tests in CI; freeze versions)
- **Phase 1D — Frontend SDK Compatibility Layer** (auth facade + entities/invoke
  proxy stub; legacy frontend migrates incrementally)

## 8. Known limitations
- Email/password sign-up flow not exposed in UI (Google + demo only)
- Apple / Microsoft / Facebook social buttons are visual-only placeholders
- AI/OCR is mocked (returns canned text). Replacement with Emergent integrations is P2.

## 9. P0 + P1 hardening (iteration 4 — 2026-06-25)
**P0 Tenant Isolation & Transaction Safety + P1 Worker + Reports — COMPLETE**

### Tenant Isolation (structural, RLS-equivalent)
- `core/tenant.py` — `ContextVar` carrying `tenant_id`, `bypass_tenant()` context manager
- `core/safe_db.py` — `SafeCollection` wrapper auto-injects `tenant_id` into
  every `find`/`find_one`/`count`/`update`/`delete`/`insert`/`aggregate`/`distinct`/
  `find_one_and_*` call. Unauthenticated context filters to `__NO_TENANT_CONTEXT__`
  (default-deny). Exposed as `tdb` singleton.
- `core/security.get_current_user` now calls `set_tenant(user.tenant_id)` so the
  context propagates through the entire request.
- Routers switched to `tdb`: `parcels`, `evidence`, `credits`, `notifications`,
  `dashboards.citizen`. Admin / Legal / Institution / Observer / Public routers
  continue to use the raw `db` collection for legitimate cross-tenant queries.
- 5 regression tests verify cross-tenant reads/writes/listings/dashboards/
  notifications/wallets are all blocked (`tests/test_tenant_isolation.py`).

### Transaction Safety (multi-doc ACID)
- MongoDB upgraded to a single-node replica set (`rs0`) so `start_session()` +
  `start_transaction()` engage at runtime. `mongod` supervisor command updated.
- `core/tx.py` — `atomic_transaction()` context + `run_in_transaction(coro_factory)`
  with **auto-retry on TransientTransactionError / WriteConflict** (5 retries,
  exponential backoff with jitter).
- `services/payments.deduct_credits` and `services/payments.fulfill_payment`
  now run inside `run_in_transaction()`. Conditional `balance >= amount` filter
  + idempotency-key guard prevent double spending under any race.
- 2 concurrency tests verify (a) 10 concurrent /api/parcels against a 25-credit
  wallet yields exactly 5×200 + 5×402, final balance 0 — never negative; and
  (b) idempotency-key replay does not double-charge.

### Background Worker (production async)
- `services/worker.py` — long-lived asyncio task started in FastAPI `startup`,
  stopped in `shutdown`. Polls `job_queue` every `WORKER_POLL_INTERVAL` (5s),
  claims jobs atomically via `find_one_and_update`, executes via
  `services.jobs._execute_job`. Exponential-backoff retries on failure
  (10s × 2^attempt with jitter), terminal `DEAD_LETTER` after `max_attempts`.
- Auto-routes all job types (OCR, duplicate detection, confidence recalc,
  fraud scoring, certificate generation, legal/institution reports, backup,
  audit, security scan, abuse detection, take-off, trust validation).

### Real PDF + CSV Reports (worker-generated)
- `services/trust.render_legal_report_csv` and `render_institution_report_csv`
  emit downloadable CSV artifacts alongside the existing reportlab PDFs.
- `LEGAL_REPORT` and `INSTITUTION_REPORT` job handlers store both URLs:
  `result_url` (PDF) + `csv_url` (CSV) on `db.reports`.
- `GET /api/legal/reports/{id}/download(.csv)` and
  `GET /api/institution/reports/{id}/download(.csv)` serve the artifacts
  through `FileResponse`, with role-scoped + owner-scoped access checks.

### Test coverage delta (iteration 4)
- Backend: **51 passed, 2 skipped, 0 failed** (was 38)
  - +5 tenant isolation tests
  - +2 concurrency tests
  - +6 worker + report E2E tests (`tests/test_worker_reports.py`)
- Pytest marker `tx_test` registered in `/app/backend/pytest.ini`.

### Operational notes
- `ENABLE_TEST_ENDPOINTS` env flag gates `POST /api/auth/test-bootstrap-citizen`
  and `POST /api/auth/test-set-balance` — defaults to true in dev, set to
  `false` for production deployments.
- Demo wallets are auto-topped-up to baseline (250 / 1000) on every backend
  startup, so drained-wallet flakes across pytest runs are eliminated.

## 10. Backlog (P2) — unchanged
- Scheduled automations (abuse 30m, fraud 15m, backup daily 02:00) — cron / APScheduler layer
- Real OCR / fraud scoring via Emergent integrations (awaiting user go-ahead)
- Stripe Metered Billing for institutional plans
- Email notifications (Resend / Postmark)
- Mapbox parcel boundary visualisation
- Bulk verification API for institutional users
- Cloudflare R2 file storage
- Rate limiting + Sentry instrumentation

## 11. Phase 4 — Workflow Bounded Context (in progress)

### Slice 4.0 Foundation — DELIVERED 2026-06-30 ✅
- ADR-0023 + 5 foundational aggregates (WorkflowDefinition, WorkflowInstance,
  Task, Timer, CompensationEntry).
- WorkflowEngine with full lifecycle + pure `replay_apply` (byte-identical).
- Saga composer scaffold; one minimal projection (`workflow.instance` v1).
- `echo.v1` demo workflow proves the engine end-to-end.
- Contract bumped **1.5.0 → 2.0.0** (15 new events, 5 req + 9 resp DTOs,
  17 new authorization actions, new `v1/workflow_definitions/` artifact
  family, drift gate green).
- Tests: 29 in-process + 14 public-URL probes + 8 contract freeze =
  51/51 green via testing agent (`iteration_7.json`).
- 195/195 strict DDD constitutional tests green overall.
- Phase 3 codebase untouched. Repository now FROZEN.

### Slice 4.1 — IMPLEMENTATION COMPLETE 2026-07-01 ✅ (awaiting Operator Accepted+Frozen approval)
Workflow Engine Completion — **GENERIC ORCHESTRATION INFRASTRUCTURE
ONLY** — delivered under Operator Key 2 `K2-P4-4.1-20260701-02`
(grant token `K2-P4-4.1-20260701-02-GRANT`, 2026-07-01T02:30:00Z).

Delivered:
- Real `emit_command` outbound envelopes via `CommandDispatcher` +
  durable `workflow_command_outbox` (deterministic exponential backoff,
  retry, DLQ, operator-inspectable via `list_dead_lettered()`).
- Deterministic `spawn` fan-out via `ChildSpawner` + parent-child
  registry (`workflow_child_registry`); real child `WorkflowInstance`
  per `for_each` item; `join_on_terminal` recorded for future
  business slices.
- LIFO `CompensationExecutor` triggered by
  `cancel(reason='saga_failed:*')`; generic verbs `noop` /
  `emit_command` / `record_audit`; never deletes data (emits
  corrective events only).
- `SlaEngine` schedules policy-driven escalation timers on state entry;
  advances escalation chains on `WorkflowScheduler` tick. All events
  flow through existing `workflow.timer.*` +
  `workflow.instance.transitioned` — **NO new event types**.
- `PolicyEngine` overlay on transition legality (`may_transition`,
  `required_roles`, `required_evidence_kinds`, `required_consensus`,
  SLA / escalation, RetryPolicy). Jurisdiction / country / tenant
  scope with deterministic specificity ranking.
- Notification DELIVERY infrastructure (ADR-0019 non-authoritative):
  `NotificationDispatcher` + `LogProvider` / `EmailStubProvider` /
  `SmsStubProvider`; retry + DLQ; **NO PII in delivery log**
  (addresses hashed at enqueue, payload never persisted); **NO
  business notification templates or content** — infrastructure only.
- `WorkflowScheduler` background loop (configurable tick +
  batch sizes) drives timers + command outbox + notification outbox.

Constitutional posture:
- Contract VERSION locked at **2.0.0** (unchanged; Operator §5
  requirement satisfied). Drift gate GREEN throughout.
- **No new public event types** (verified by static test).
- **No new HTTP endpoints / pydantic response DTOs / SDK
  regeneration** (verified by drift gate GREEN + version tests).
- Bounded-context isolation preserved: **static scan finds zero
  imports** from `contexts.evidence` / `contexts.registry` /
  `contexts.identity` and zero references to their collections.
- Deterministic replay preserved: `replay_apply` unchanged; every
  Slice 4.1 side-effect is a separate aggregate. End-to-end HTTP
  replay verification (`test_slice41_replay_byte_identical_via_httpx`):
  `matches_committed=true`.
- Every new service emits `kernel.audit.audit()` trails and
  `workflow_*` metrics.

Testing:
- 16 new tests (`test_phase4_slice41_workflow.py`) — 16/16 PASS.
- 106-test regression suite (Slice 4.0 + Slice 4.1 + SDK +
  contract freeze + authorization engine + matrix) — 106/106 PASS.

Slice 4.0 implementation freeze anchor
`4e472e24eb2f1c85744ef00ae061a3c71ca572fe` **remains immutable** —
Slice 4.1 work does NOT replace or modify it. Slice 4.1 freeze SHA
+ annotated tag (e.g. `phase4-slice-4.1`) pending Operator §7 item 4
approval; `SLICE_STATE.md` row 4.1 currently `In-Progress`.

**Post-implementation HALT engaged per Operator §8** — no work
performed toward Slice 4.2. No contracts / SDKs regenerated. No
other bounded-context modifications. Awaiting Operator instruction.

Deliverables:
- Acceptance Review Packet: `/app/audit/PHASE-4-SLICE-4.1-ACCEPTANCE.md`
- Acceptance Governance Validation Report:
  `/app/governance/reports/K2-P4-4.1-20260701-02-4.1-ACCEPTANCE.md`
- STEP 0 pre-flight report:
  `/app/governance/reports/K2-P4-4.1-20260701-02-4.1.md`

### Slice 4.2 — DEFERRED (requires separate Key 2)
Consent sub-context (ADR-0020).

### Slice 4.3 — DEFERRED (requires separate Key 2)
Survey Assignment (dedicated, per Operator Decision #1 in
Reconciliation §5.3).

### Slice 4.4 — DEFERRED (requires separate Key 2)
Community Validation (ADR-0020).

### Slice 4.5 — DEFERRED (requires separate Key 2)
Inheritance (ADR-0001 + ADR-0014).

### Slice 4.6 — DEFERRED (requires separate Key 2)
Infrastructure — notification projections / inbox + cross-slice
projections.

### Slice 4.7 — DEFERRED (requires separate Key 2)
SDK & React Workspace (contract v2.x pinned).
