# 03 · ADR Compliance Matrix

> Cross-links: [02 Architecture Review](02-architecture-review.md) ·
> [04 Domain Invariants](04-domain-invariant-inventory.md) ·
> [06 Contract Verification](06-contract-verification.md)

Every ADR-0001 → ADR-0010 binding rule is enumerated with the
mechanical evidence and test reference. **All 10 ADRs PASS** their
binding rules. Residual risks are listed at the end.

Legend: ✅ pass · ⚠ partial · ❌ fail

---

## ADR-0001 — Platform Contract Freeze

| # | Binding rule | Evidence | Test | Status |
| - | --- | --- | --- | --- |
| 1.1 | All public artifacts come from a deterministic generator (`contracts/generate.py`). | 98 artifacts emitted by single command. | `tests/test_contract_freeze.py::test_contract_package_has_no_drift` | ✅ |
| 1.2 | Disk content matches generator output byte-for-byte. | Drift gate green at v1.5.0. | `…::test_every_artifact_is_committed` | ✅ |
| 1.3 | Version + sha pinned in `contracts/v1/sdk/compatibility.json`. | Manifest present; sha-256 over every artifact. | `…::test_compatibility_manifest_*` | ✅ |
| 1.4 | The SDK pins to the same version + sha. | `frontend/src/sdk/meta.ts` constants match the manifest. | `tests/test_sdk_consistency.py::test_sdk_meta_matches_compatibility_manifest` | ✅ |

## ADR-0002 — Canonical LandVault Registry

| # | Binding rule | Evidence | Test | Status |
| - | --- | --- | --- | --- |
| 2.1 | LandVault is the single source of truth for parcels. | `contexts/registry` aggregates own state. | `tests/test_registry_aggregate_invariants.py::*` | ✅ |
| 2.2 | Location tokens are validated (≥2 chars per component). | `invariants.py::validate_location_token`. | `…::test_invalid_location_token_rejected` | ✅ |
| 2.3 | Ownership recorded as an event, not as a mutation. | `registry.ownership.recorded.v1` in catalog. | `…::test_ownership_recorded_event_emitted` | ✅ |

## ADR-0003 — Evidence Bounded Context

| # | Binding rule | Evidence | Test | Status |
| - | --- | --- | --- | --- |
| 3.1 | Evidence is its own bounded context — no cross-context aggregate access. | `contexts/evidence/domain` has no import from `contexts/identity` or `contexts/registry`. | grep + import discipline | ✅ |
| 3.2 | Cross-context coupling is via published events only. | All inter-context flow goes through `kernel/events/outbox`. | `tests/test_evidence_e2e.py` | ✅ |

## ADR-0004 — Server-side Hashing

| # | Binding rule | Evidence | Test | Status |
| - | --- | --- | --- | --- |
| 4.1 | Composite SHA-256 is computed server-side from stored bytes. | `evidence_service.py::_compose_streamed_hash`. | `tests/test_evidence_storage_foundation.py::test_streamed_sha_matches_server_compute` | ✅ |
| 4.2 | Client-provided `streamed_sha256` is only a wire-level receipt, never authoritative. | `verify()` recomputes from disk. | `…::test_verify_rejects_tampered_payload` | ✅ |
| 4.3 | Frontend MUST NOT compute authoritative hashes. | `EvidenceUpload.jsx` forwards server receipt. | `tests/test_sdk_consistency.py::test_evidence_pages_never_call_fetch_or_axios_directly` (purity) | ✅ |

## ADR-0005 — Merkle Anchor Saga

| # | Binding rule | Evidence | Test | Status |
| - | --- | --- | --- | --- |
| 5.1 | Seals are anchored in batches; batches embed a Merkle root. | `anchor_batch.py::compute_merkle_root`. | `tests/test_phase36_aggregates.py::test_merkle_root_deterministic` | ✅ |
| 5.2 | Anchoring is a resumable saga (idempotent at every step). | `anchor_saga.py` retries are idempotent. | `…::test_anchor_saga_resume_after_crash` | ✅ |
| 5.3 | OTS + internal CT-log produce independent proofs. | Two adapters: `ots_v1.py`, `ctlog_internal.py`. | `tests/test_phase36_e2e.py::test_ots_and_ctlog_both_emit_proof` | ✅ |

## ADR-0006 — Legal Hold + Remediation

| # | Binding rule | Evidence | Test | Status |
| - | --- | --- | --- | --- |
| 6.1 | A legal hold blocks deletion + supersession until released. | `legal_hold_service.py::ensure_no_active_hold`. | `tests/test_phase37_timeline.py::test_supersession_blocked_during_hold` | ✅ |
| 6.2 | Release is itself immutable — stored with reason + actor + timestamp. | `legal_hold.release()` is one-shot. | `…::test_legal_hold_release_is_terminal` | ✅ |

## ADR-0007 — Evidence Aggregate + Sealing

| # | Binding rule | Evidence | Test | Status |
| - | --- | --- | --- | --- |
| 7.1 | The aggregate enforces FSM on `status`. | `evidence_item.py::_assert_transition`. | `tests/test_evidence_aggregate_invariants.py::test_status_fsm` | ✅ |
| 7.2 | Once `SEALED`, the aggregate cannot change bytes. | `seal_service.seal()` requires VERIFIED → SEALED. | `…::test_sealed_evidence_cannot_re_upload` | ✅ |
| 7.3 | Seal stores deterministic merkle root over its evidence ids + composite hashes. | `seal.py::compute_merkle_root`. | `tests/test_phase36_aggregates.py::test_seal_root_deterministic` | ✅ |
| 7.4 | WORM-applied is terminal — seal status cannot reverse. | `seal.apply_worm()` rejects double-apply. | `…::test_worm_applied_terminal` | ✅ |

## ADR-0008 — Anchoring + Integrity Saga

| # | Binding rule | Evidence | Test | Status |
| - | --- | --- | --- | --- |
| 8.1 | Periodic integrity checks recompute composite hash and assert equality. | `integrity_service.py::run_check`. | `tests/test_phase36_aggregates.py::test_integrity_check_recomputes` | ✅ |
| 8.2 | A failed integrity check records mismatch_reason; never overwrites prior checks. | `evidence_integrity_checks` is append-only. | `…::test_failed_integrity_immutable` | ✅ |
| 8.3 | CT-log checkpoint is signed and append-only. | `ctlog_internal.py::publish_checkpoint`. | `tests/test_phase36_e2e.py::test_ctlog_append_only` | ✅ |

## ADR-0009 — Timeline / Custody / Legal-Hold / Supersession

| # | Binding rule | Evidence | Test | Status |
| - | --- | --- | --- | --- |
| 9.1 | Timeline + Custody are append-only chained logs (`prev_hash` → `entry_hash`). | `chain.py::compute_entry_hash`. | `tests/test_phase37_timeline.py::test_timeline_chain_integrity` | ✅ |
| 9.2 | Genesis row has `prev_hash=None`; all non-genesis MUST have `prev_hash != None`. | Asserted in `TimelineEntry.create / from_event`. | `…::test_chain_invariants` | ✅ |
| 9.3 | Superseded evidence is **never** hidden; the chain remains queryable. | `supersession_chain` endpoint returns full history. | `…::test_supersession_chain_complete` | ✅ |
| 9.4 | Custody requires non-empty justification + valid action. | Invariants in `CustodyEntry.create / from_event`. | `…::test_custody_invariants` | ✅ |

## ADR-0010 — Projection Engine + Read Models (Phase 3.8)

| # | Binding rule | Evidence | Test | Status |
| - | --- | --- | --- | --- |
| 10.1 | Projections contain ZERO business logic. | Static check in `assert_projection_purity`. | `tests/test_phase38_projections.py::test_purity_rejects_*` | ✅ |
| 10.2 | Projections never mutate aggregates / publish commands. | Forbidden-token scan over class source. | `…::test_purity_rejects_aggregate_mutation_token` | ✅ |
| 10.3 | Every projection has `reset()` + is rebuildable. | `TimelineProjector.reset()` deletes both projection collections. | `…::test_replay_after_reset_full_state` | ✅ |
| 10.4 | Full delete + replay produces byte-identical state. | End-to-end test rebuilds 1,675 events → identical rows. | `…::test_timeline_replay_is_byte_identical_end_to_end` | ✅ |
| 10.5 | Cursor + lag tracked atomically per delivery. | `kernel_projection_cursors` upserted in wrapper. | `…::test_lag_metric_reflects_undelivered_events` | ✅ |
| 10.6 | Admin endpoints super_admin only. | `enforce("kernel.projections.admin")`. | `…::test_admin_projections_denies_non_super_admin` | ✅ |

---

## Residual risks per ADR

| ADR | Residual risk | Tracked in |
| --- | --- | --- |
| 0001 | A future contract bump without regeneration would slip past the CI drift gate only if the gate itself is disabled. Mitigation: gate runs unconditionally in `tests/test_contract_freeze.py`. | [§15 R-1](15-outstanding-risks.md) |
| 0004 | Browser CSP not yet hardened to prevent malicious JS from intercepting upload bytes pre-Network. | [§15 R-2](15-outstanding-risks.md) |
| 0005 | OTS network adapter currently runs in `dry-run=fast` for the dev cluster; a real public submission flow is gated by ops. | [§15 R-3](15-outstanding-risks.md) |
| 0010 | The purity check is a source-token scan; a sufficiently determined author could obfuscate the call. The binding governance is still the test suite and ADR-0010 itself, not the static check. | Acceptable — documented in ADR-0010. |

All other ADRs have no open residual risks for production readiness.
