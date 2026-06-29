"""Phase 3.6 — EvidenceLock + EvidenceIntegrityCheck + AnchorBatch invariants."""
from __future__ import annotations

import hashlib

import pytest

from contexts.evidence.domain.anchor_batch import (
    AnchorBatch,
    AnchorProvider,
    BatchState,
)
from contexts.evidence.domain.chain import compute_entry_hash, verify_chain
from contexts.evidence.domain.evidence_lock import EvidenceLock, LockMode
from contexts.evidence.domain.integrity_check import (
    EvidenceIntegrityCheck,
    IntegrityOutcome,
    IntegrityTrigger,
)
from contexts.evidence.domain.invariants import (
    ImmutableFieldError,
    InvariantViolation,
    TransitionError,
)

H1 = "a" * 64
H2 = "b" * 64
H3 = "c" * 64
FUTURE_1 = "2125-01-01T00:00:00+00:00"
FUTURE_2 = "2126-01-01T00:00:00+00:00"


# ============================================================================
# EvidenceLock invariants
# ============================================================================

def _new_lock(**overrides) -> EvidenceLock:
    return EvidenceLock.create(
        evidence_id="evd_" + "1" * 32,
        seal_id="sea_" + "1" * 32,
        tenant_id="t", country_code="NG",
        storage_provider="local_fs_worm",
        storage_locator="private/t/2026/06/29/evd_x/final",
        retention_until=FUTURE_1, applied_by="usr_admin",
        **overrides,
    )


def test_lock_create_emits_applied_event() -> None:
    lock = _new_lock()
    types = [e.event_type for e in lock.pull_events()]
    assert types == ["evidence.lock.applied"]
    assert lock.mode == LockMode.COMPLIANCE.value
    assert lock.version == 1


def test_lock_rejects_non_compliance_mode() -> None:
    with pytest.raises(InvariantViolation):
        _new_lock(mode="governance")


def test_lock_extend_retention_is_forward_only() -> None:
    lock = _new_lock()
    lock.pull_events()
    lock.extend_retention(new_until=FUTURE_2, by="usr_admin",
                            reason="court order")
    assert lock.retention_until == FUTURE_2
    assert len(lock.extensions) == 1
    assert lock.extensions[0]["previous_until"] == FUTURE_1
    types = [e.event_type for e in lock.pull_events()]
    assert types == ["evidence.lock.extended"]


def test_lock_extend_rejects_backward_retention() -> None:
    lock = _new_lock()
    with pytest.raises(ImmutableFieldError):
        lock.extend_retention(new_until="2024-01-01T00:00:00+00:00",
                                by="x", reason="r")


def test_lock_extend_rejects_equal_retention() -> None:
    lock = _new_lock()
    with pytest.raises(ImmutableFieldError):
        lock.extend_retention(new_until=FUTURE_1, by="x", reason="r")


def test_lock_to_state_roundtrip() -> None:
    lock = _new_lock()
    state = lock.to_state()
    rehydrated = EvidenceLock.from_state(state)
    assert rehydrated.lock_id == lock.lock_id
    assert rehydrated.retention_until == lock.retention_until


# ============================================================================
# EvidenceIntegrityCheck chain invariants
# ============================================================================

def _new_check(**overrides) -> EvidenceIntegrityCheck:
    kwargs = dict(evidence_id="evd_" + "1" * 32,
                   tenant_id="t", country_code="NG",
                   triggered_by=IntegrityTrigger.SCHEDULED.value,
                   expected_hash=H1, seq=0, prev_hash=None)
    kwargs.update(overrides)
    return EvidenceIntegrityCheck.start(**kwargs)


def test_integrity_check_initial_state_is_running() -> None:
    check = _new_check()
    assert check.outcome == IntegrityOutcome.RUNNING.value
    assert check.seq == 0
    assert check.prev_hash is None
    assert len(check.entry_hash) == 64


def test_integrity_check_genesis_requires_prev_hash_none() -> None:
    with pytest.raises(InvariantViolation):
        _new_check(seq=0, prev_hash=H1)


def test_integrity_check_non_genesis_requires_prev_hash() -> None:
    with pytest.raises(InvariantViolation):
        _new_check(seq=1, prev_hash=None)


def test_integrity_check_invalid_trigger_rejected() -> None:
    with pytest.raises(InvariantViolation):
        _new_check(triggered_by="bogus")


def test_integrity_record_pass_requires_match() -> None:
    check = _new_check()
    check.pull_events()
    check.record_pass(observed_hash=H1)
    assert check.outcome == IntegrityOutcome.PASS.value
    types = [e.event_type for e in check.pull_events()]
    assert types == ["evidence.integrity.passed"]


def test_integrity_record_pass_rejects_hash_drift() -> None:
    check = _new_check()
    with pytest.raises(InvariantViolation):
        check.record_pass(observed_hash=H2)


def test_integrity_record_fail_emits_event() -> None:
    check = _new_check()
    check.pull_events()
    check.record_fail(observed_hash=H2, reason="drift")
    assert check.outcome == IntegrityOutcome.FAIL.value
    types = [e.event_type for e in check.pull_events()]
    assert types == ["evidence.integrity.failed"]


def test_integrity_check_terminal_state_is_one_way() -> None:
    check = _new_check()
    check.record_pass(observed_hash=H1)
    with pytest.raises(TransitionError):
        check.record_fail(observed_hash=H2, reason="x")
    with pytest.raises(TransitionError):
        check.record_pass(observed_hash=H1)
    with pytest.raises(TransitionError):
        check.record_error(error_summary="x")


def test_integrity_chain_helper_verifies_genuine_chain() -> None:
    # Build a hand-crafted 3-link chain and verify.
    payloads = [
        {"check_id": "c0", "x": 0},
        {"check_id": "c1", "x": 1},
        {"check_id": "c2", "x": 2},
    ]
    chain = []
    prev = None
    for seq, p in enumerate(payloads):
        entry_hash = compute_entry_hash(prev, p)
        chain.append({**p, "seq": seq, "prev_hash": prev,
                       "entry_hash": entry_hash})
        prev = entry_hash
    assert verify_chain(chain,
                          payload_fields=["check_id", "x"]) is True
    # Tamper with one entry — verification fails.
    tampered = list(chain)
    tampered[1] = {**tampered[1], "x": 999}
    assert verify_chain(tampered, payload_fields=["check_id", "x"]) is False


# ============================================================================
# AnchorBatch FSM invariants
# ============================================================================

def _new_batch(provider_id: str = AnchorProvider.CTLOG_INTERNAL.value,
                seals: list[dict] | None = None) -> AnchorBatch:
    return AnchorBatch.create(
        provider_id=provider_id, tenant_id="t", country_code="NG",
        seals=seals or [
            {"seal_id": "sea_" + "1" * 32, "merkle_root": H1},
            {"seal_id": "sea_" + "2" * 32, "merkle_root": H2},
        ],
    )


def test_anchor_batch_initial_state_pending() -> None:
    b = _new_batch()
    assert b.state == BatchState.PENDING_BATCH.value
    assert b.attempts == 0
    assert b.merkle_root


def test_anchor_batch_requires_seals() -> None:
    with pytest.raises(InvariantViolation):
        AnchorBatch.create(provider_id="ctlog_internal", tenant_id="t",
                            country_code="NG", seals=[])


def test_anchor_batch_rejects_unknown_provider() -> None:
    with pytest.raises(InvariantViolation):
        _new_batch(provider_id="bogus_provider")


def test_anchor_batch_rejects_duplicate_seal() -> None:
    with pytest.raises(InvariantViolation):
        _new_batch(seals=[
            {"seal_id": "sea_dup", "merkle_root": H1},
            {"seal_id": "sea_dup", "merkle_root": H2},
        ])


def test_anchor_batch_root_is_set_equivalent() -> None:
    a = _new_batch(seals=[
        {"seal_id": "sea_a", "merkle_root": H1},
        {"seal_id": "sea_b", "merkle_root": H2},
        {"seal_id": "sea_c", "merkle_root": H3},
    ])
    b = _new_batch(seals=[
        {"seal_id": "sea_c", "merkle_root": H3},
        {"seal_id": "sea_a", "merkle_root": H1},
        {"seal_id": "sea_b", "merkle_root": H2},
    ])
    assert a.merkle_root == b.merkle_root


def test_anchor_batch_fsm_happy_path() -> None:
    b = _new_batch()
    b.mark_sealed()
    assert b.state == BatchState.SEALED.value
    b.mark_submitted(provider_request_id="42")
    assert b.state == BatchState.SUBMITTED.value
    assert b.attempts == 1
    b.mark_confirming()
    assert b.state == BatchState.CONFIRMING.value
    b.mark_confirmed(inclusion_proofs={"sea_x": {"path": []}})
    assert b.state == BatchState.CONFIRMED.value


def test_anchor_batch_illegal_transition_rejected() -> None:
    b = _new_batch()
    with pytest.raises(TransitionError):
        b.mark_submitted(provider_request_id="x")  # must be sealed first
    b.mark_sealed()
    with pytest.raises(TransitionError):
        b.mark_confirmed(inclusion_proofs={"x": {}})


def test_anchor_batch_dlq_is_terminal() -> None:
    b = _new_batch()
    b.mark_sealed()
    b.mark_submitted(provider_request_id="x")
    # Fail then DLQ
    b.mark_failed(reason="oops", next_attempt_at=None, transient=False)
    b.mark_dead_letter(reason="permanent")
    assert b.state == BatchState.DEAD_LETTER.value
    # Subsequent state changes other than replay-marker are blocked.
    with pytest.raises(ImmutableFieldError):
        b.mark_submitted(provider_request_id="y")
    with pytest.raises(ImmutableFieldError):
        b.mark_confirmed(inclusion_proofs={"x": {}})


def test_anchor_batch_confirmed_is_terminal() -> None:
    b = _new_batch()
    b.mark_sealed()
    b.mark_submitted(provider_request_id="x")
    b.mark_confirming()
    b.mark_confirmed(inclusion_proofs={"sea_x": {"p": "x"}})
    with pytest.raises(ImmutableFieldError):
        b.mark_failed(reason="x", next_attempt_at=None)


def test_anchor_batch_replay_marker_is_write_once() -> None:
    b = _new_batch()
    b.mark_sealed()
    b.mark_submitted(provider_request_id="x")
    b.mark_failed(reason="x", next_attempt_at=None, transient=False)
    b.mark_dead_letter(reason="x")
    b.mark_replay_initiated(new_batch_id="bch_new")
    with pytest.raises(ImmutableFieldError):
        b.mark_replay_initiated(new_batch_id="bch_another")


def test_anchor_batch_inclusion_proofs_write_once() -> None:
    b = _new_batch()
    b.mark_sealed()
    b.mark_submitted(provider_request_id="x")
    b.mark_confirming()
    b.mark_confirmed(inclusion_proofs={"sea_x": {"p": "x"}})
    # Already terminal — further mutation refused.
    with pytest.raises(ImmutableFieldError):
        b.mark_confirmed(inclusion_proofs={"sea_y": {"p": "y"}})


def test_anchor_batch_events_emitted_per_transition() -> None:
    b = _new_batch()
    b.mark_sealed()
    b.mark_submitted(provider_request_id="x")
    b.mark_confirming()
    b.mark_confirmed(inclusion_proofs={"sea_x": {"p": "x"}})
    types = [e.event_type for e in b.pull_events()]
    assert "evidence.anchor.batched" in types
    assert "evidence.anchor.submitted" in types
    assert "evidence.anchor.confirmed" in types


def test_anchor_batch_state_roundtrip() -> None:
    b = _new_batch()
    b.mark_sealed()
    state = b.to_state()
    re = AnchorBatch.from_state(state)
    assert re.batch_id == b.batch_id
    assert re.merkle_root == b.merkle_root
    assert re.state == b.state
