"""Contract Package Generator — Phase 1C (Platform Contract Freeze).

Generates the entire `contracts/v1/` tree from the live FastAPI application.

Run:
    python -m contracts.generate          # writes the freeze tree
    python -m contracts.generate --check  # compares without writing

Determinism: every JSON artifact is serialized with `sort_keys=True`,
`indent=2`, and a trailing newline. SHA256 fingerprints are computed over
the exact byte output so the freeze is reproducible.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Make /app/backend importable so we can build the FastAPI app object.
ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

CONTRACT_VERSION = (ROOT / "contracts" / "VERSION").read_text().strip()
CONTRACT_DIR = ROOT / "contracts"
V1_DIR = CONTRACT_DIR / "v1"

# ---------------------------------------------------------------------------
# Canonical request / response DTO mapping.
#
# The DTOs listed here are the binding wire contracts for v1. They are
# extracted from the OpenAPI `components.schemas` block, frozen as
# independent JSON Schemas, and pinned by SHA256 in `sdk/contract.sha256`.
# ---------------------------------------------------------------------------
REQUEST_DTOS = (
    "RegisterRequest",
    "LoginLocalRequest",
    "LoginGoogleRequest",
    "SuspendRequest",
    "AssignRoleRequest",
    "CreateServiceAccountRequest",
    "DelegationRequest",
    "RevokeRequest",
)
RESPONSE_DTOS = (
    "TokenResponse",
)

# Domain events — names mirror `kernel.events.outbox.EVENT_TYPES` and the
# Envelope shape defined in `kernel.events.envelope`. Versions all start
# at 1; bumping requires a new `event_type` (see envelope.py).
EVENT_DEFINITIONS: tuple[dict, ...] = (
    {
        "event_name": "identity.user.registered",
        "version": 1,
        "aggregate": "User",
        "bounded_context": "identity",
        "producer": "identity",
        "known_consumers": ["audit-log", "metrics", "notifications"],
        "idempotency_requirements": (
            "Consumers MUST deduplicate by `event_id`. Producers guarantee "
            "exactly-once via the transactional outbox."
        ),
        "ordering_guarantees": (
            "Per-aggregate (User) ordering by `aggregate_version`. No global "
            "ordering across aggregates."
        ),
        "replay_support": "Idempotent — events can be replayed from the outbox.",
        "payload_fields": {
            "user_id": "string — identity user id (uuid)",
            "email": "string — normalized lowercase email",
            "country": "string|null — ISO-3166-1 alpha-2",
            "roles": "string[] — initial role set",
            "registration_source": "string — 'local' | 'google'",
        },
    },
    {
        "event_name": "identity.account.activated",
        "version": 1,
        "aggregate": "User",
        "bounded_context": "identity",
        "producer": "identity",
        "known_consumers": ["audit-log", "metrics"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-User ordering by `aggregate_version`.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "user_id": "string",
            "actor_id": "string|null — admin who activated the account",
        },
    },
    {
        "event_name": "identity.account.suspended",
        "version": 1,
        "aggregate": "User",
        "bounded_context": "identity",
        "producer": "identity",
        "known_consumers": ["audit-log", "metrics", "notifications"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-User ordering by `aggregate_version`.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "user_id": "string",
            "actor_id": "string|null",
            "reason": "string",
        },
    },
    {
        "event_name": "identity.password.changed",
        "version": 1,
        "aggregate": "User",
        "bounded_context": "identity",
        "producer": "identity",
        "known_consumers": ["audit-log", "notifications"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-User ordering by `aggregate_version`.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "user_id": "string",
            "actor_id": "string|null",
        },
    },
    {
        "event_name": "identity.role.assigned",
        "version": 1,
        "aggregate": "User",
        "bounded_context": "identity",
        "producer": "identity",
        "known_consumers": ["audit-log", "metrics"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-User ordering by `aggregate_version`.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "user_id": "string",
            "role": "string — one of the 10 canonical Role values",
            "actor_id": "string|null",
        },
    },
    {
        "event_name": "identity.delegation.granted",
        "version": 1,
        "aggregate": "Delegation",
        "bounded_context": "identity",
        "producer": "identity",
        "known_consumers": ["audit-log"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-Delegation ordering.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "delegation_id": "string",
            "delegator_id": "string",
            "delegate_id": "string",
            "scope": "string[]",
            "valid_from": "string — ISO8601",
            "valid_until": "string — ISO8601",
            "reason": "string",
        },
    },
    {
        "event_name": "identity.delegation.revoked",
        "version": 1,
        "aggregate": "Delegation",
        "bounded_context": "identity",
        "producer": "identity",
        "known_consumers": ["audit-log"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-Delegation ordering.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "delegation_id": "string",
            "actor_id": "string|null",
            "reason": "string",
        },
    },
    {
        "event_name": "identity.service_account.created",
        "version": 1,
        "aggregate": "ServiceAccount",
        "bounded_context": "identity",
        "producer": "identity",
        "known_consumers": ["audit-log"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-ServiceAccount ordering.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "account_id": "string",
            "name": "string",
            "scopes": "string[]",
            "tenant_id": "string|null",
            "country": "string|null",
            "organization_id": "string|null",
            "actor_id": "string|null",
        },
    },
    {
        "event_name": "identity.service_account.revoked",
        "version": 1,
        "aggregate": "ServiceAccount",
        "bounded_context": "identity",
        "producer": "identity",
        "known_consumers": ["audit-log"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-ServiceAccount ordering.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "account_id": "string",
            "actor_id": "string|null",
        },
    },
    {
        "event_name": "identity.session.revoked",
        "version": 1,
        "aggregate": "Session",
        "bounded_context": "identity",
        "producer": "identity",
        "known_consumers": ["audit-log", "metrics"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-Session ordering.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "session_id": "string",
            "user_id": "string",
            "reason": "string",
        },
    },
    {
        "event_name": "identity.login.success",
        "version": 1,
        "aggregate": "Session",
        "bounded_context": "identity",
        "producer": "identity",
        "known_consumers": ["audit-log", "metrics", "fraud-detection"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "No global ordering required.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "user_id": "string",
            "session_id": "string",
            "ip": "string|null",
            "user_agent": "string|null",
            "source": "string — 'local' | 'google'",
        },
    },
    {
        "event_name": "identity.login.failed",
        "version": 1,
        "aggregate": "User",
        "bounded_context": "identity",
        "producer": "identity",
        "known_consumers": ["audit-log", "metrics", "fraud-detection"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "No global ordering required.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "email_attempted": "string",
            "ip": "string|null",
            "user_agent": "string|null",
            "reason_code": "string — 'invalid_credentials' | 'account_suspended' | 'rate_limited'",
        },
    },
)

# Canonical RFC7807 error contracts (Phase 1C, §5). Every error a v1
# endpoint may emit is independently frozen here. Backend handlers raise
# these via `kernel.errors.problem.ProblemException`.
ERROR_CONTRACTS: tuple[dict, ...] = (
    {
        "name": "ValidationError",
        "title": "Validation failed",
        "status": 422,
        "code": "common.validation_error",
        "description": (
            "Request body or query parameters failed schema validation. "
            "`errors` lists the offending fields and reasons."
        ),
        "extra_fields": {
            "errors": {
                "type": "array",
                "description": "Per-field validation failures.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["loc", "msg", "type"],
                    "properties": {
                        "loc": {"type": "array", "items": {"type": "string"}},
                        "msg": {"type": "string"},
                        "type": {"type": "string"},
                    },
                },
            },
        },
    },
    {
        "name": "AuthorizationDenied",
        "title": "Forbidden",
        "status": 403,
        "code": "auth.forbidden",
        "description": (
            "The authenticated principal is not authorized to perform "
            "the requested action on the target resource. The PDP "
            "default-denies; this response means a policy returned "
            "an explicit DENY or no policy returned PERMIT."
        ),
        "extra_fields": {
            "policy_id": {
                "type": "string",
                "description": "Identifier of the policy that produced the DENY decision.",
            },
        },
    },
    {
        "name": "ConcurrencyConflict",
        "title": "Concurrency conflict",
        "status": 409,
        "code": "common.concurrency_conflict",
        "description": (
            "Optimistic concurrency check failed: the aggregate's "
            "`version` did not match the version supplied by the "
            "caller. Re-read the aggregate and retry."
        ),
        "extra_fields": {
            "expected_version": {"type": "integer"},
            "current_version": {"type": "integer"},
        },
    },
    {
        "name": "NotFound",
        "title": "Resource not found",
        "status": 404,
        "code": "common.not_found",
        "description": "The requested resource does not exist or is outside the caller's scope.",
        "extra_fields": {},
    },
    {
        "name": "RateLimitExceeded",
        "title": "Rate limit exceeded",
        "status": 429,
        "code": "common.rate_limit_exceeded",
        "description": (
            "The caller has exceeded their rate-limit budget for this "
            "endpoint or action. `retry_after_seconds` indicates when "
            "the budget will refresh."
        ),
        "extra_fields": {
            "retry_after_seconds": {"type": "integer", "minimum": 0},
        },
    },
    {
        "name": "SpatialValidationError",
        "title": "Spatial validation failed",
        "status": 422,
        "code": "spatial.validation_error",
        "description": (
            "Geometry (parcel, survey, or polygon) failed spatial "
            "validation — for example invalid coordinates, overlap "
            "with an existing approved record, or outside the "
            "permitted country envelope."
        ),
        "extra_fields": {
            "violations": {
                "type": "array",
                "description": "List of spatial constraint violations.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["constraint", "detail"],
                    "properties": {
                        "constraint": {"type": "string"},
                        "detail": {"type": "string"},
                    },
                },
            },
        },
    },
    {
        "name": "BusinessRuleViolation",
        "title": "Business rule violation",
        "status": 422,
        "code": "business.rule_violation",
        "description": (
            "The requested operation would violate an invariant of "
            "the target aggregate (for example, suspending a user "
            "that is already suspended, or revoking a delegation "
            "outside its validity window)."
        ),
        "extra_fields": {
            "rule": {
                "type": "string",
                "description": "Identifier of the violated rule.",
            },
        },
    },
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dumps(obj: Any) -> str:
    """Deterministic JSON serialization used for every artifact + SHA."""
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _git_commit() -> str:
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=False, timeout=5)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# OpenAPI generation
# ---------------------------------------------------------------------------

def _load_openapi() -> dict:
    """Import the FastAPI app and produce its OpenAPI dict.

    Done in a subprocess-free fashion: the generator process imports the
    module exactly as the running server would, but without invoking
    `startup` event handlers (so we never touch MongoDB during generation).
    """
    # FastAPI's `app.openapi()` only inspects routes — no DB I/O happens.
    from main import app  # type: ignore

    spec = app.openapi()
    spec = copy.deepcopy(spec)
    # Pin contract metadata
    spec["info"] = {
        "title": "Aquasavannah LandVault — Platform Contract",
        "version": CONTRACT_VERSION,
        "description": (
            "Canonical, governed API surface for AquaSavannah LandVault. "
            "Endpoints under `/api/v1/*` are the supported platform contract. "
            "Endpoints under `/api/*` (without `/v1/`) are LEGACY and "
            "deprecated — see `contracts/deprecation-policy.md`."
        ),
        "x-contract-version": CONTRACT_VERSION,
        "x-contract-package": "aquasavannah-landvault",
    }
    paths = spec.get("paths", {})
    for path, operations in paths.items():
        is_v1 = "/v1/" in path or ".well-known" in path
        for method, op in operations.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete",
                                      "options", "head"}:
                continue
            if not is_v1:
                op["deprecated"] = True
                tags = list(op.get("tags") or [])
                if "legacy" not in tags:
                    tags.insert(0, "legacy")
                op["tags"] = tags
                op["x-legacy"] = True
                op["x-deprecation-policy"] = (
                    "See contracts/deprecation-policy.md. Bug fixes only; "
                    "no new functionality."
                )
            else:
                op["x-canonical"] = True
    return spec


def _extract_dto_schema(openapi: dict, name: str) -> dict:
    schemas = openapi.get("components", {}).get("schemas", {})
    if name not in schemas:
        raise KeyError(f"DTO {name!r} not found in OpenAPI components.schemas")
    sch = copy.deepcopy(schemas[name])
    sch["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    sch["$id"] = f"https://aquasavannah.landvault/contracts/v1/schemas/{name}.json"
    sch["title"] = name
    sch["x-contract-version"] = CONTRACT_VERSION
    # Inline any $ref to other component schemas so each DTO is independently usable.
    # (For Phase 1C none of the listed DTOs ref another, but we keep the safety pass.)
    return sch


def _build_event_schema(defn: dict) -> dict:
    """Build a per-event JSON Schema that validates the full envelope."""
    payload_props = {}
    for fname, fdesc in defn["payload_fields"].items():
        payload_props[fname] = {"description": fdesc, "type": ["string", "number", "boolean",
                                                                "object", "array", "null"]}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://aquasavannah.landvault/contracts/v1/events/{defn['event_name']}.v{defn['version']}.json",
        "title": defn["event_name"],
        "description": (
            f"Domain event emitted by the `{defn['producer']}` bounded "
            f"context for aggregate `{defn['aggregate']}`. "
            "Schema validates the full envelope; `payload` carries the "
            "aggregate-specific fields documented under "
            "`x-payload-fields`."
        ),
        "x-event-name": defn["event_name"],
        "x-event-version": defn["version"],
        "x-aggregate": defn["aggregate"],
        "x-bounded-context": defn["bounded_context"],
        "x-producer": defn["producer"],
        "x-known-consumers": defn["known_consumers"],
        "x-idempotency": defn["idempotency_requirements"],
        "x-ordering": defn["ordering_guarantees"],
        "x-replay": defn["replay_support"],
        "x-payload-fields": defn["payload_fields"],
        "x-contract-version": CONTRACT_VERSION,
        "type": "object",
        "additionalProperties": False,
        "required": [
            "event_id", "event_type", "event_version", "aggregate_type",
            "aggregate_id", "aggregate_version", "occurred_at", "producer",
            "payload",
        ],
        "properties": {
            "event_id": {"type": "string", "pattern": "^evt_[a-f0-9]{32}$"},
            "event_type": {"type": "string", "const": defn["event_name"]},
            "event_version": {"type": "integer", "const": defn["version"]},
            "aggregate_type": {"type": "string", "const": defn["aggregate"]},
            "aggregate_id": {"type": "string"},
            "aggregate_version": {"type": "integer", "minimum": 0},
            "occurred_at": {"type": "string", "format": "date-time"},
            "producer": {"type": "string", "const": defn["producer"]},
            "tenant_id": {"type": ["string", "null"]},
            "country": {"type": ["string", "null"]},
            "organization_id": {"type": ["string", "null"]},
            "correlation_id": {"type": ["string", "null"]},
            "causation_id": {"type": ["string", "null"]},
            "actor": {"type": ["string", "null"]},
            "payload": {
                "type": "object",
                "additionalProperties": True,
                "properties": payload_props,
            },
        },
    }


def _build_event_catalog() -> dict:
    entries = []
    for defn in EVENT_DEFINITIONS:
        entries.append({
            "event_name": defn["event_name"],
            "version": defn["version"],
            "aggregate": defn["aggregate"],
            "bounded_context": defn["bounded_context"],
            "producer": defn["producer"],
            "known_consumers": defn["known_consumers"],
            "payload_schema": f"v1/events/{defn['event_name']}.v{defn['version']}.json",
            "idempotency_requirements": defn["idempotency_requirements"],
            "ordering_guarantees": defn["ordering_guarantees"],
            "replay_support": defn["replay_support"],
        })
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://aquasavannah.landvault/contracts/v1/events/catalog.json",
        "x-contract-version": CONTRACT_VERSION,
        "description": (
            "Authoritative catalog of every domain event emitted by the "
            "platform. New events are added by minor version bumps; "
            "breaking changes to an existing event MUST mint a new "
            "`event_type` per kernel.events.envelope versioning policy."
        ),
        "events": entries,
    }


def _build_error_contract(spec: dict) -> dict:
    extra_props = spec.get("extra_fields") or {}
    required = ["title", "status", "code", "type"]
    properties = {
        "type": {"type": "string", "format": "uri",
                  "description": "Stable, dereferenceable URI identifying the problem type."},
        "title": {"type": "string", "const": spec["title"]},
        "status": {"type": "integer", "const": spec["status"]},
        "code": {"type": "string", "const": spec["code"]},
        "detail": {"type": ["string", "null"]},
        "instance": {"type": ["string", "null"]},
        "correlation_id": {"type": ["string", "null"],
                            "description": "Request correlation id for support tooling."},
    }
    for k, v in extra_props.items():
        properties[k] = v
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://aquasavannah.landvault/contracts/v1/errors/{spec['name']}.json",
        "title": spec["name"],
        "description": spec["description"],
        "x-rfc": "RFC 7807",
        "x-contract-version": CONTRACT_VERSION,
        "x-http-status": spec["status"],
        "x-error-code": spec["code"],
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


# ---------------------------------------------------------------------------
# Security contracts
# ---------------------------------------------------------------------------

def _build_security_contracts() -> dict[str, dict]:
    """Generate `permissions.json`, `role_matrix.json`, `field_projection.json`."""
    from contexts.identity.domain.value_objects import (  # type: ignore
        ALL_ROLES, GOVERNANCE_ROLES, SURVEY_ROLES, COMMUNITY_ROLES,
        OBSERVER_ROLES, FIELD_ROLES, Role,
    )
    from kernel.authorization.policy_library import LOCKED_STATES  # type: ignore

    role_descriptions = {
        Role.GENERAL_USER.value: "Default authenticated principal — owns their own data only.",
        Role.SURVEYOR_GENERAL.value: "Country-level survey authority. Governance role.",
        Role.SURVEYOR.value: "Operational surveyor — may update assignments while in progress.",
        Role.FIELD_AGENT.value: "Field operator executing tasks assigned to them by email.",
        Role.SUPER_ADMIN.value: "Platform super-admin — bypasses tenant/country isolation.",
        Role.COMPLIANCE_OFFICER.value: "Compliance & audit overseer. Governance role.",
        Role.LICENSED_SURVEYOR.value: "Externally-licensed surveyor authorized to file plans.",
        Role.SURVEYOR_PARTNER.value: "Surveying firm/partner organisation member.",
        Role.COMMUNITY_VALIDATOR.value: "Community validator — chairman, traditional ruler.",
        Role.GOVERNMENT_OBSERVER.value: "Government observer — read-only oversight access.",
    }

    role_sets = {
        "GOVERNANCE_ROLES": sorted(GOVERNANCE_ROLES),
        "SURVEY_ROLES": sorted(SURVEY_ROLES),
        "COMMUNITY_ROLES": sorted(COMMUNITY_ROLES),
        "OBSERVER_ROLES": sorted(OBSERVER_ROLES),
        "FIELD_ROLES": sorted(FIELD_ROLES),
    }

    role_matrix = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://aquasavannah.landvault/contracts/v1/security/role_matrix.json",
        "x-contract-version": CONTRACT_VERSION,
        "description": (
            "The 10 canonical platform roles. This list is binding — no "
            "new roles may be introduced. Future domains add namespaced "
            "permissions, not new roles."
        ),
        "roles": [
            {"name": r, "description": role_descriptions[r]}
            for r in sorted(ALL_ROLES)
        ],
        "role_sets": role_sets,
    }

    # Permissions / ABAC patterns derived from policy_library factories.
    # Each entry is a binding pattern, not a concrete (resource_type, action)
    # binding — the latter are minted by each bounded context.
    permissions = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://aquasavannah.landvault/contracts/v1/security/permissions.json",
        "x-contract-version": CONTRACT_VERSION,
        "description": (
            "ABAC permission patterns + concrete identity-bound "
            "permissions. The PDP evaluates these in priority order; "
            "default DENY (ADR-002, fail closed)."
        ),
        "default_decision": "DENY",
        "platform_policies": [
            {
                "id": "platform.tenant_isolation",
                "priority": 10,
                "effect": "DENY",
                "description": "Deny cross-tenant access unless super_admin.",
                "scope": "tenant",
            },
            {
                "id": "platform.country_isolation",
                "priority": 11,
                "effect": "DENY",
                "description": "Deny cross-country access unless super_admin.",
                "scope": "country",
            },
            {
                "id": "platform.super_admin",
                "priority": 20,
                "effect": "PERMIT",
                "description": "super_admin can do anything within their scope.",
                "scope": "global",
            },
            {
                "id": "platform.anonymous_public",
                "priority": 30,
                "effect": "PERMIT/DENY",
                "description": (
                    "Anonymous principals may only perform whitelisted "
                    "actions: identity.register, identity.login, "
                    "identity.refresh, identity.jwks.read, and "
                    "platform.public.*."
                ),
                "scope": "anonymous",
            },
            {
                "id": "identity.self",
                "priority": 40,
                "effect": "PERMIT",
                "description": (
                    "Authenticated principals may operate on their own "
                    "user record (identity.self.read, identity.self.logout, "
                    "and identity.user.read when targeting self)."
                ),
                "scope": "self",
            },
        ],
        "abac_patterns": [
            {
                "pattern": "owner_or_privileged_read",
                "applies_to_actions": ["<resource_type>.read"],
                "permit_when": [
                    "principal has any role in `privileged_roles`",
                    "principal owns the resource (owner_id == principal_id)",
                    "principal email == owner_email",
                    "principal email == assigned_to",
                ],
                "obligations": [
                    "project_fields(fields=projection_fields) when principal is owner-only"
                ],
                "default": "DEFER (no decision -> default DENY)",
            },
            {
                "pattern": "locked_state_guard",
                "applies_to_actions": ["<resource_type>.update"],
                "deny_when": [
                    "resource.status in LOCKED_STATES AND principal owns resource AND principal lacks any privileged role"
                ],
                "locked_states": sorted(LOCKED_STATES),
            },
            {
                "pattern": "role_conditional_on_status",
                "applies_to_actions": ["<resource_type>.<action>"],
                "permit_when": [
                    "role in principal.roles AND resource.status in allowed_statuses"
                ],
                "deny_when": [
                    "role in principal.roles AND resource.status not in allowed_statuses"
                ],
            },
            {
                "pattern": "delete_super_admin_only",
                "applies_to_actions": ["<resource_type>.delete"],
                "permit_when": ["principal has role super_admin"],
                "deny_when": ["otherwise"],
                "notes": "Prefer soft delete; all deletes are always audited.",
            },
            {
                "pattern": "create_owner_stamp",
                "applies_to_actions": ["<resource_type>.create"],
                "permit_when": [
                    "principal is authenticated",
                    "principal has any role in `creator_roles` (if restricted)",
                ],
                "obligations": ["stamp_owner(principal_id=principal_id)"],
            },
        ],
        "identity_actions": [
            {"action": "identity.register", "anonymous": True, "description": "Create a local user account."},
            {"action": "identity.login", "anonymous": True, "description": "Local email+password login."},
            {"action": "identity.refresh", "anonymous": True, "description": "Refresh-token rotation."},
            {"action": "identity.jwks.read", "anonymous": True, "description": "RFC 7517 public key set."},
            {"action": "identity.self.read", "anonymous": False, "description": "Read own user record (GET /v1/auth/me)."},
            {"action": "identity.self.logout", "anonymous": False, "description": "Revoke own session."},
            {"action": "identity.user.read", "anonymous": False, "required_roles": [], "description": "Read a user record (self or governance)."},
            {"action": "identity.user.suspend", "required_roles": sorted(GOVERNANCE_ROLES)},
            {"action": "identity.user.activate", "required_roles": sorted(GOVERNANCE_ROLES)},
            {"action": "identity.role.assign", "required_roles": [Role.SUPER_ADMIN.value, Role.COMPLIANCE_OFFICER.value]},
            {"action": "identity.service_account.create", "required_roles": [Role.SUPER_ADMIN.value]},
            {"action": "identity.service_account.revoke", "required_roles": [Role.SUPER_ADMIN.value]},
            {"action": "identity.delegation.grant", "required_roles": sorted(GOVERNANCE_ROLES)},
            {"action": "identity.delegation.revoke", "required_roles": sorted(GOVERNANCE_ROLES)},
        ],
    }

    field_projection = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://aquasavannah.landvault/contracts/v1/security/field_projection.json",
        "x-contract-version": CONTRACT_VERSION,
        "description": (
            "Per-resource field projection rules. Backend AND frontend "
            "MUST derive PII/visibility behaviour from this table — never "
            "by copying logic across layers. The `owner` projection is "
            "applied as an obligation by the PEP; the `public` projection "
            "is what un-elevated callers see; the `privileged` projection "
            "is what governance roles see."
        ),
        "projections": {
            "identity.user": {
                "public": ["user_id", "full_name", "roles", "country"],
                "owner": [
                    "user_id", "email", "full_name", "roles", "country",
                    "tenant_id", "organization_id", "account_status",
                    "created_at",
                ],
                "privileged": [
                    "user_id", "email", "full_name", "roles", "country",
                    "tenant_id", "organization_id", "lga_code",
                    "account_status", "suspension_reason", "last_login_at",
                    "created_at", "updated_at",
                ],
                "redacted_for_public": [
                    "email", "tenant_id", "organization_id", "lga_code",
                    "suspension_reason", "last_login_at",
                ],
                "pii_fields": ["email", "full_name"],
            },
            "identity.service_account": {
                "public": [],
                "owner": ["account_id", "name", "scopes", "tenant_id",
                          "country", "organization_id", "created_at"],
                "privileged": [
                    "account_id", "name", "description", "scopes",
                    "tenant_id", "country", "organization_id",
                    "revoked", "created_at", "revoked_at",
                ],
                "pii_fields": [],
            },
            "identity.delegation": {
                "public": [],
                "owner": [
                    "delegation_id", "delegator_id", "delegate_id",
                    "scope", "valid_from", "valid_until",
                ],
                "privileged": [
                    "delegation_id", "delegator_id", "delegate_id",
                    "scope", "valid_from", "valid_until", "reason",
                    "revoked", "revoked_at", "created_at",
                ],
                "pii_fields": [],
            },
        },
    }

    return {
        "permissions.json": permissions,
        "role_matrix.json": role_matrix,
        "field_projection.json": field_projection,
    }


# ---------------------------------------------------------------------------
# Generation orchestration
# ---------------------------------------------------------------------------

@dataclass
class Artifact:
    relpath: str   # path relative to /app/contracts/
    content: str   # canonical bytes-as-string

    @property
    def absolute(self) -> Path:
        return CONTRACT_DIR / self.relpath


def _build_artifacts() -> list[Artifact]:
    openapi = _load_openapi()
    out: list[Artifact] = []
    out.append(Artifact("v1/openapi.json", _dumps(openapi)))

    for dto in REQUEST_DTOS:
        sch = _extract_dto_schema(openapi, dto)
        out.append(Artifact(f"v1/schemas/requests/{dto}.json", _dumps(sch)))
    for dto in RESPONSE_DTOS:
        sch = _extract_dto_schema(openapi, dto)
        out.append(Artifact(f"v1/schemas/responses/{dto}.json", _dumps(sch)))

    out.append(Artifact("v1/events/catalog.json", _dumps(_build_event_catalog())))
    for defn in EVENT_DEFINITIONS:
        sch = _build_event_schema(defn)
        out.append(Artifact(
            f"v1/events/{defn['event_name']}.v{defn['version']}.json",
            _dumps(sch),
        ))

    for spec in ERROR_CONTRACTS:
        sch = _build_error_contract(spec)
        out.append(Artifact(f"v1/errors/{spec['name']}.json", _dumps(sch)))

    sec = _build_security_contracts()
    for name, doc in sec.items():
        out.append(Artifact(f"v1/security/{name}", _dumps(doc)))

    return out


def _sha_index(artifacts: list[Artifact]) -> dict[str, str]:
    return {a.relpath: _sha256(a.content) for a in artifacts}


def _build_sdk_metadata(artifacts: list[Artifact]) -> list[Artifact]:
    shas = _sha_index(artifacts)
    aggregate = _sha256("".join(f"{p}:{shas[p]}\n" for p in sorted(shas)))
    sdk_version = f"{CONTRACT_VERSION}+sdk.1"
    sdk_version_file = Artifact("v1/sdk/sdk.version", sdk_version + "\n")
    contract_sha = Artifact(
        "v1/sdk/contract.sha256",
        "\n".join(f"{shas[p]}  {p}" for p in sorted(shas)) + "\n",
    )
    compatibility = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://aquasavannah.landvault/contracts/v1/sdk/compatibility.json",
        "contract_version": CONTRACT_VERSION,
        "sdk_version": sdk_version,
        "aggregate_sha256": aggregate,
        "min_supported_contract": "1.0.0",
        "max_supported_contract": "1.x.x",
        "breaks_on_major_bump": True,
        "compatible_languages": ["typescript", "python"],
        "regeneration_command": "python -m contracts.generate",
        "drift_check_command": "bash contracts/ci_check_drift.sh",
        "artifacts": [
            {"path": p, "sha256": shas[p]} for p in sorted(shas)
        ],
    }
    compat_artifact = Artifact("v1/sdk/compatibility.json", _dumps(compatibility))
    return [sdk_version_file, contract_sha, compat_artifact]


def _build_release_manifest(all_artifacts: list[Artifact]) -> Artifact:
    shas = _sha_index(all_artifacts)
    openapi_sha = shas["v1/openapi.json"]
    event_catalog_sha = shas["v1/events/catalog.json"]
    # Aggregate "schema" SHA covers every per-DTO schema file deterministically.
    schema_files = sorted(p for p in shas if p.startswith("v1/schemas/"))
    schema_aggregate = _sha256("".join(f"{p}:{shas[p]}\n" for p in schema_files))
    sdk_sha = shas.get("v1/sdk/contract.sha256", "")
    manifest = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://aquasavannah.landvault/contracts/release-manifest.json",
        "contract_version": CONTRACT_VERSION,
        "build_timestamp": datetime(2026, 6, 28, tzinfo=timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "adr_references": [
            "ADR-0001 — Platform Contract Freeze (v1/adr/ADR-0001-platform-contract-freeze.md)",
            "ADR-002 — Centralized Authorization Engine (default DENY)",
            "ADR-007 — Routers are composition only",
        ],
        "checksums": {
            "openapi_sha256": openapi_sha,
            "event_catalog_sha256": event_catalog_sha,
            "schema_aggregate_sha256": schema_aggregate,
            "sdk_contract_sha256": sdk_sha,
        },
        "files": [
            {"path": p, "sha256": shas[p]} for p in sorted(shas)
        ],
    }
    return Artifact("release-manifest.json", _dumps(manifest))


def build_full_package() -> list[Artifact]:
    """Build every artifact in the contract package, deterministically."""
    artifacts = _build_artifacts()
    sdk_artifacts = _build_sdk_metadata(artifacts)
    artifacts.extend(sdk_artifacts)
    # release manifest is computed over EVERY v1 artifact + sdk
    release = _build_release_manifest(artifacts)
    artifacts.append(release)
    return artifacts


# ---------------------------------------------------------------------------
# Write / check entry points
# ---------------------------------------------------------------------------

def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_all() -> list[Artifact]:
    artifacts = build_full_package()
    for a in artifacts:
        _ensure_parent(a.absolute)
        a.absolute.write_text(a.content)
    return artifacts


def diff_against_disk() -> tuple[list[Artifact], list[tuple[Artifact, str]]]:
    """Return (artifacts, mismatches). `mismatches` is a list of (artifact, on_disk_content)."""
    artifacts = build_full_package()
    mismatches: list[tuple[Artifact, str]] = []
    for a in artifacts:
        if not a.absolute.exists():
            mismatches.append((a, "<MISSING>"))
            continue
        on_disk = a.absolute.read_text()
        if on_disk != a.content:
            mismatches.append((a, on_disk))
    return artifacts, mismatches


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AquaSavannah LandVault — Contract Package Generator")
    parser.add_argument("--check", action="store_true",
                        help="Verify the on-disk freeze matches what would be generated.")
    args = parser.parse_args(argv)
    if args.check:
        _, mismatches = diff_against_disk()
        if mismatches:
            print(f"CONTRACT DRIFT DETECTED — {len(mismatches)} file(s) differ:",
                  file=sys.stderr)
            for a, _ in mismatches:
                print(f"  • {a.relpath}", file=sys.stderr)
            print("\nIf this change is intentional:", file=sys.stderr)
            print("  1. Bump contracts/VERSION (semver).", file=sys.stderr)
            print("  2. Add an ADR under contracts/v1/adr/.", file=sys.stderr)
            print("  3. Append an entry to contracts/CHANGELOG.md referencing the ADR.", file=sys.stderr)
            print("  4. Re-run `python -m contracts.generate` and commit the result.", file=sys.stderr)
            return 1
        print("Contract freeze OK — no drift.")
        return 0
    artifacts = write_all()
    print(f"Wrote {len(artifacts)} contract artifacts (version {CONTRACT_VERSION}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
