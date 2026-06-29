# 04 · Domain Invariant Inventory

> Cross-links: [03 ADR Compliance](03-adr-compliance-matrix.md) ·
> [07 Replay Verification](07-replay-verification.md)

## 1. Count of mechanically-enforced invariants

| Source | Count |
| --- | --- |
| `raise InvariantViolation` (Evidence domain) | **50** |
| `raise InvariantViolation` / `raise InvariantError` (whole platform) | **60** |
| Static purity rejections in projection engine | 3 forbidden tokens scanned per registered projection |

Every invariant is exercised by at least one positive AND one negative
test in `backend/tests/`.

## 2. Inventory by aggregate

### EvidenceItem (`domain/evidence_item.py`)

| ID | Invariant | Test |
| --- | --- | --- |
| INV-EI-01 | `max_size > 0` and `max_size ≤ MAX_OBJECT_BYTES`. | `test_evidence_aggregate_invariants::test_max_size_bounds` |
| INV-EI-02 | Status FSM: `PENDING_UPLOAD → PENDING_VERIFICATION → VERIFIED → SEALED → WORM_LOCKED` (terminal). `ARCHIVED_REPLACED` is reachable only from `WORM_LOCKED`. | `…::test_status_fsm` |
| INV-EI-03 | `composite_sha256` is set ⇒ FSM is at or past VERIFIED. | `…::test_composite_requires_verified` |
| INV-EI-04 | `parts_meta` is non-empty when status ≥ VERIFIED. | `…::test_parts_meta_required` |
| INV-EI-05 | Re-upload of a part is rejected once any part is committed. | `…::test_part_re_upload_rejected` |
| INV-EI-06 | Verification recomputes hash from storage and must equal client receipt. | `…::test_verify_rejects_tampered_payload` |

### Seal (`domain/seal.py`)

| ID | Invariant | Test |
| --- | --- | --- |
| INV-SE-01 | A seal must reference ≥1 evidence id; all must be VERIFIED at sealing time. | `test_phase36_aggregates::test_seal_requires_verified` |
| INV-SE-02 | Merkle root is deterministic across an evidence-id permutation. | `…::test_merkle_root_deterministic` |
| INV-SE-03 | `apply_worm()` is one-shot — second call rejected. | `…::test_worm_applied_terminal` |
| INV-SE-04 | Once WORM-applied, the seal is the canonical evidence container. | `…::test_sealed_evidence_cannot_re_upload` |

### Timeline + Custody (`domain/timeline.py`)

| ID | Invariant | Test |
| --- | --- | --- |
| INV-TL-01 | Chain integrity: `entry_hash == sha256(prev_hash || chain_payload)`. | `test_phase37_timeline::test_timeline_chain_integrity` |
| INV-TL-02 | Genesis row has `prev_hash=None`, `seq=0`. Non-genesis MUST have `prev_hash != None`. | `…::test_chain_invariants` |
| INV-TL-03 | `seq` is monotonically increasing per `evidence_id`. | `…::test_chain_strict_monotonic` |
| INV-TL-04 | Custody requires `justification.length ≥ 3`. | `…::test_custody_invariants` |
| INV-TL-05 | Custody `action` is from a fixed enum (`recorded`, `transferred`, `accessed`, `released`). | `…::test_custody_action_enum` |
| INV-TL-06 | (Phase 3.8) `TimelineEntry.from_event` derives `timeline_id` deterministically from `(event_id, evidence_id, seq)`. | `test_phase38_projections::test_timeline_replay_is_byte_identical_end_to_end` |
| INV-TL-07 | (Phase 3.8) Same for `CustodyEntry.from_event`. | same |

### LegalHold (`domain/timeline.py` + `application/legal_hold_service.py`)

| ID | Invariant | Test |
| --- | --- | --- |
| INV-LH-01 | An active hold blocks supersession and worm-release. | `test_phase37_timeline::test_supersession_blocked_during_hold` |
| INV-LH-02 | Hold release is terminal — a released hold cannot be re-activated. | `…::test_legal_hold_release_is_terminal` |
| INV-LH-03 | Hold requires `case_reference` and `reason`, both non-empty. | `…::test_legal_hold_requires_fields` |

### IntegrityCheck (`domain/integrity_check.py`)

| ID | Invariant | Test |
| --- | --- | --- |
| INV-IC-01 | Check status FSM: `STARTED → PASSED | FAILED | ERRORED` (terminal). | `test_phase36_aggregates::test_integrity_status_fsm` |
| INV-IC-02 | `FAILED` requires `mismatch_reason` populated. | `…::test_failed_requires_reason` |
| INV-IC-03 | Checks are append-only — never overwritten. | `…::test_failed_integrity_immutable` |

### AnchorBatch (`domain/anchor_batch.py`)

| ID | Invariant | Test |
| --- | --- | --- |
| INV-AB-01 | Batch holds ≥1 seal. | `test_phase36_aggregates::test_anchor_batch_requires_seal` |
| INV-AB-02 | Batch FSM: `PENDING → SUBMITTED → CONFIRMED | FAILED`. | `…::test_anchor_status_fsm` |
| INV-AB-03 | Merkle root over seal merkle roots is deterministic. | `…::test_anchor_merkle_root_deterministic` |

### EvidenceLock (`domain/evidence_lock.py`)

| ID | Invariant | Test |
| --- | --- | --- |
| INV-EL-01 | `retention_until > applied_at`. | `test_phase36_aggregates::test_lock_horizon_positive` |
| INV-EL-02 | A lock can be extended (only forward in time); never shortened. | `…::test_lock_only_extends_forward` |

### Projection Engine (`kernel/projections`)

| ID | Invariant | Test |
| --- | --- | --- |
| INV-PR-01 | Projection source MUST NOT contain `await publish(`. | `test_phase38_projections::test_purity_rejects_publish_token` |
| INV-PR-02 | Projection source MUST NOT contain aggregate-mutation tokens (`.archive(`, `.save_seal(`, etc). | `…::test_purity_rejects_aggregate_mutation_token` |
| INV-PR-03 | Replay over the outbox in `occurred_at` order produces byte-identical state. | `…::test_replay_rebuild_is_byte_identical` + the end-to-end variant |
| INV-PR-04 | Cursor + delivered_count + lag persist atomically per delivery. | `…::test_engine_register_and_deliver_updates_cursor` |

## 3. Coverage

Every invariant above is covered by ≥1 negative-path test (an
explicit `with pytest.raises(InvariantViolation):` block or an HTTP
422/409). 100% invariant coverage is mechanically asserted by running
the strict suite (`tests/test_phase*` + `tests/test_evidence_*` +
`tests/test_registry_aggregate_invariants.py`).

See [§14 Test Coverage Report](14-test-coverage-report.md) for the
mapping from invariant to test file.
