"""Phase 3.4 + 3.5 — EvidenceItem + Seal aggregate invariant tests.

Pure-Python tests against the domain layer. No Mongo, no HTTP, no PEP.
"""
from __future__ import annotations

import pytest

from contexts.evidence.domain.evidence_item import EvidenceItem
from contexts.evidence.domain.invariants import (
    ConcurrencyConflict,
    HashMismatchError,
    ImmutableFieldError,
    InvariantViolation,
    SealedItemError,
    TransitionError,
)
from contexts.evidence.domain.seal import Seal
from contexts.evidence.domain.value_objects import (
    EvidenceKind,
    EvidenceSourceSystem,
    EvidenceStatus,
    Origin,
    SealStatus,
    canonical_json_hash,
    compute_merkle_root,
)

H1 = "a" * 64
H2 = "b" * 64
H3 = "c" * 64


def _origin() -> Origin:
    return Origin(source_system=EvidenceSourceSystem.NATIVE.value)


def _new_item(*, kind: str = EvidenceKind.DOCUMENT.value,
              client_hash_claim=None) -> EvidenceItem:
    return EvidenceItem.create(
        registry_id="reg_" + "0" * 32,
        tenant_id="t_test", country_code="NG",
        kind=kind, created_by="usr_creator",
        origin=_origin(), media_type="application/pdf",
        client_hash_claim=client_hash_claim,
    )


# ---- EvidenceItem invariants -------------------------------------------

def test_evidence_create_initial_state_is_pending_upload() -> None:
    item = _new_item()
    assert item.status == EvidenceStatus.PENDING_UPLOAD.value
    assert item.version == 1
    assert item.evidence_id.startswith("evd_")
    assert len(item.evidence_id) == len("evd_") + 32


def test_evidence_invalid_kind_is_rejected() -> None:
    with pytest.raises(InvariantViolation):
        EvidenceItem.create(
            registry_id="reg_x", tenant_id="t", country_code="NG",
            kind="bogus_kind", created_by="u", origin=_origin(),
        )


def test_evidence_invalid_client_hash_claim_is_rejected() -> None:
    with pytest.raises(ValueError):
        _new_item(client_hash_claim="not-hex")


def test_evidence_fsm_happy_path() -> None:
    item = _new_item()
    item.attach_upload_session(upload_id="up_1", media_type="application/pdf")
    item.mark_uploaded(
        storage_locator="private/t_test/2026/06/29/" + item.evidence_id + "/final",
        storage_provider="local_fs_worm", size_bytes=1024,
        streamed_sha256=H1, media_type="application/pdf",
        actor="u",
    )
    assert item.status == EvidenceStatus.PENDING_VERIFICATION.value
    item.verify_hash(readback_sha256=H1, actor="u")
    assert item.status == EvidenceStatus.VERIFIED.value
    assert item.server_hash == H1
    assert item.hash_verified is True
    # `evidence.item.uploaded.v1` + `evidence.item.hash_verified.v1` queued.
    events = item.pull_events()
    types = [e.event_type for e in events]
    assert "evidence.item.uploaded" in types
    assert "evidence.item.hash_verified" in types


def test_evidence_verify_requires_pending_verification() -> None:
    item = _new_item()
    with pytest.raises(TransitionError):
        item.verify_hash(readback_sha256=H1, actor="u")


def test_evidence_streamed_vs_readback_mismatch_rolls_back_to_pending_upload() -> None:
    item = _new_item()
    item.attach_upload_session(upload_id="up", media_type="application/pdf")
    item.mark_uploaded(storage_locator="x", storage_provider="local_fs_worm",
                        size_bytes=1, streamed_sha256=H1,
                        media_type="application/pdf", actor="u")
    with pytest.raises(HashMismatchError):
        item.verify_hash(readback_sha256=H2, actor="u")
    assert item.status == EvidenceStatus.PENDING_UPLOAD.value
    assert item.server_hash is None
    assert item.server_hash_streamed is None
    assert item.storage_locator is None
    types = [e.event_type for e in item.pull_events()]
    assert "evidence.item.hash_mismatch" in types


def test_evidence_client_claim_mismatch_is_rejected() -> None:
    item = _new_item(client_hash_claim=H1)
    item.attach_upload_session(upload_id="up", media_type="application/pdf")
    item.mark_uploaded(storage_locator="x", storage_provider="local_fs_worm",
                        size_bytes=1, streamed_sha256=H2,
                        media_type="application/pdf", actor="u")
    # readback agrees with the SERVER stream, but disagrees with the CLIENT claim.
    with pytest.raises(HashMismatchError):
        item.verify_hash(readback_sha256=H2, actor="u")
    types = [e.event_type for e in item.pull_events()]
    assert "evidence.item.hash_mismatch" in types
    assert item.status == EvidenceStatus.PENDING_UPLOAD.value


def test_evidence_immutable_fields_after_creation() -> None:
    item = _new_item()
    initial = (item.evidence_id, item.registry_id, item.tenant_id,
               item.country_code, item.kind, item.created_at)
    item.attach_upload_session(upload_id="up", media_type="application/pdf")
    item.mark_uploaded(storage_locator="x", storage_provider="p",
                        size_bytes=1, streamed_sha256=H1,
                        media_type="application/pdf", actor="u")
    after = (item.evidence_id, item.registry_id, item.tenant_id,
             item.country_code, item.kind, item.created_at)
    assert initial == after


def test_evidence_sealed_blocks_all_mutations() -> None:
    item = _drive_to_verified()
    item.attach_to_seal(seal_id="sea_" + "f" * 32, actor="u")
    assert item.status == EvidenceStatus.SEALED.value
    # Any subsequent mutation must raise SealedItemError.
    with pytest.raises(SealedItemError):
        item.mark_uploaded(storage_locator="x", storage_provider="p",
                            size_bytes=1, streamed_sha256=H1,
                            media_type="application/pdf", actor="u")
    with pytest.raises(SealedItemError):
        item.verify_hash(readback_sha256=H1, actor="u")
    with pytest.raises(SealedItemError):
        item.attach_upload_session(upload_id="up2", media_type="application/pdf")


def test_evidence_attach_to_seal_requires_verified() -> None:
    item = _new_item()
    with pytest.raises(TransitionError):
        item.attach_to_seal(seal_id="sea_x", actor="u")


def test_evidence_attach_to_seal_is_idempotent_same_id() -> None:
    item = _drive_to_verified()
    item.attach_to_seal(seal_id="sea_aaa", actor="u")
    v1 = item.version
    item.attach_to_seal(seal_id="sea_aaa", actor="u")  # noop
    assert item.version == v1


def test_evidence_attach_to_seal_rejects_second_seal() -> None:
    item = _drive_to_verified()
    item.attach_to_seal(seal_id="sea_aaa", actor="u")
    with pytest.raises(ImmutableFieldError):
        item.attach_to_seal(seal_id="sea_bbb", actor="u")


def test_evidence_archive_replaced_is_only_exit_from_sealed() -> None:
    item = _drive_to_verified()
    item.attach_to_seal(seal_id="sea_aaa", actor="u")
    item.archive_replaced(replaced_by="evd_new", actor="u",
                          reason="legacy remediation cutover")
    assert item.status == EvidenceStatus.ARCHIVED_REPLACED.value
    assert item.replaced_by == "evd_new"
    types = [e.event_type for e in item.pull_events()]
    assert "evidence.item.archived_replaced" in types


def test_evidence_optimistic_concurrency_check() -> None:
    item = _new_item()
    item.check_expected_version(1)  # ok
    with pytest.raises(ConcurrencyConflict):
        item.check_expected_version(99)


def _drive_to_verified() -> EvidenceItem:
    it = _new_item()
    it.attach_upload_session(upload_id="up", media_type="application/pdf")
    it.mark_uploaded(storage_locator="x", storage_provider="p",
                      size_bytes=10, streamed_sha256=H1,
                      media_type="application/pdf", actor="u")
    it.verify_hash(readback_sha256=H1, actor="u")
    it.pull_events()
    return it


# ---- Merkle + canonical JSON determinism -------------------------------

def test_merkle_root_single_leaf_is_leaf() -> None:
    assert compute_merkle_root([H1]) == H1


def test_merkle_root_is_order_independent_via_sort() -> None:
    a = compute_merkle_root([H1, H2, H3])
    b = compute_merkle_root([H3, H1, H2])
    assert a == b


def test_merkle_root_rejects_non_sha256() -> None:
    with pytest.raises(ValueError):
        compute_merkle_root(["zz", H1])


def test_canonical_json_hash_is_stable() -> None:
    a = canonical_json_hash({"a": 1, "b": [1, 2, 3]})
    b = canonical_json_hash({"b": [1, 2, 3], "a": 1})
    assert a == b


# ---- Seal invariants ---------------------------------------------------

def _verified_items_dict() -> list[dict]:
    return [
        {"evidence_id": "evd_" + "1" * 32, "server_hash": H1,
         "size_bytes": 10, "kind": "document", "media_type": "application/pdf"},
        {"evidence_id": "evd_" + "2" * 32, "server_hash": H2,
         "size_bytes": 20, "kind": "photo", "media_type": "image/jpeg"},
    ]


def test_seal_create_freezes_manifest() -> None:
    seal = Seal.create(
        registry_id="reg_" + "0" * 32,
        tenant_id="t", country_code="NG",
        items=_verified_items_dict(), created_by="u",
    )
    assert seal.status == SealStatus.CREATED.value
    assert seal.merkle_root == compute_merkle_root([H1, H2])
    assert len(seal.evidence_ids) == 2
    # Manifest hash is deterministic.
    seal2 = Seal.create(
        registry_id=seal.registry_id, tenant_id="t", country_code="NG",
        items=_verified_items_dict(), created_by="u",
        seal_id=seal.seal_id,
    )
    # Same inputs, same seal_id, same created_by: ONLY created_at + version
    # differ; manifest_hash should differ ONLY by created_at. We test the
    # determinism property by comparing the merkle roots (which exclude
    # timestamps).
    assert seal.merkle_root == seal2.merkle_root


def test_seal_requires_at_least_one_item() -> None:
    with pytest.raises(InvariantViolation):
        Seal.create(registry_id="reg_x", tenant_id="t", country_code="NG",
                    items=[], created_by="u")


def test_seal_rejects_duplicate_items() -> None:
    dup = _verified_items_dict() + [_verified_items_dict()[0]]
    with pytest.raises(InvariantViolation):
        Seal.create(registry_id="reg_x", tenant_id="t", country_code="NG",
                    items=dup, created_by="u")


def test_seal_rejects_item_missing_required_field() -> None:
    bad = [{"evidence_id": "evd_x", "server_hash": H1, "size_bytes": 1}]
    with pytest.raises(InvariantViolation):
        Seal.create(registry_id="reg_x", tenant_id="t", country_code="NG",
                    items=bad, created_by="u")


def test_seal_apply_worm_is_idempotent_and_one_way() -> None:
    seal = Seal.create(registry_id="reg_x", tenant_id="t", country_code="NG",
                        items=_verified_items_dict(), created_by="u")
    seal.pull_events()
    seal.apply_worm(actor="u", lock_results=[])
    assert seal.status == SealStatus.WORM_APPLIED.value
    seal.apply_worm(actor="u", lock_results=[])  # idempotent
    assert seal.status == SealStatus.WORM_APPLIED.value
    seal.archive(actor="u", reason="remediation")
    with pytest.raises(TransitionError):
        seal.apply_worm(actor="u", lock_results=[])


def test_seal_anchor_batch_is_write_once() -> None:
    seal = Seal.create(registry_id="reg_x", tenant_id="t", country_code="NG",
                        items=_verified_items_dict(), created_by="u")
    seal.attach_anchor_batch(batch_id="bch_001")
    seal.attach_anchor_batch(batch_id="bch_001")  # idempotent
    with pytest.raises(ImmutableFieldError):
        seal.attach_anchor_batch(batch_id="bch_002")


def test_seal_to_state_round_trips_tuples_as_lists() -> None:
    seal = Seal.create(registry_id="reg_x", tenant_id="t", country_code="NG",
                        items=_verified_items_dict(), created_by="u")
    state = seal.to_state()
    assert isinstance(state["evidence_ids"], list)
    rehydrated = Seal.from_state(state)
    assert rehydrated.evidence_ids == seal.evidence_ids
    assert rehydrated.merkle_root == seal.merkle_root
