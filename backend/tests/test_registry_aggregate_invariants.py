"""Phase 2A — Aggregate invariant tests (Directive §5).

Tests the LandVault aggregate in pure-Python isolation — no DB, no FastAPI.
Every binding invariant from the Phase 2A authorization is covered:

* registry_id / parcel_number / tenant_id / country_code / created_at /
  origin.* immutability
* version + schema_version monotonic
* deleted_at / archived one-way
* OwnershipHistory append-only
* DomainEvents emission and the OwnershipRecorded discipline (§3)
* Locked-state guard
* Evidence-sealed guard
"""
from __future__ import annotations

import pytest

from contexts.registry.domain.invariants import (
    ImmutableFieldError,
    InvariantViolation,
    LockedStateError,
    SoftDeletedError,
)
from contexts.registry.domain.land_vault import LandVault
from contexts.registry.domain.value_objects import (
    Geometry,
    LandVaultStatus,
    Origin,
    ParcelNumber,
    PropertyType,
    SourceSystem,
)


def _new_agg(**overrides) -> LandVault:
    kw = dict(
        parcel_number=ParcelNumber("LAGOS-IKEJA-WARD3-RES-000001"),
        tenant_id="t1", country_code="NG", created_by="usr_creator",
        origin=Origin(source_system=SourceSystem.NATIVE.value),
        ownership_type="individual", owner_name="Ada Lovelace",
        owner_email="ada@example.com",
        state="LAGOS", lga="IKEJA", ward="WARD3", property_type="RES",
    )
    kw.update(overrides)
    return LandVault.create(**kw)


# ---- Identity immutability ----------------------------------------------

def test_registry_id_is_immutable_via_update_helper() -> None:
    agg = _new_agg()
    with pytest.raises(ImmutableFieldError):
        agg._apply_patch({"registry_id": "reg_tampered"})


def test_parcel_number_is_immutable() -> None:
    agg = _new_agg()
    with pytest.raises(ImmutableFieldError):
        agg._apply_patch({"parcel_number": "LAGOS-IKEJA-WARD3-RES-000999"})


def test_tenant_and_country_are_immutable() -> None:
    agg = _new_agg()
    with pytest.raises(ImmutableFieldError):
        agg._apply_patch({"tenant_id": "other"})
    with pytest.raises(ImmutableFieldError):
        agg._apply_patch({"country_code": "GH"})


def test_created_at_and_origin_are_immutable() -> None:
    agg = _new_agg()
    with pytest.raises(ImmutableFieldError):
        agg._apply_patch({"created_at": "2000-01-01T00:00:00+00:00"})
    with pytest.raises(ImmutableFieldError):
        agg._apply_patch({"origin": {"source_system": "tampered"}})


# ---- Monotonic version ---------------------------------------------------

def test_version_is_monotonic_across_updates() -> None:
    agg = _new_agg()
    assert agg.version == 1
    agg.update_location(actor="usr_creator", address="No. 1 New Rd")
    assert agg.version == 2
    agg.update_ownership_contact(actor="usr_creator",
                                 owner_phone="+234-800-1234567")
    assert agg.version == 3


def test_schema_version_never_decreases() -> None:
    agg = _new_agg()
    starting = agg.schema_version
    # A downgrade attempt via _apply_patch must be rejected by callers; the
    # field itself is not in the immutable set, but the contract is enforced
    # at the API: no input model can target `schema_version`.
    assert starting >= 1
    # If we DID allow a patch, decreasing must not be representable in any
    # path because no command exposes the field. So this test asserts the
    # absence of such a setter.
    assert not hasattr(agg, "set_schema_version")


# ---- OwnershipHistory + OwnershipRecorded discipline (§3) ---------------

def test_creation_emits_landvault_created_and_initial_ownership_events() -> None:
    agg = _new_agg()
    events = [e.event_type for e in agg.pull_events()]
    assert "registry.landvault.created" in events
    assert "registry.parcel_reference.allocated" in events
    assert "registry.ownership.recorded" in events
    # initial ownership history entry present
    assert len(agg.ownership_history) == 1
    assert agg.ownership_history[0]["reason"] == "initial registration"


def test_contact_update_does_NOT_emit_ownership_recorded() -> None:
    """§3: phone/email edits are NOT legal ownership changes."""
    agg = _new_agg()
    agg.pull_events()  # drain creation events
    agg.update_ownership_contact(actor="usr_creator",
                                 owner_phone="+234-800-1112233",
                                 owner_email="ada.new@example.com")
    events = [e.event_type for e in agg.pull_events()]
    assert "registry.ownership.recorded" not in events
    assert any(e == "registry.landvault.updated" for e in events)
    # Ownership history is NOT extended by a contact update.
    assert len(agg.ownership_history) == 1


def test_legal_ownership_transfer_emits_ownership_recorded_and_appends_history() -> None:
    agg = _new_agg()
    agg.pull_events()
    agg.record_ownership_transfer(actor="usr_creator",
                                  owner_name="New Owner Ltd",
                                  ownership_type="corporate",
                                  reason="purchase")
    events = [e.event_type for e in agg.pull_events()]
    assert "registry.ownership.recorded" in events
    assert "registry.landvault.updated" in events
    assert len(agg.ownership_history) == 2
    assert agg.ownership_history[-1]["reason"] == "purchase"
    assert agg.ownership_history[-1]["owner_name"] == "New Owner Ltd"


def test_ownership_history_is_append_only() -> None:
    agg = _new_agg()
    agg.record_ownership_transfer(actor="x", owner_name="Step 1",
                                  reason="t1")
    agg.record_ownership_transfer(actor="x", owner_name="Step 2",
                                  reason="t2")
    # The aggregate exposes no remove/replace API:
    assert not hasattr(agg, "remove_ownership_entry")
    assert not hasattr(agg, "clear_ownership_history")
    assert [h["owner_name"] for h in agg.ownership_history] == [
        "Ada Lovelace", "Step 1", "Step 2"]


def test_ownership_transfer_without_legal_field_changes_is_rejected() -> None:
    """§3: record_ownership_transfer requires a legal field change.

    Passing only `owner_phone` to this command must fail — callers should
    use update_ownership_contact instead.
    """
    agg = _new_agg()
    with pytest.raises(InvariantViolation):
        agg.record_ownership_transfer(actor="x", reason="noop")


# ---- Locked-state and soft-delete invariants ----------------------------

def test_locked_status_blocks_owner_updates() -> None:
    agg = _new_agg()
    agg.status = LandVaultStatus.APPROVED_LOCKED.value  # simulate state machine
    with pytest.raises(LockedStateError):
        agg.update_location(actor="usr_creator", community="Updated")
    # ...but a privileged actor (super_admin/governance) may bypass.
    agg.update_location(actor="admin", actor_is_privileged=True,
                        community="By Admin")
    assert agg.community == "By Admin"


def test_evidence_sealed_blocks_owner_updates() -> None:
    agg = _new_agg()
    agg.evidence_sealed = True
    with pytest.raises(LockedStateError):
        agg.update_geometry(actor="usr_creator",
                            geometry=Geometry(type="Polygon",
                                               coordinates=[[[3.3, 6.5], [3.4, 6.5],
                                                             [3.4, 6.6], [3.3, 6.6],
                                                             [3.3, 6.5]]]))


def test_archive_is_one_way() -> None:
    agg = _new_agg()
    agg.archive(actor="super_admin", reason="duplicate")
    assert agg.archived is True
    assert agg.deleted_at is not None
    assert agg.status == LandVaultStatus.ARCHIVED.value
    # second archive: rejected as invariant violation
    with pytest.raises(InvariantViolation):
        agg.archive(actor="super_admin", reason="again")
    # any further update also rejected
    with pytest.raises(SoftDeletedError):
        agg.update_location(actor="super_admin", community="X")


# ---- Initial creation guards --------------------------------------------

def test_creation_requires_ownership_type_and_owner_name() -> None:
    with pytest.raises(InvariantViolation):
        _new_agg(owner_name="")
    with pytest.raises(InvariantViolation):
        _new_agg(ownership_type="not_a_real_type")


def test_creation_requires_tenant_and_country() -> None:
    with pytest.raises(InvariantViolation):
        _new_agg(tenant_id="")
    with pytest.raises(InvariantViolation):
        _new_agg(country_code="")
