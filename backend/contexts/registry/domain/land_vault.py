"""LandVault — the single canonical aggregate root for land records.

ADR-001 / ADR-014: every state change for a land record goes through this
aggregate. The aggregate raises domain events; the Application Service
persists state + raised events inside one Mongo transaction; the
transactional outbox guarantees at-least-once delivery to consumers.

Invariants enforced INSIDE the aggregate (not at the API edge):
* `registry_id`, `parcel_number`, `tenant_id`, `country_code`, `created_at`,
  and `origin.*` are immutable after the relevant lifecycle point.
* `version` and `schema_version` are monotonic.
* `deleted_at` is one-way (soft-delete cannot be undone).
* OwnershipHistory, Audit, and DomainEvents are append-only.
* Owner-side mutation is denied while status is in LOCKED_STATUSES or
  while `evidence_sealed` is True.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from contexts.registry.domain.events import (
    DomainEvent,
    landvault_archived,
    landvault_created,
    landvault_updated,
    ownership_recorded,
    parcel_reference_allocated,
)
from contexts.registry.domain.invariants import (
    ConcurrencyConflict,
    ImmutableFieldError,
    InvariantViolation,
    LockedStateError,
    SoftDeletedError,
)
from contexts.registry.domain.value_objects import (
    EVIDENCE_SEALED_LOCK,
    LOCKED_STATUSES,
    Geometry,
    LandVaultStatus,
    Origin,
    OwnershipSnapshot,
    OwnershipType,
    ParcelNumber,
    new_registry_id,
    now_iso,
)

SCHEMA_VERSION_CURRENT = 1

# Fields editable by ordinary contact updates — these do NOT raise an
# OwnershipRecorded event. (Phase 2A authorization §3: ownership events
# represent legal ownership changes, not profile edits.)
OWNERSHIP_CONTACT_FIELDS = frozenset({"owner_phone", "owner_email"})

# Fields whose change DOES constitute a legal ownership change.
LEGAL_OWNERSHIP_FIELDS = frozenset({
    "ownership_type", "owner_name", "owner_nin",
    "representative_name", "representative_authority",
    "family_head", "family_members",
})


@dataclass
class LandVault:
    """Aggregate root.

    The mutable state lives here; mutation only happens through
    intention-revealing methods (`update_location`, `update_geometry`,
    `update_ownership_contact`, `record_ownership_transfer`,
    `update_survey`, `update_community_data`, `archive`).
    """

    # ---- Identity (immutable after creation) ----
    registry_id: str
    parcel_number: str
    tenant_id: str
    country_code: str
    created_at: str
    origin: dict
    # ---- Versioning ----
    version: int = 0
    schema_version: int = SCHEMA_VERSION_CURRENT
    # ---- Lifecycle ----
    status: str = LandVaultStatus.DRAFT.value
    deleted_at: Optional[str] = None
    archived: bool = False
    evidence_sealed: bool = False
    # ---- Mutable facets (stored inert per Phase 2 §2.4 unless logic noted) ----
    title: Optional[str] = None
    legacy_aliases: list[str] = field(default_factory=list)
    # location / admin
    state: Optional[str] = None
    lga: Optional[str] = None
    ward: Optional[str] = None
    ward_code: Optional[str] = None
    community: Optional[str] = None
    village: Optional[str] = None
    address: Optional[str] = None
    property_type: Optional[str] = None
    land_use: Optional[str] = None
    size_sqm: Optional[float] = None
    size_hectares: Optional[float] = None
    # ownership (current snapshot — full history under `ownership_history`)
    ownership_type: Optional[str] = None
    owner_name: Optional[str] = None
    owner_email: Optional[str] = None
    owner_phone: Optional[str] = None
    owner_nin: Optional[str] = None
    representative_name: Optional[str] = None
    representative_authority: Optional[str] = None
    family_head: Optional[str] = None
    family_members: list[dict] = field(default_factory=list)
    # geometry
    geometry: Optional[dict] = None
    boundary_area: Optional[float] = None
    boundary_perimeter: Optional[float] = None
    boundary_source: Optional[str] = None
    spatial_validation_status: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    # consent / community (inert)
    verbal_consent: Optional[bool] = None
    consent_timeline: list[dict] = field(default_factory=list)
    witness_records: list[dict] = field(default_factory=list)
    community_confirmed: Optional[bool] = None
    # survey (inert)
    survey_plan_url: Optional[str] = None
    surveyor_id: Optional[str] = None
    surveyor_name: Optional[str] = None
    surveyor_licence: Optional[str] = None
    survey_date: Optional[str] = None
    survey_status: Optional[str] = None
    field_agent_email: Optional[str] = None
    # evidence (inert)
    evidence_seal_id: Optional[str] = None
    evidence_seal_hash: Optional[str] = None
    evidence_seal_timestamp: Optional[str] = None
    evidence_count_at_seal: Optional[int] = None
    # certificate (inert)
    certificate_url: Optional[str] = None
    certificate_version: Optional[int] = None
    certificate_status: Optional[str] = None
    # economic (inert)
    amount_paid: Optional[float] = None
    total_fee: Optional[float] = None
    outstanding_balance: Optional[float] = None
    payment_status: Optional[str] = None
    # verification/risk (inert)
    verification_status: Optional[str] = None
    risk_level: Optional[str] = None
    risk_score: Optional[float] = None
    # provenance / actors
    created_by: Optional[str] = None
    registered_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
    # append-only history
    ownership_history: list[dict] = field(default_factory=list)
    # transient — never persisted; drained by the Application Service
    _events: list[DomainEvent] = field(default_factory=list, repr=False, compare=False)
    _initial_load: bool = field(default=False, repr=False, compare=False)

    # ---- Factory ---------------------------------------------------------

    @classmethod
    def create(
        cls, *, parcel_number: ParcelNumber, tenant_id: str, country_code: str,
        created_by: str, origin: Origin,
        ownership_type: str, owner_name: str,
        state: Optional[str] = None, lga: Optional[str] = None,
        ward: Optional[str] = None, community: Optional[str] = None,
        property_type: Optional[str] = None,
        geometry: Optional[Geometry] = None,
        title: Optional[str] = None,
        owner_email: Optional[str] = None, owner_phone: Optional[str] = None,
        legacy_aliases: Optional[list[str]] = None,
        registry_id: Optional[str] = None,
        registered_by: Optional[str] = None,
        field_agent_email: Optional[str] = None,
    ) -> "LandVault":
        """Create a brand-new LandVault aggregate.

        Raises `LandVaultCreated` AND, for non-empty `ownership_type/owner_name`,
        `OwnershipRecorded` representing the initial legal ownership.
        """
        if ownership_type not in {o.value for o in OwnershipType}:
            raise InvariantViolation(f"invalid ownership_type: {ownership_type!r}")
        if not owner_name or not owner_name.strip():
            raise InvariantViolation("owner_name is required at creation")
        if not tenant_id:
            raise InvariantViolation("tenant_id is required")
        if not country_code:
            raise InvariantViolation("country_code is required")

        agg = cls(
            registry_id=registry_id or new_registry_id(),
            parcel_number=str(parcel_number),
            tenant_id=tenant_id, country_code=country_code,
            created_at=now_iso(),
            origin=origin.to_dict(),
            version=1,
            status=LandVaultStatus.DRAFT.value,
            ownership_type=ownership_type, owner_name=owner_name,
            owner_email=owner_email, owner_phone=owner_phone,
            state=state, lga=lga, ward=ward, community=community,
            property_type=property_type, title=title,
            geometry=geometry.to_dict() if geometry else None,
            legacy_aliases=list(legacy_aliases or []),
            created_by=created_by, registered_by=registered_by or created_by,
            field_agent_email=field_agent_email,
        )
        # Compute geometry derivatives if provided
        if geometry is not None:
            agg.spatial_validation_status = "valid"

        agg._raise(landvault_created(
            registry_id=agg.registry_id, version=agg.version,
            payload={
                "registry_id": agg.registry_id,
                "parcel_number": agg.parcel_number,
                "tenant_id": agg.tenant_id,
                "country_code": agg.country_code,
                "created_by": agg.created_by,
                "status": agg.status,
                "ownership_type": agg.ownership_type,
                "origin": agg.origin,
                "has_geometry": agg.geometry is not None,
            },
        ))
        agg._raise(parcel_reference_allocated(
            registry_id=agg.registry_id, version=agg.version,
            payload={
                "registry_id": agg.registry_id,
                "parcel_number": agg.parcel_number,
                "sequence_key": parcel_number.sequence_key,
                "sequence_number": parcel_number.sequence_number,
            },
        ))
        # Initial ownership is a legal ownership event.
        agg._record_ownership_snapshot(
            reason="initial registration",
            recorded_by=created_by,
        )
        return agg

    # ---- Reconstitution from storage ------------------------------------

    @classmethod
    def from_state(cls, state: dict) -> "LandVault":
        """Hydrate the aggregate from a persisted document. NO events raised."""
        clean = {k: v for k, v in state.items()
                 if k in cls.__dataclass_fields__ and not k.startswith("_")}
        agg = cls(**clean)
        agg._initial_load = True
        agg._events.clear()
        return agg

    # ---- Mutation guards (run at the top of every command) --------------

    def _ensure_writable(self, *, allow_locked_roles: bool = False,
                        actor_is_privileged: bool = False) -> None:
        if self.deleted_at is not None or self.archived:
            raise SoftDeletedError("aggregate is archived/soft-deleted")
        if self.evidence_sealed and not actor_is_privileged:
            raise LockedStateError(f"locked: {EVIDENCE_SEALED_LOCK}")
        if self.status in LOCKED_STATUSES and not actor_is_privileged:
            raise LockedStateError(f"locked status: {self.status}")

    def _bump(self, actor: Optional[str]) -> None:
        self.version += 1
        self.updated_at = now_iso()
        self.updated_by = actor

    def _raise(self, ev: DomainEvent) -> None:
        self._events.append(ev)

    def pull_events(self) -> list[DomainEvent]:
        """Drained by the Application Service post-commit (or pre-persist for outbox-in-tx)."""
        out = list(self._events)
        self._events.clear()
        return out

    # ---- Task-oriented commands -----------------------------------------

    def update_location(
        self, *, actor: str, actor_is_privileged: bool = False,
        state: Optional[str] = None, lga: Optional[str] = None,
        ward: Optional[str] = None, ward_code: Optional[str] = None,
        community: Optional[str] = None, village: Optional[str] = None,
        address: Optional[str] = None, land_use: Optional[str] = None,
        size_sqm: Optional[float] = None, size_hectares: Optional[float] = None,
    ) -> None:
        self._ensure_writable(actor_is_privileged=actor_is_privileged)
        changes = self._apply_patch({
            "state": state, "lga": lga, "ward": ward, "ward_code": ward_code,
            "community": community, "village": village, "address": address,
            "land_use": land_use, "size_sqm": size_sqm,
            "size_hectares": size_hectares,
        })
        if not changes:
            return
        self._bump(actor)
        self._raise(landvault_updated(
            registry_id=self.registry_id, version=self.version,
            payload={"facet": "location", "changes": changes, "actor": actor},
        ))

    def update_geometry(self, *, actor: str, actor_is_privileged: bool = False,
                        geometry: Geometry, boundary_source: Optional[str] = None,
                        boundary_area: Optional[float] = None,
                        boundary_perimeter: Optional[float] = None,
                        latitude: Optional[float] = None,
                        longitude: Optional[float] = None) -> None:
        self._ensure_writable(actor_is_privileged=actor_is_privileged)
        self.geometry = geometry.to_dict()
        if boundary_source is not None:
            self.boundary_source = boundary_source
        if boundary_area is not None:
            self.boundary_area = boundary_area
        if boundary_perimeter is not None:
            self.boundary_perimeter = boundary_perimeter
        if latitude is not None:
            self.latitude = latitude
        if longitude is not None:
            self.longitude = longitude
        self.spatial_validation_status = "valid"
        self._bump(actor)
        self._raise(landvault_updated(
            registry_id=self.registry_id, version=self.version,
            payload={"facet": "geometry", "actor": actor,
                     "boundary_source": self.boundary_source},
        ))

    def update_ownership_contact(self, *, actor: str,
                                 actor_is_privileged: bool = False,
                                 owner_email: Optional[str] = None,
                                 owner_phone: Optional[str] = None) -> None:
        """Pure contact edits — NO OwnershipRecorded event (§3 ruling)."""
        self._ensure_writable(actor_is_privileged=actor_is_privileged)
        changes = self._apply_patch({
            "owner_email": owner_email,
            "owner_phone": owner_phone,
        })
        if not changes:
            return
        self._bump(actor)
        self._raise(landvault_updated(
            registry_id=self.registry_id, version=self.version,
            payload={"facet": "ownership_contact", "changes": list(changes.keys()),
                     "actor": actor},
        ))

    def record_ownership_transfer(self, *, actor: str,
                                  actor_is_privileged: bool = False,
                                  ownership_type: Optional[str] = None,
                                  owner_name: Optional[str] = None,
                                  owner_nin: Optional[str] = None,
                                  representative_name: Optional[str] = None,
                                  representative_authority: Optional[str] = None,
                                  family_head: Optional[str] = None,
                                  family_members: Optional[list[dict]] = None,
                                  reason: str = "ownership change") -> None:
        """A LEGAL ownership change (§3). Always raises OwnershipRecorded."""
        self._ensure_writable(actor_is_privileged=actor_is_privileged)
        if ownership_type is not None and ownership_type not in {o.value for o in OwnershipType}:
            raise InvariantViolation(f"invalid ownership_type: {ownership_type!r}")
        if owner_name is not None and not owner_name.strip():
            raise InvariantViolation("owner_name cannot be set to empty")

        patch = {
            "ownership_type": ownership_type,
            "owner_name": owner_name,
            "owner_nin": owner_nin,
            "representative_name": representative_name,
            "representative_authority": representative_authority,
            "family_head": family_head,
        }
        if family_members is not None:
            patch["family_members"] = family_members
        changes = self._apply_patch(patch)

        # No legal ownership field changed → no-op (caller likely intended contact update).
        legal_changed = bool(set(changes) & LEGAL_OWNERSHIP_FIELDS)
        if not legal_changed:
            raise InvariantViolation(
                "record_ownership_transfer requires at least one legal "
                "ownership field to change; use update_ownership_contact "
                "for phone/email."
            )
        self._bump(actor)
        self._record_ownership_snapshot(reason=reason, recorded_by=actor)
        self._raise(landvault_updated(
            registry_id=self.registry_id, version=self.version,
            payload={"facet": "ownership_transfer",
                     "changes": list(changes.keys()),
                     "actor": actor, "reason": reason},
        ))

    def update_survey(self, *, actor: str, actor_is_privileged: bool = False,
                      survey_plan_url: Optional[str] = None,
                      surveyor_id: Optional[str] = None,
                      surveyor_name: Optional[str] = None,
                      surveyor_licence: Optional[str] = None,
                      survey_date: Optional[str] = None,
                      survey_status: Optional[str] = None,
                      field_agent_email: Optional[str] = None) -> None:
        self._ensure_writable(actor_is_privileged=actor_is_privileged)
        changes = self._apply_patch({
            "survey_plan_url": survey_plan_url,
            "surveyor_id": surveyor_id, "surveyor_name": surveyor_name,
            "surveyor_licence": surveyor_licence, "survey_date": survey_date,
            "survey_status": survey_status, "field_agent_email": field_agent_email,
        })
        if not changes:
            return
        self._bump(actor)
        self._raise(landvault_updated(
            registry_id=self.registry_id, version=self.version,
            payload={"facet": "survey", "changes": list(changes.keys()),
                     "actor": actor},
        ))

    def update_community_data(self, *, actor: str, actor_is_privileged: bool = False,
                              verbal_consent: Optional[bool] = None,
                              community_confirmed: Optional[bool] = None,
                              witness_records: Optional[list[dict]] = None) -> None:
        self._ensure_writable(actor_is_privileged=actor_is_privileged)
        patch = {"verbal_consent": verbal_consent,
                 "community_confirmed": community_confirmed}
        if witness_records is not None:
            patch["witness_records"] = witness_records
        changes = self._apply_patch(patch)
        if not changes:
            return
        self._bump(actor)
        self._raise(landvault_updated(
            registry_id=self.registry_id, version=self.version,
            payload={"facet": "community_data", "changes": list(changes.keys()),
                     "actor": actor},
        ))

    def archive(self, *, actor: str, reason: str) -> None:
        if self.archived or self.deleted_at is not None:
            raise InvariantViolation("aggregate is already archived")
        self.archived = True
        self.deleted_at = now_iso()
        self.status = LandVaultStatus.ARCHIVED.value
        self._bump(actor)
        self._raise(landvault_archived(
            registry_id=self.registry_id, version=self.version,
            payload={"actor": actor, "reason": reason,
                     "archived_at": self.deleted_at},
        ))

    # ---- Internal helpers ------------------------------------------------

    def _apply_patch(self, patch: dict) -> dict:
        """Apply a sparse patch; return only fields that actually changed."""
        changes: dict = {}
        for k, v in patch.items():
            if v is None:
                continue
            if getattr(self, k) != v:
                # immutables guard
                if k in {"registry_id", "parcel_number", "tenant_id",
                         "country_code", "created_at", "origin"}:
                    raise ImmutableFieldError(f"{k} is immutable")
                setattr(self, k, v)
                changes[k] = v
        return changes

    def _record_ownership_snapshot(self, *, reason: str,
                                   recorded_by: Optional[str]) -> None:
        if not self.ownership_type or not self.owner_name:
            raise InvariantViolation(
                "cannot record ownership without ownership_type + owner_name")
        snap = OwnershipSnapshot(
            ownership_type=self.ownership_type, owner_name=self.owner_name,
            recorded_at=now_iso(), recorded_by=recorded_by, reason=reason,
            representative_name=self.representative_name,
            representative_authority=self.representative_authority,
            family_head=self.family_head,
        )
        self.ownership_history.append(snap.to_dict())
        self._raise(ownership_recorded(
            registry_id=self.registry_id, version=self.version,
            payload={"registry_id": self.registry_id,
                     "ownership_type": self.ownership_type,
                     "owner_name": self.owner_name,
                     "reason": reason, "recorded_by": recorded_by,
                     "history_length": len(self.ownership_history)},
        ))

    # ---- Concurrency control --------------------------------------------

    def check_expected_version(self, expected: Optional[int]) -> None:
        """Optimistic concurrency. Caller may pass `None` to skip the check."""
        if expected is not None and expected != self.version:
            raise ConcurrencyConflict(
                f"expected version {expected}, found {self.version}"
            )

    # ---- Persistence projection -----------------------------------------

    def to_state(self) -> dict:
        """Project to a plain dict for the repository (no events)."""
        out = {k: getattr(self, k) for k in self.__dataclass_fields__
               if not k.startswith("_")}
        return out
