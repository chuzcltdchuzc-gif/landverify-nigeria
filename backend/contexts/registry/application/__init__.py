"""Registry Application Service.

Thin orchestrator (Phase 2A §4): opens a Mongo session, drives the
aggregate's intention-revealing commands, persists state + raised events
inside the SAME transaction (transactional outbox), writes audit and
metrics, returns a DTO-shaped dict.

NEVER puts business logic here. NEVER raises domain events directly.
"""
from __future__ import annotations

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from contexts.registry.adapters.mongo_allocator import MongoRegistryNumberAllocator
from contexts.registry.adapters.mongo_repository import MongoLandVaultRepository
from contexts.registry.domain.invariants import (
    ConcurrencyConflict,
    ImmutableFieldError,
    InvariantViolation,
    LockedStateError,
    SoftDeletedError,
)
from contexts.registry.domain.land_vault import LandVault
from contexts.registry.domain.value_objects import (
    Geometry,
    Origin,
    ParcelNumber,
    PropertyType,
    SourceSystem,
)
from kernel.audit import audit
from kernel.errors.problem import bad_request, conflict, forbidden, not_found
from kernel.events.outbox import publish
from kernel.observability.metrics import increment
from kernel.persistence.context import current_context

PRIVILEGED_REGISTRY_ROLES = frozenset({
    "super_admin", "surveyor_general", "compliance_officer",
})


class RegistryCommandService:
    """Coordinates LandVault commands inside a Mongo transaction.

    The service relies on the PEP having already authorized the action.
    Domain invariants are enforced inside the aggregate; the service maps
    domain exceptions to the platform's RFC 7807 problem types.
    """

    def __init__(
        self, *,
        client: AsyncIOMotorClient,
        repo: MongoLandVaultRepository,
        allocator: MongoRegistryNumberAllocator,
    ) -> None:
        self._client = client
        self._repo = repo
        self._allocator = allocator

    # ---- Internal helpers ----------------------------------------------

    def _actor_is_privileged(self) -> bool:
        ctx = current_context()
        return bool(set(ctx.roles) & PRIVILEGED_REGISTRY_ROLES)

    async def _publish_events(self, agg: LandVault, session) -> None:
        ctx = current_context()
        for evt in agg.pull_events():
            env = evt.to_envelope(
                tenant_id=agg.tenant_id, country=agg.country_code,
                organization_id=ctx.organization_id,
                actor=ctx.principal_id, correlation_id=ctx.correlation_id,
            )
            await publish(env, session=session)
            # Audit + metrics. These do NOT need to be inside the tx
            # (audit is append-only by design), but doing them here keeps
            # ordering deterministic.
            await audit(
                action=evt.event_type, resource_type="land_vault",
                resource_id=agg.registry_id, decision="EXECUTED",
                payload={"version": evt.aggregate_version},
            )
            await increment("registry_event", labels={"event_type": evt.event_type})

    def _map_domain_error(self, exc: Exception) -> Exception:
        if isinstance(exc, ImmutableFieldError):
            return bad_request(str(exc), code="registry.immutable_field")
        if isinstance(exc, SoftDeletedError):
            return conflict(str(exc), code="registry.archived")
        if isinstance(exc, LockedStateError):
            return forbidden(str(exc), code="registry.locked_state")
        if isinstance(exc, ConcurrencyConflict):
            return conflict(str(exc), code="registry.version_conflict")
        if isinstance(exc, InvariantViolation):
            return bad_request(str(exc), code="registry.invariant_violation")
        return exc

    async def _with_session(self, fn):
        """Run `fn(session)` inside a Mongo transaction. The transaction
        ensures the aggregate write AND outbox inserts commit atomically.

        Falls back to no-session execution if the Mongo deployment doesn't
        support transactions (e.g. standalone). Production deployments use
        a replica set; tests use the `rs0` replica set.
        """
        try:
            async with await self._client.start_session() as session:
                try:
                    async with session.start_transaction():
                        return await fn(session)
                except Exception:
                    raise
        except Exception as exc:  # noqa: BLE001
            # Mongo will reject `start_transaction` outside a replica set.
            # In that case run without a session (still correct for tests
            # against a standalone Mongo).
            if "Transaction numbers" in str(exc) or "replica set" in str(exc).lower():
                return await fn(None)
            raise

    # ---- Commands -------------------------------------------------------

    async def create_landvault(self, *, country_code: str, state: str, lga: str,
                               ward: str, property_type: str,
                               ownership_type: str, owner_name: str,
                               owner_email: Optional[str] = None,
                               owner_phone: Optional[str] = None,
                               title: Optional[str] = None,
                               community: Optional[str] = None,
                               address: Optional[str] = None,
                               geometry: Optional[dict] = None,
                               legacy_aliases: Optional[list[str]] = None,
                               field_agent_email: Optional[str] = None,
                               origin_source: str = SourceSystem.NATIVE.value,
                               origin_source_id: Optional[str] = None,
                               import_batch: Optional[str] = None) -> dict:
        ctx = current_context()
        try:
            geom = Geometry(**geometry) if geometry else None
        except ValueError as exc:
            raise bad_request(str(exc), code="registry.geometry_invalid") from exc

        async def _run(session):
            try:
                pn_value = await self._allocator.allocate(
                    country=country_code, state=state, lga=lga, ward=ward,
                    property_type=property_type, session=session,
                )
                parcel_number = ParcelNumber(pn_value)
            except ValueError as exc:
                # Allocator rejected a malformed STATE/LGA/WARD/property_type
                # OR the assembled ParcelNumber failed the canonical regex.
                # Surface as HTTP 400 with a stable error code.
                raise bad_request(str(exc),
                                  code="registry.invalid_location_token") from exc
            origin = Origin(source_system=origin_source,
                            source_id=origin_source_id,
                            import_batch=import_batch)
            try:
                agg = LandVault.create(
                    parcel_number=parcel_number,
                    tenant_id=ctx.tenant_id or "default",
                    country_code=country_code,
                    created_by=ctx.principal_id,
                    origin=origin,
                    ownership_type=ownership_type, owner_name=owner_name,
                    owner_email=owner_email, owner_phone=owner_phone,
                    state=state, lga=lga, ward=ward, community=community,
                    property_type=property_type, geometry=geom, title=title,
                    legacy_aliases=legacy_aliases,
                    field_agent_email=field_agent_email,
                    registered_by=ctx.principal_id,
                )
            except InvariantViolation as exc:
                raise self._map_domain_error(exc) from exc

            await self._repo.add(agg, session=session)
            await self._publish_events(agg, session=session)
            return agg

        agg = await self._with_session(_run)
        return _project_landvault(agg, viewer_role="privileged"
                                  if self._actor_is_privileged() else "owner")

    async def _load_or_404(self, registry_id: str) -> LandVault:
        agg = await self._repo.get_by_registry_id(registry_id)
        if not agg:
            raise not_found(f"LandVault {registry_id} not found",
                            code="registry.not_found")
        return agg

    async def _mutate(self, registry_id: str, mutator,
                      expected_version: Optional[int] = None) -> dict:
        """Common mutation flow: load → mutate → save → publish."""

        async def _run(session):
            agg = await self._load_or_404(registry_id)
            agg.check_expected_version(expected_version)
            prev_version = agg.version
            try:
                mutator(agg)
            except (InvariantViolation, ConcurrencyConflict) as exc:
                raise self._map_domain_error(exc) from exc
            # If the mutator didn't actually bump the version, it was a no-op.
            if agg.version == prev_version:
                return agg
            await self._repo.replace(agg, expected_version=prev_version, session=session)
            await self._publish_events(agg, session=session)
            return agg

        try:
            agg = await self._with_session(_run)
        except ConcurrencyConflict as exc:
            raise self._map_domain_error(exc) from exc
        return _project_landvault(agg, viewer_role="privileged"
                                  if self._actor_is_privileged() else "owner")

    async def update_location(self, registry_id: str, *, expected_version=None,
                              **kwargs) -> dict:
        return await self._mutate(
            registry_id,
            lambda a: a.update_location(
                actor=current_context().principal_id,
                actor_is_privileged=self._actor_is_privileged(), **kwargs),
            expected_version=expected_version,
        )

    async def update_geometry(self, registry_id: str, *, expected_version=None,
                              **kwargs) -> dict:
        try:
            geom = Geometry(**kwargs.pop("geometry"))
        except ValueError as exc:
            raise bad_request(str(exc), code="registry.geometry_invalid") from exc
        return await self._mutate(
            registry_id,
            lambda a: a.update_geometry(
                actor=current_context().principal_id,
                actor_is_privileged=self._actor_is_privileged(),
                geometry=geom, **kwargs),
            expected_version=expected_version,
        )

    async def update_ownership_contact(self, registry_id: str, *,
                                       expected_version=None, **kwargs) -> dict:
        return await self._mutate(
            registry_id,
            lambda a: a.update_ownership_contact(
                actor=current_context().principal_id,
                actor_is_privileged=self._actor_is_privileged(), **kwargs),
            expected_version=expected_version,
        )

    async def record_ownership_transfer(self, registry_id: str, *,
                                        expected_version=None, **kwargs) -> dict:
        return await self._mutate(
            registry_id,
            lambda a: a.record_ownership_transfer(
                actor=current_context().principal_id,
                actor_is_privileged=self._actor_is_privileged(), **kwargs),
            expected_version=expected_version,
        )

    async def update_survey(self, registry_id: str, *, expected_version=None,
                            **kwargs) -> dict:
        return await self._mutate(
            registry_id,
            lambda a: a.update_survey(
                actor=current_context().principal_id,
                actor_is_privileged=self._actor_is_privileged(), **kwargs),
            expected_version=expected_version,
        )

    async def update_community_data(self, registry_id: str, *, expected_version=None,
                                    **kwargs) -> dict:
        return await self._mutate(
            registry_id,
            lambda a: a.update_community_data(
                actor=current_context().principal_id,
                actor_is_privileged=self._actor_is_privileged(), **kwargs),
            expected_version=expected_version,
        )

    async def archive(self, registry_id: str, *, reason: str,
                      expected_version=None) -> dict:
        # Soft delete is super_admin-only per Phase 2 §3.3.
        if not current_context().has_role("super_admin"):
            raise forbidden("archive requires super_admin",
                            code="registry.archive_forbidden")
        return await self._mutate(
            registry_id,
            lambda a: a.archive(actor=current_context().principal_id, reason=reason),
            expected_version=expected_version,
        )


# ---- Read-side projection -----------------------------------------------

# Fields that a non-privileged owner can see.
OWNER_VIEW_FIELDS = (
    "registry_id", "parcel_number", "title", "status", "version",
    "country_code", "state", "lga", "ward", "ward_code", "community",
    "village", "address", "property_type", "land_use", "size_sqm",
    "size_hectares", "ownership_type", "owner_name", "owner_email",
    "owner_phone", "representative_name", "representative_authority",
    "family_head", "geometry", "boundary_area", "boundary_perimeter",
    "boundary_source", "spatial_validation_status", "latitude", "longitude",
    "verbal_consent", "community_confirmed",
    "survey_plan_url", "surveyor_name", "survey_date", "survey_status",
    "field_agent_email",
    "evidence_seal_id", "evidence_seal_timestamp", "evidence_count_at_seal",
    "certificate_url", "certificate_version", "certificate_status",
    "amount_paid", "total_fee", "outstanding_balance", "payment_status",
    "verification_status", "risk_level",
    "created_at", "created_by", "updated_at",
    "legacy_aliases", "ownership_history",
)

# Fields only visible to privileged roles (PII + sensitive metadata).
PRIVILEGED_EXTRA_FIELDS = (
    "owner_nin", "surveyor_id", "surveyor_licence", "tenant_id",
    "evidence_seal_hash", "risk_score", "deleted_at", "archived",
    "evidence_sealed", "origin", "schema_version",
)

# Public-anonymous view (when we ever expose a public verifier).
PUBLIC_VIEW_FIELDS = (
    "registry_id", "parcel_number", "country_code", "state", "lga", "ward",
    "community", "village", "property_type", "land_use", "status",
    "verification_status", "geometry", "boundary_area", "boundary_source",
    "certificate_status", "spatial_validation_status",
)


def _project_landvault(agg: LandVault, *, viewer_role: str = "owner") -> dict:
    state = agg.to_state()
    if viewer_role == "public":
        keys = PUBLIC_VIEW_FIELDS
    elif viewer_role == "privileged":
        keys = OWNER_VIEW_FIELDS + PRIVILEGED_EXTRA_FIELDS
    else:
        keys = OWNER_VIEW_FIELDS
    return {k: state.get(k) for k in keys}


# ---- Query service -------------------------------------------------------

class RegistryQueryService:
    """Read-side service. Applies field projection per viewer role."""

    def __init__(self, repo: MongoLandVaultRepository) -> None:
        self._repo = repo

    def _viewer_role_for(self, agg: LandVault) -> str:
        ctx = current_context()
        if set(ctx.roles) & PRIVILEGED_REGISTRY_ROLES:
            return "privileged"
        if ctx.principal_id == agg.created_by:
            return "owner"
        if ctx.email and ctx.email.lower() == (agg.owner_email or "").lower():
            return "owner"
        if ctx.email and ctx.email.lower() == (agg.field_agent_email or "").lower():
            return "owner"
        if "government_observer" in ctx.roles:
            return "privileged"
        return "public"

    async def get(self, registry_id: str) -> dict:
        agg = await self._repo.get_by_registry_id(registry_id)
        if not agg:
            raise not_found(f"LandVault {registry_id} not found",
                            code="registry.not_found")
        return _project_landvault(agg, viewer_role=self._viewer_role_for(agg))

    async def list(self, *, spec, limit: int = 50, skip: int = 0) -> dict:
        items = await self._repo.find(spec, limit=limit, skip=skip,
                                       sort=[("created_at", -1)])
        total = await self._repo.count(spec)
        projected = [_project_landvault(a, viewer_role=self._viewer_role_for(a))
                     for a in items]
        return {"items": projected, "total": total, "limit": limit, "skip": skip}
