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
from typing import Any, Optional

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
    # Phase 2 — Registry
    "CreateLandVaultRequest",
    "UpdateLocationRequest",
    "UpdateGeometryRequest",
    "UpdateOwnershipContactRequest",
    "RecordOwnershipTransferRequest",
    "UpdateSurveyRequest",
    "UpdateCommunityDataRequest",
    "ArchiveLandVaultRequest",
    # Phase 3.4 + 3.5 — Evidence
    "InitiateEvidenceUploadRequest",
    "CompleteEvidenceUploadRequest",
    "IssueSignedUrlRequest",
    "CreateSealRequest",
    "ApplySealWormRequest",
    # Phase 3.6 — Anchoring + Locking + Integrity
    "ReplayAnchorBatchRequest",
    "ExtendLockRetentionRequest",
    "TriggerIntegrityCheckRequest",
    # Phase 4 — Workflow bounded context (Slice 4.0 Foundation)
    "StartWorkflowRequest",
    "CancelWorkflowRequest",
    "SuspendWorkflowRequest",
    "ReactivateWorkflowRequest",
    "CompleteTaskRequest",
)
RESPONSE_DTOS = (
    "TokenResponse",
    # Phase 2 — Registry
    "LandVaultResponse",
    "LandVaultListResponse",
    # Phase 3.4 + 3.5 — Evidence
    "InitiateEvidenceUploadResponse",
    "EvidenceItemResponse",
    "EvidenceItemListResponse",
    "SignedUrlResponse",
    "SealResponse",
    # Phase 3.6 — Anchoring + Locking + Integrity
    "AnchorBatchResponse",
    "EvidenceLockResponse",
    "EvidenceLockListResponse",
    "IntegrityCheckResponse",
    "IntegrityChainResponse",
    "CtlogCheckpointResponse",
    # Phase 3.8 — Projection engine admin
    "ProjectionStatusResponse",
    "ProjectionListResponse",
    # Phase 4 — Workflow bounded context (Slice 4.0 Foundation)
    "WorkflowInstanceResponse",
    "WorkflowInstanceListResponse",
    "WorkflowTaskResponse",
    "WorkflowTaskListResponse",
    "WorkflowTimerResponse",
    "WorkflowTimerListResponse",
    "WorkflowReplayResponse",
    "WorkflowDefinitionResponse",
    "WorkflowDefinitionListResponse",
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
    # ---- Phase 2 — Registry bounded context -----------------------------
    {
        "event_name": "registry.landvault.created",
        "version": 1,
        "aggregate": "LandVault",
        "bounded_context": "registry",
        "producer": "registry",
        "known_consumers": ["audit-log", "metrics", "search-index", "evidence",
                             "verification", "community", "certificate"],
        "idempotency_requirements": "Dedup by `event_id`. Producer emits inside the same Mongo tx as the aggregate write (transactional outbox).",
        "ordering_guarantees": "Per-LandVault ordering by `aggregate_version`.",
        "replay_support": "Idempotent — events can be replayed from the outbox.",
        "payload_fields": {
            "registry_id": "string — immutable internal id",
            "parcel_number": "string — STATE-LGA-WARD-PROPTYPE-NNNNNN",
            "tenant_id": "string",
            "country_code": "string — ISO-3166-1 alpha-2",
            "created_by": "string — principal id",
            "status": "string — initial LandVaultStatus (always 'draft' for native creates)",
            "ownership_type": "string — initial OwnershipType",
            "origin": "object — { source_system, source_id, import_batch }",
            "has_geometry": "boolean",
        },
    },
    {
        "event_name": "registry.landvault.updated",
        "version": 1,
        "aggregate": "LandVault",
        "bounded_context": "registry",
        "producer": "registry",
        "known_consumers": ["audit-log", "metrics", "search-index"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-LandVault ordering by `aggregate_version`.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "facet": "string — 'location' | 'geometry' | 'ownership_contact' | 'ownership_transfer' | 'survey' | 'community_data'",
            "changes": "object|array — keys/values that changed (omitted for sensitive facets)",
            "actor": "string — principal id who performed the update",
            "reason": "string|null — present for ownership_transfer",
            "boundary_source": "string|null — present for geometry updates",
        },
    },
    {
        "event_name": "registry.parcel_reference.allocated",
        "version": 1,
        "aggregate": "LandVault",
        "bounded_context": "registry",
        "producer": "registry",
        "known_consumers": ["audit-log", "metrics"],
        "idempotency_requirements": (
            "Dedup by `event_id`. The allocator itself is atomic and never "
            "reuses sequence numbers, so each event corresponds to a unique "
            "ParcelNumber."
        ),
        "ordering_guarantees": "Per-sequence_key ordering by sequence_number.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "registry_id": "string",
            "parcel_number": "string",
            "sequence_key": "string — STATE-LGA-WARD-PROPTYPE",
            "sequence_number": "integer — strictly increasing within sequence_key",
        },
    },
    {
        "event_name": "registry.ownership.recorded",
        "version": 1,
        "aggregate": "LandVault",
        "bounded_context": "registry",
        "producer": "registry",
        "known_consumers": ["audit-log", "metrics", "notifications", "search-index"],
        "idempotency_requirements": (
            "Dedup by `event_id`. Producers emit ONLY on legal ownership "
            "changes — ordinary contact edits (phone/email) MUST NOT "
            "emit this event."
        ),
        "ordering_guarantees": "Per-LandVault ordering by `aggregate_version`.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "registry_id": "string",
            "ownership_type": "string — current OwnershipType",
            "owner_name": "string — current owner name",
            "reason": "string — 'initial registration' | 'purchase' | 'inheritance' | ...",
            "recorded_by": "string|null — principal id",
            "history_length": "integer — append-only history depth after this event",
        },
    },
    {
        "event_name": "registry.landvault.archived",
        "version": 1,
        "aggregate": "LandVault",
        "bounded_context": "registry",
        "producer": "registry",
        "known_consumers": ["audit-log", "metrics", "search-index", "evidence"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-LandVault ordering by `aggregate_version`. Always the terminal event for an aggregate.",
        "replay_support": "Idempotent. Archive is one-way.",
        "payload_fields": {
            "actor": "string — super_admin principal id",
            "reason": "string — operator-supplied reason",
            "archived_at": "string — ISO8601 timestamp",
        },
    },
    # ---- Phase 3.4 + 3.5 — Evidence bounded context ---------------------
    {
        "event_name": "evidence.item.uploaded",
        "version": 1,
        "aggregate": "EvidenceItem",
        "bounded_context": "evidence",
        "producer": "evidence",
        "known_consumers": ["audit-log", "metrics", "verification"],
        "idempotency_requirements": "Dedup by `event_id`. Producer emits inside the same Mongo tx as the aggregate write (transactional outbox).",
        "ordering_guarantees": "Per-EvidenceItem ordering by `aggregate_version`.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "evidence_id": "string — immutable internal id",
            "registry_id": "string — owning LandVault id",
            "kind": "string — EvidenceKind value",
            "size_bytes": "integer — total stored size",
            "media_type": "string — RFC 2045 media type",
            "storage_provider": "string — 'local_fs_worm' | 'r2'",
        },
    },
    {
        "event_name": "evidence.item.hash_verified",
        "version": 1,
        "aggregate": "EvidenceItem",
        "bounded_context": "evidence",
        "producer": "evidence",
        "known_consumers": ["audit-log", "metrics", "verification"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-EvidenceItem ordering by `aggregate_version`.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "evidence_id": "string",
            "registry_id": "string",
            "server_hash": "string — SHA-256 hex digest (server-authoritative)",
            "hash_algorithm": "string — always 'SHA-256' for v1",
        },
    },
    {
        "event_name": "evidence.item.hash_mismatch",
        "version": 1,
        "aggregate": "EvidenceItem",
        "bounded_context": "evidence",
        "producer": "evidence",
        "known_consumers": ["audit-log", "security-incident", "metrics"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-EvidenceItem ordering by `aggregate_version`.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "evidence_id": "string",
            "registry_id": "string",
            "reason": "string — 'readback_streamed_mismatch' | 'client_claim_mismatch'",
            "server_hash_streamed": "string|null",
            "server_hash": "string|null",
            "client_hash_claim": "string|null",
            "readback_sha256": "string|null",
        },
    },
    {
        "event_name": "evidence.item.archived_replaced",
        "version": 1,
        "aggregate": "EvidenceItem",
        "bounded_context": "evidence",
        "producer": "evidence",
        "known_consumers": ["audit-log", "search-index", "verification"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-EvidenceItem ordering. Terminal for the old aggregate.",
        "replay_support": "Idempotent. Archive is one-way.",
        "payload_fields": {
            "evidence_id": "string",
            "registry_id": "string",
            "replaced_by": "string — new EvidenceItem id produced by the remediation cutover",
            "reason": "string",
        },
    },
    {
        "event_name": "evidence.seal.created",
        "version": 1,
        "aggregate": "Seal",
        "bounded_context": "evidence",
        "producer": "evidence",
        "known_consumers": ["audit-log", "metrics", "verification", "certificate"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-Seal ordering by `aggregate_version`.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "seal_id": "string — immutable seal id",
            "registry_id": "string",
            "evidence_ids": "string[] — items included in the seal manifest",
            "merkle_root": "string — SHA-256 hex digest of the canonical merkle tree",
            "manifest_hash": "string — SHA-256 hex of canonical_json(manifest)",
            "item_count": "integer",
            "created_by": "string — principal id",
        },
    },
    {
        "event_name": "evidence.seal.worm_applied",
        "version": 1,
        "aggregate": "Seal",
        "bounded_context": "evidence",
        "producer": "evidence",
        "known_consumers": ["audit-log", "metrics", "verification"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-Seal ordering. Strict successor of `evidence.seal.created`.",
        "replay_support": "Idempotent. WORM is one-way.",
        "payload_fields": {
            "seal_id": "string",
            "registry_id": "string",
            "applied_by": "string — principal id",
            "item_count": "integer",
            "items": "object[] — per-item lock outcome { evidence_id, storage_locator, locked, retention_until }",
            "retention_until": "string — ISO8601 retention floor",
        },
    },
    {
        "event_name": "evidence.seal.archived",
        "version": 1,
        "aggregate": "Seal",
        "bounded_context": "evidence",
        "producer": "evidence",
        "known_consumers": ["audit-log", "metrics"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-Seal ordering. Terminal.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "seal_id": "string",
            "registry_id": "string",
            "actor": "string — principal id",
            "reason": "string",
        },
    },
    {
        "event_name": "evidence.signed_url.issued",
        "version": 1,
        "aggregate": "EvidenceItem",
        "bounded_context": "evidence",
        "producer": "evidence",
        "known_consumers": ["audit-log", "security-incident"],
        "idempotency_requirements": "Dedup by `event_id`. The signed-URL audit row is the durable source of truth; this event is a fan-out signal for downstream consumers.",
        "ordering_guarantees": "No global ordering required.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "evidence_id": "string",
            "registry_id": "string",
            "principal_id": "string",
            "action": "string — 'read' | 'verify' | 'export'",
            "ttl_seconds": "integer",
            "url_sha256": "string — sha256 of the URL (the URL plaintext is never stored)",
        },
    },
    # ---- Phase 3.6 — Anchoring + Integrity + Locking --------------------
    {
        "event_name": "evidence.lock.applied", "version": 1,
        "aggregate": "EvidenceLock", "bounded_context": "evidence",
        "producer": "evidence",
        "known_consumers": ["audit-log", "metrics"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-EvidenceLock ordering by `aggregate_version`.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "lock_id": "string", "evidence_id": "string", "seal_id": "string",
            "storage_provider": "string", "storage_locator": "string",
            "mode": "string — always 'compliance' in v1",
            "retention_until": "string ISO8601", "applied_by": "string",
        },
    },
    {
        "event_name": "evidence.lock.extended", "version": 1,
        "aggregate": "EvidenceLock", "bounded_context": "evidence",
        "producer": "evidence",
        "known_consumers": ["audit-log", "metrics"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-EvidenceLock ordering by `aggregate_version`.",
        "replay_support": "Idempotent; forward-only retention.",
        "payload_fields": {
            "lock_id": "string", "evidence_id": "string",
            "previous_until": "string ISO8601", "new_until": "string ISO8601",
            "by": "string", "reason": "string",
        },
    },
    {
        "event_name": "evidence.integrity.check_started", "version": 1,
        "aggregate": "EvidenceIntegrityCheck", "bounded_context": "evidence",
        "producer": "evidence",
        "known_consumers": ["audit-log", "metrics"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-EvidenceIntegrityCheck ordering by `seq`.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "check_id": "string", "evidence_id": "string",
            "triggered_by": "string — IntegrityTrigger enum value",
            "expected_hash": "string SHA-256", "seq": "integer",
        },
    },
    {
        "event_name": "evidence.integrity.passed", "version": 1,
        "aggregate": "EvidenceIntegrityCheck", "bounded_context": "evidence",
        "producer": "evidence",
        "known_consumers": ["audit-log", "metrics", "verification"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-EvidenceIntegrityCheck ordering. Terminal-positive.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "check_id": "string", "evidence_id": "string",
            "triggered_by": "string",
            "expected_hash": "string", "observed_hash": "string",
        },
    },
    {
        "event_name": "evidence.integrity.failed", "version": 1,
        "aggregate": "EvidenceIntegrityCheck", "bounded_context": "evidence",
        "producer": "evidence",
        "known_consumers": ["audit-log", "security-incident", "metrics"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-EvidenceIntegrityCheck ordering. Terminal-negative.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "check_id": "string", "evidence_id": "string",
            "triggered_by": "string",
            "expected_hash": "string", "observed_hash": "string",
            "reason": "string",
        },
    },
    {
        "event_name": "evidence.integrity.check_errored", "version": 1,
        "aggregate": "EvidenceIntegrityCheck", "bounded_context": "evidence",
        "producer": "evidence",
        "known_consumers": ["audit-log", "metrics"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-EvidenceIntegrityCheck ordering.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "check_id": "string", "evidence_id": "string",
            "triggered_by": "string", "error_summary": "string",
        },
    },
    {
        "event_name": "evidence.anchor.batched", "version": 1,
        "aggregate": "AnchorBatch", "bounded_context": "evidence",
        "producer": "evidence",
        "known_consumers": ["audit-log", "metrics", "verification"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-AnchorBatch ordering by `aggregate_version`.",
        "replay_support": "Idempotent. Saga rebuilds state from attempts chain.",
        "payload_fields": {
            "batch_id": "string", "provider_id": "string",
            "merkle_root": "string SHA-256",
            "seal_ids": "string[]", "seal_count": "integer",
            "replayed_from": "string|null",
        },
    },
    {
        "event_name": "evidence.anchor.submitted", "version": 1,
        "aggregate": "AnchorBatch", "bounded_context": "evidence",
        "producer": "evidence",
        "known_consumers": ["audit-log", "metrics"],
        "idempotency_requirements": "Dedup by `event_id`. Provider-side dedup keyed on `(batch_id, merkle_root)`.",
        "ordering_guarantees": "Per-AnchorBatch ordering.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "batch_id": "string", "provider_id": "string",
            "provider_request_id": "string", "attempts": "integer",
        },
    },
    {
        "event_name": "evidence.anchor.confirmed", "version": 1,
        "aggregate": "AnchorBatch", "bounded_context": "evidence",
        "producer": "evidence",
        "known_consumers": ["audit-log", "metrics", "verification", "certificate"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-AnchorBatch ordering. Terminal-positive.",
        "replay_support": "Idempotent. Inclusion proofs are deterministic.",
        "payload_fields": {
            "batch_id": "string", "provider_id": "string",
            "merkle_root": "string SHA-256",
            "seal_ids": "string[]",
            "confirmed_at": "string ISO8601",
        },
    },
    {
        "event_name": "evidence.anchor.failed", "version": 1,
        "aggregate": "AnchorBatch", "bounded_context": "evidence",
        "producer": "evidence",
        "known_consumers": ["audit-log", "metrics", "ops-alerting"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-AnchorBatch ordering. Recoverable via replay when terminal.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "batch_id": "string", "provider_id": "string",
            "reason": "string", "attempts": "integer",
            "transient": "boolean", "terminal": "boolean (optional)",
            "next_attempt_at": "string ISO8601 (optional)",
        },
    },
    {
        "event_name": "evidence.anchor.replayed", "version": 1,
        "aggregate": "AnchorBatch", "bounded_context": "evidence",
        "producer": "evidence",
        "known_consumers": ["audit-log", "verification"],
        "idempotency_requirements": "Dedup by `event_id`. Original DLQ batch is frozen.",
        "ordering_guarantees": "Per-AnchorBatch ordering. References a NEW batch_id.",
        "replay_support": "Idempotent. New batch goes through the full saga again.",
        "payload_fields": {
            "batch_id": "string — DLQ batch id",
            "provider_id": "string", "replayed_to": "string — new batch id",
        },
    },
    {
        "event_name": "evidence.ctlog.checkpoint_published", "version": 1,
        "aggregate": "CtlogTree", "bounded_context": "evidence",
        "producer": "evidence",
        "known_consumers": ["audit-log", "verification", "public-mirror"],
        "idempotency_requirements": "Dedup by `event_id`. Tree head sequence is monotonic.",
        "ordering_guarantees": "Strict monotonic order by `head_seq`.",
        "replay_support": "Idempotent. Each checkpoint is signed.",
        "payload_fields": {
            "head_seq": "integer", "tree_size": "integer",
            "root_hash": "string SHA-256", "signature_kid": "string",
            "locator": "string|null — publisher-specific reference",
        },
    },
    # ---- Phase 3.7 — Timeline + Custody + Legal Hold + Supersession ----
    {
        "event_name": "evidence.timeline.appended", "version": 1,
        "aggregate": "TimelineEntry", "bounded_context": "evidence",
        "producer": "evidence",
        "known_consumers": ["audit-log", "verification", "ui-projection"],
        "idempotency_requirements": "Dedup by `event_id`. Timeline insertion is also dedup'd by `(evidence_id, seq)` at the adapter.",
        "ordering_guarantees": "Strict per-evidence ordering by `seq`. Insert-only.",
        "replay_support": "Idempotent. Timeline is itself a projection of the upstream event stream.",
        "payload_fields": {
            "timeline_id": "string", "evidence_id": "string",
            "kind": "string — TimelineEventKind", "actor": "string",
            "seq": "integer", "occurred_at": "string ISO8601",
            "summary": "string",
        },
    },
    {
        "event_name": "evidence.custody.appended", "version": 1,
        "aggregate": "CustodyEntry", "bounded_context": "evidence",
        "producer": "evidence",
        "known_consumers": ["audit-log", "court-export", "ui-projection"],
        "idempotency_requirements": "Dedup by `event_id`. Adapter-level dedup on `(evidence_id, seq)`.",
        "ordering_guarantees": "Strict per-evidence ordering by `seq`.",
        "replay_support": "Idempotent. Each link references the previous via `previous_custody_id` + `prev_hash`.",
        "payload_fields": {
            "custody_id": "string", "evidence_id": "string",
            "action": "string — CustodyAction", "role": "string",
        },
    },
    {
        "event_name": "evidence.legal_hold.applied", "version": 1,
        "aggregate": "LegalHold", "bounded_context": "evidence",
        "producer": "evidence",
        "known_consumers": ["audit-log", "retention-sweeper", "ui-projection"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-LegalHold ordering by `aggregate_version`.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "hold_id": "string", "evidence_id": "string",
            "case_reference": "string", "issued_by": "string",
            "reason": "string",
        },
    },
    {
        "event_name": "evidence.legal_hold.released", "version": 1,
        "aggregate": "LegalHold", "bounded_context": "evidence",
        "producer": "evidence",
        "known_consumers": ["audit-log", "retention-sweeper"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-LegalHold ordering. Terminal.",
        "replay_support": "Idempotent. Release is one-way.",
        "payload_fields": {
            "hold_id": "string", "evidence_id": "string",
            "released_by": "string", "release_reason": "string",
        },
    },
    {
        "event_name": "evidence.supersession.recorded", "version": 1,
        "aggregate": "EvidenceItem", "bounded_context": "evidence",
        "producer": "evidence",
        "known_consumers": ["audit-log", "ui-projection"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-EvidenceItem ordering.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "evidence_id": "string — superseded item id",
            "replaced_by": "string — successor evidence_id",
            "superseded_reason": "string",
        },
    },
    # ---- Phase 4 Slice 4.0 — Workflow bounded context -------------------
    {
        "event_name": "workflow.instance.started", "version": 1,
        "aggregate": "WorkflowInstance", "bounded_context": "workflow",
        "producer": "workflow",
        "known_consumers": ["audit-log", "metrics", "ui-projection"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-WorkflowInstance ordering by `aggregate_version`.",
        "replay_support": "Idempotent. Replay rebuilds aggregate state via pure apply().",
        "payload_fields": {
            "instance_id": "string", "definition_name": "string",
            "definition_version": "integer", "initial_state": "string",
            "initiator_id": "string", "payload": "object",
        },
    },
    {
        "event_name": "workflow.instance.transitioned", "version": 1,
        "aggregate": "WorkflowInstance", "bounded_context": "workflow",
        "producer": "workflow",
        "known_consumers": ["audit-log", "metrics", "ui-projection"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-WorkflowInstance ordering.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "instance_id": "string", "definition_name": "string",
            "definition_version": "integer",
            "command": "string", "actor": "string",
            "from_state": "string", "to_state": "string",
            "payload": "object",
        },
    },
    {
        "event_name": "workflow.instance.completed", "version": 1,
        "aggregate": "WorkflowInstance", "bounded_context": "workflow",
        "producer": "workflow",
        "known_consumers": ["audit-log", "metrics", "saga-composer"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-WorkflowInstance ordering. Terminal-positive.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "instance_id": "string", "definition_name": "string",
            "definition_version": "integer", "final_state": "string",
        },
    },
    {
        "event_name": "workflow.instance.cancelled", "version": 1,
        "aggregate": "WorkflowInstance", "bounded_context": "workflow",
        "producer": "workflow",
        "known_consumers": ["audit-log", "metrics"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-WorkflowInstance ordering. Terminal.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "instance_id": "string", "actor": "string", "reason": "string",
            "at_state": "string",
        },
    },
    {
        "event_name": "workflow.instance.suspended", "version": 1,
        "aggregate": "WorkflowInstance", "bounded_context": "workflow",
        "producer": "workflow",
        "known_consumers": ["audit-log", "metrics", "ops-alerting"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-WorkflowInstance ordering.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "instance_id": "string", "actor": "string", "reason": "string",
        },
    },
    {
        "event_name": "workflow.instance.reactivated", "version": 1,
        "aggregate": "WorkflowInstance", "bounded_context": "workflow",
        "producer": "workflow",
        "known_consumers": ["audit-log", "metrics"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-WorkflowInstance ordering.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "instance_id": "string", "actor": "string",
        },
    },
    {
        "event_name": "workflow.task.created", "version": 1,
        "aggregate": "WorkflowTask", "bounded_context": "workflow",
        "producer": "workflow",
        "known_consumers": ["audit-log", "ui-projection", "notifications"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-WorkflowTask ordering.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "task_id": "string", "instance_id": "string",
            "definition_name": "string", "title": "string",
            "assigned_to_role": "string|null",
            "assigned_to_principal": "string|null",
            "due_at": "string|null",
        },
    },
    {
        "event_name": "workflow.task.claimed", "version": 1,
        "aggregate": "WorkflowTask", "bounded_context": "workflow",
        "producer": "workflow",
        "known_consumers": ["audit-log", "ui-projection"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-WorkflowTask ordering.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "task_id": "string", "instance_id": "string",
            "claimed_by": "string",
        },
    },
    {
        "event_name": "workflow.task.completed", "version": 1,
        "aggregate": "WorkflowTask", "bounded_context": "workflow",
        "producer": "workflow",
        "known_consumers": ["audit-log", "ui-projection", "engine"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-WorkflowTask ordering. Terminal-positive.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "task_id": "string", "instance_id": "string",
            "completed_by": "string", "payload": "object",
        },
    },
    {
        "event_name": "workflow.task.cancelled", "version": 1,
        "aggregate": "WorkflowTask", "bounded_context": "workflow",
        "producer": "workflow",
        "known_consumers": ["audit-log"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-WorkflowTask ordering. Terminal.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "task_id": "string", "instance_id": "string",
            "actor": "string", "reason": "string",
        },
    },
    {
        "event_name": "workflow.task.expired", "version": 1,
        "aggregate": "WorkflowTask", "bounded_context": "workflow",
        "producer": "workflow",
        "known_consumers": ["audit-log", "ops-alerting"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-WorkflowTask ordering. Terminal.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "task_id": "string", "instance_id": "string",
        },
    },
    {
        "event_name": "workflow.timer.scheduled", "version": 1,
        "aggregate": "WorkflowTimer", "bounded_context": "workflow",
        "producer": "workflow",
        "known_consumers": ["audit-log", "timer-runner"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-WorkflowTimer ordering.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "timer_id": "string", "instance_id": "string",
            "definition_name": "string", "fire_at": "string ISO8601",
            "command_on_fire": "string",
        },
    },
    {
        "event_name": "workflow.timer.fired", "version": 1,
        "aggregate": "WorkflowTimer", "bounded_context": "workflow",
        "producer": "workflow",
        "known_consumers": ["audit-log", "engine"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-WorkflowTimer ordering. Terminal-positive.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "timer_id": "string", "instance_id": "string",
            "command_on_fire": "string",
        },
    },
    {
        "event_name": "workflow.timer.cancelled", "version": 1,
        "aggregate": "WorkflowTimer", "bounded_context": "workflow",
        "producer": "workflow",
        "known_consumers": ["audit-log"],
        "idempotency_requirements": "Dedup by `event_id`.",
        "ordering_guarantees": "Per-WorkflowTimer ordering. Terminal.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "timer_id": "string", "instance_id": "string",
            "reason": "string",
        },
    },
    {
        "event_name": "workflow.compensation.recorded", "version": 1,
        "aggregate": "WorkflowCompensation", "bounded_context": "workflow",
        "producer": "workflow",
        "known_consumers": ["audit-log", "saga-composer"],
        "idempotency_requirements": "Dedup by `event_id`. Append-only.",
        "ordering_guarantees": "Per-instance ordering by `recorded_at`.",
        "replay_support": "Idempotent.",
        "payload_fields": {
            "compensation_id": "string", "instance_id": "string",
            "definition_name": "string", "verb": "string",
            "actor": "string", "payload": "object",
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


def _inline_refs(node: Any, schemas: dict, seen: Optional[set] = None) -> Any:
    """Recursively inline component $refs so each frozen schema is
    self-contained. Cycle-safe via a visited set."""
    if seen is None:
        seen = set()
    if isinstance(node, dict):
        if "$ref" in node and isinstance(node["$ref"], str):
            ref = node["$ref"]
            if ref.startswith("#/components/schemas/"):
                target_name = ref.rsplit("/", 1)[-1]
                if target_name in seen:
                    return {"description": f"cyclic ref to {target_name}"}
                if target_name not in schemas:
                    return node
                sub = copy.deepcopy(schemas[target_name])
                return _inline_refs(sub, schemas, seen | {target_name})
        # Walk every key recursively.
        return {k: _inline_refs(v, schemas, seen) for k, v in node.items()}
    if isinstance(node, list):
        return [_inline_refs(item, schemas, seen) for item in node]
    return node


def _extract_dto_schema(openapi: dict, name: str) -> dict:
    schemas = openapi.get("components", {}).get("schemas", {})
    if name not in schemas:
        raise KeyError(f"DTO {name!r} not found in OpenAPI components.schemas")
    sch = copy.deepcopy(schemas[name])
    sch = _inline_refs(sch, schemas, seen={name})
    sch["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    sch["$id"] = f"https://aquasavannah.landvault/contracts/v1/schemas/{name}.json"
    sch["title"] = name
    sch["x-contract-version"] = CONTRACT_VERSION
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
        "registry_actions": [
            {"action": "registry.landvault.create",
             "required_roles": ["super_admin", "field_agent", "surveyor",
                                 "surveyor_general", "compliance_officer",
                                 "licensed_surveyor", "surveyor_partner"],
             "description": "Create a new LandVault aggregate (allocates parcel_number)."},
            {"action": "registry.landvault.read",
             "description": "Read a LandVault with role-projected fields."},
            {"action": "registry.landvault.list",
             "description": "List LandVaults scoped to the caller's ExecutionContext."},
            {"action": "registry.landvault.update.location",
             "description": "Update administrative location facet."},
            {"action": "registry.landvault.update.geometry",
             "description": "Update boundary geometry (GeoJSON Polygon, WGS84)."},
            {"action": "registry.landvault.update.ownership_contact",
             "description": "Update owner contact fields (phone/email). Does NOT emit OwnershipRecorded."},
            {"action": "registry.landvault.ownership.transfer",
             "required_roles": ["super_admin", "surveyor_general",
                                 "compliance_officer", "government_observer"],
             "description": "Legal ownership change. Emits OwnershipRecorded + appends history."},
            {"action": "registry.landvault.update.survey",
             "required_roles": ["super_admin", "surveyor_general", "surveyor",
                                 "licensed_surveyor", "surveyor_partner", "field_agent"],
             "description": "Update survey facet."},
            {"action": "registry.landvault.update.community_data",
             "required_roles": ["super_admin", "surveyor_general",
                                 "compliance_officer", "community_validator"],
             "description": "Update community/consent facet."},
            {"action": "registry.landvault.archive",
             "required_roles": [Role.SUPER_ADMIN.value],
             "description": "Soft-delete. One-way. super_admin only."},
        ],
        "evidence_actions": [
            {"action": "evidence.item.upload.initiate",
             "required_roles": ["super_admin", "field_agent", "surveyor",
                                 "surveyor_general", "compliance_officer",
                                 "licensed_surveyor", "surveyor_partner"],
             "description": "Open a multipart upload session for a new EvidenceItem."},
            {"action": "evidence.item.upload.complete",
             "required_roles": ["super_admin", "field_agent", "surveyor",
                                 "surveyor_general", "compliance_officer",
                                 "licensed_surveyor", "surveyor_partner"],
             "description": "Finalize multipart upload. Server records streamed SHA-256."},
            {"action": "evidence.item.verify",
             "description": "Independent server-side read-back + SHA-256 verification."},
            {"action": "evidence.item.read",
             "description": "Read EvidenceItem metadata (role-projected)."},
            {"action": "evidence.item.list",
             "description": "List EvidenceItems scoped to the caller's ExecutionContext."},
            {"action": "evidence.item.read.signed_url",
             "description": "Issue a short-lived signed URL (TTL clamped by role)."},
            {"action": "evidence.seal.create",
             "required_roles": ["super_admin", "surveyor_general",
                                 "compliance_officer", "licensed_surveyor"],
             "description": "Create an immutable Seal manifest over verified EvidenceItems."},
            {"action": "evidence.seal.apply_worm",
             "required_roles": ["super_admin", "compliance_officer"],
             "description": "Flip the WORM gate. Activates StoragePort Object-Lock for every referenced item."},
            {"action": "evidence.seal.read",
             "description": "Read Seal manifest + status (role-projected)."},
            # Phase 3.6
            {"action": "evidence.anchor.batch.read",
             "description": "Read anchor batch state + inclusion proofs (role-projected)."},
            {"action": "evidence.anchor.batch.replay_dlq",
             "required_roles": ["super_admin"],
             "description": "Replay a DLQ batch as a NEW batch row. Original DLQ row stays frozen."},
            {"action": "evidence.lock.read",
             "description": "Read EvidenceLock + extension history."},
            {"action": "evidence.lock.extend",
             "required_roles": ["super_admin", "compliance_officer"],
             "description": "Forward-only retention extension on an EvidenceLock."},
            {"action": "evidence.integrity.trigger",
             "required_roles": ["super_admin", "compliance_officer",
                                  "government_observer"],
             "description": "Trigger an on-demand or mandatory-trigger integrity check."},
            {"action": "evidence.integrity.read",
             "description": "Read EvidenceIntegrityCheck chain (role-projected)."},
            {"action": "evidence.ctlog.checkpoint.read",
             "description": "Read the latest published CT-log tree head."},
            # Phase 3.7
            {"action": "evidence.timeline.read",
             "description": "Read the append-only Evidence Timeline chain."},
            {"action": "evidence.custody.read",
             "description": "Read the append-only chain-of-custody for an evidence item."},
            {"action": "evidence.custody.record",
             "description": "Append a custody-transfer entry (signed by the actor)."},
            {"action": "evidence.legal_hold.read",
             "description": "Read Legal Hold + status."},
            {"action": "evidence.legal_hold.apply",
             "required_roles": ["super_admin", "compliance_officer"],
             "description": "Apply an independent Legal Hold that overrides retention."},
            {"action": "evidence.legal_hold.release",
             "required_roles": ["super_admin", "compliance_officer"],
             "description": "Release a Legal Hold. Release is itself immutable."},
        ],
        "kernel_actions": [
            {"action": "kernel.projections.admin",
             "required_roles": ["super_admin"],
             "description": (
                 "Admin gate for Phase 3.8 projection engine endpoints — "
                 "health, lag inspection, replay (deterministic rebuild), "
                 "and snapshot timestamps. super_admin only (ADR-0010 §5)."
             )},
        ],
        "workflow_actions": [
            {"action": "workflow.instance.start",
             "required_roles": ["super_admin", "compliance_officer",
                                 "surveyor_general"],
             "description": "Start a new workflow instance from a frozen definition."},
            {"action": "workflow.instance.read",
             "description": "Read a workflow instance (role-projected)."},
            {"action": "workflow.instance.list",
             "description": "List workflow instances scoped to the caller."},
            {"action": "workflow.instance.cancel",
             "required_roles": ["super_admin", "compliance_officer",
                                 "surveyor_general"],
             "description": "Cancel a non-terminal workflow instance."},
            {"action": "workflow.instance.suspend",
             "required_roles": ["super_admin"],
             "description": "Suspend an instance (no commands or timers fire)."},
            {"action": "workflow.instance.reactivate",
             "required_roles": ["super_admin"],
             "description": "Reactivate a suspended instance."},
            {"action": "workflow.task.read",
             "description": "Read a workflow task."},
            {"action": "workflow.task.list",
             "description": "List workflow tasks scoped to the caller."},
            {"action": "workflow.task.claim",
             "description": "Claim an OPEN workflow task as the current principal."},
            {"action": "workflow.task.complete",
             "description": "Complete a CLAIMED workflow task (claimer only)."},
            {"action": "workflow.task.cancel",
             "required_roles": ["super_admin"],
             "description": "Administratively cancel a non-terminal task."},
            {"action": "workflow.timer.read",
             "description": "Read a workflow timer."},
            {"action": "workflow.timer.list",
             "description": "List workflow timers (admin / ops)."},
            {"action": "workflow.timer.fire",
             "required_roles": ["super_admin"],
             "description": "Manually fire a scheduled timer (operator break-glass)."},
            {"action": "workflow.timer.cancel",
             "required_roles": ["super_admin"],
             "description": "Cancel a scheduled timer."},
            {"action": "workflow.admin.replay",
             "required_roles": ["super_admin"],
             "description": (
                 "Replay a workflow instance from the outbox event stream. "
                 "Result MUST be byte-identical to the committed state "
                 "(ADR-0019 §C-19.3 constitutional replay gate)."
             )},
            {"action": "workflow.admin.fire_timer",
             "required_roles": ["super_admin"],
             "description": (
                 "Admin endpoint to fire a timer manually for ops / break-glass."
             )},
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
            "registry.land_vault": {
                "public": [
                    "registry_id", "parcel_number", "country_code",
                    "state", "lga", "ward", "community", "village",
                    "property_type", "land_use", "status",
                    "verification_status", "geometry", "boundary_area",
                    "boundary_source", "certificate_status",
                    "spatial_validation_status",
                ],
                "owner": [
                    "registry_id", "parcel_number", "title", "status",
                    "version", "country_code", "state", "lga", "ward",
                    "ward_code", "community", "village", "address",
                    "property_type", "land_use", "size_sqm", "size_hectares",
                    "ownership_type", "owner_name", "owner_email",
                    "owner_phone", "representative_name",
                    "representative_authority", "family_head",
                    "geometry", "boundary_area", "boundary_perimeter",
                    "boundary_source", "spatial_validation_status",
                    "latitude", "longitude", "verbal_consent",
                    "community_confirmed", "survey_plan_url",
                    "surveyor_name", "survey_date", "survey_status",
                    "field_agent_email", "evidence_seal_id",
                    "evidence_seal_timestamp", "evidence_count_at_seal",
                    "certificate_url", "certificate_version",
                    "certificate_status", "amount_paid", "total_fee",
                    "outstanding_balance", "payment_status",
                    "verification_status", "risk_level",
                    "created_at", "created_by", "updated_at",
                    "legacy_aliases", "ownership_history",
                ],
                "privileged": [
                    "registry_id", "parcel_number", "title", "status",
                    "version", "country_code", "state", "lga", "ward",
                    "ward_code", "community", "village", "address",
                    "property_type", "land_use", "size_sqm", "size_hectares",
                    "ownership_type", "owner_name", "owner_email",
                    "owner_phone", "owner_nin",
                    "representative_name", "representative_authority",
                    "family_head", "geometry", "boundary_area",
                    "boundary_perimeter", "boundary_source",
                    "spatial_validation_status", "latitude", "longitude",
                    "verbal_consent", "community_confirmed",
                    "survey_plan_url", "surveyor_id", "surveyor_name",
                    "surveyor_licence", "survey_date", "survey_status",
                    "field_agent_email", "evidence_seal_id",
                    "evidence_seal_hash", "evidence_seal_timestamp",
                    "evidence_count_at_seal", "certificate_url",
                    "certificate_version", "certificate_status",
                    "amount_paid", "total_fee", "outstanding_balance",
                    "payment_status", "verification_status",
                    "risk_level", "risk_score", "created_at",
                    "created_by", "updated_at", "legacy_aliases",
                    "ownership_history", "tenant_id", "origin",
                    "schema_version", "deleted_at", "archived",
                    "evidence_sealed",
                ],
                "redacted_for_public": [
                    "owner_name", "owner_email", "owner_phone",
                    "owner_nin", "address", "tenant_id",
                    "evidence_seal_hash", "ownership_history",
                ],
                "pii_fields": ["owner_name", "owner_email",
                                "owner_phone", "owner_nin", "address"],
            },
            "evidence.item": {
                "public": [
                    "evidence_id", "registry_id", "kind", "status",
                    "hash_algorithm", "hash_verified", "seal_id",
                    "created_at",
                ],
                "owner": [
                    "evidence_id", "registry_id", "kind", "status", "version",
                    "media_type", "size_bytes", "storage_provider",
                    "server_hash", "hash_algorithm", "hash_verified",
                    "client_hash_claim", "seal_id", "sealed_at",
                    "retention_until", "replaced_by", "replaced_at",
                    "created_at", "created_by", "updated_at",
                ],
                "privileged": [
                    "evidence_id", "registry_id", "kind", "status", "version",
                    "media_type", "size_bytes", "storage_provider",
                    "server_hash", "server_hash_streamed",
                    "hash_algorithm", "hash_verified",
                    "client_hash_claim", "seal_id", "sealed_at",
                    "retention_until", "replaced_by", "replaced_at",
                    "tenant_id", "country_code", "storage_locator",
                    "upload_id", "schema_version", "origin",
                    "created_at", "created_by", "updated_at", "updated_by",
                ],
                "redacted_for_public": [
                    "tenant_id", "storage_locator", "upload_id",
                    "server_hash", "server_hash_streamed",
                    "client_hash_claim", "media_type", "size_bytes",
                ],
                "pii_fields": [],
            },
            "evidence.seal": {
                "public": [
                    "seal_id", "registry_id", "status",
                    "merkle_root", "manifest_hash", "created_at",
                ],
                "owner": [
                    "seal_id", "registry_id", "status", "version",
                    "evidence_ids", "merkle_root", "manifest_hash",
                    "created_at", "created_by",
                    "worm_applied_at", "retention_until", "anchor_batch_id",
                ],
                "privileged": [
                    "seal_id", "registry_id", "status", "version",
                    "evidence_ids", "merkle_root", "manifest_hash",
                    "manifest", "leaf_hashes",
                    "tenant_id", "country_code", "schema_version",
                    "created_at", "created_by",
                    "worm_applied_at", "retention_until",
                    "anchor_batch_id", "archived_at",
                ],
                "redacted_for_public": [
                    "tenant_id", "evidence_ids", "manifest", "leaf_hashes",
                ],
                "pii_fields": [],
            },
            # Phase 3.6
            "evidence.lock": {
                "public": ["lock_id", "evidence_id", "seal_id",
                            "mode", "applied_at"],
                "owner": ["lock_id", "evidence_id", "seal_id",
                           "storage_provider", "mode", "retention_until",
                           "applied_at", "applied_by", "extensions",
                           "last_status_check"],
                "privileged": ["lock_id", "evidence_id", "seal_id",
                                "tenant_id", "country_code",
                                "storage_provider", "storage_locator",
                                "mode", "retention_until", "extensions",
                                "applied_at", "applied_by",
                                "last_status_check", "schema_version",
                                "version"],
                "redacted_for_public": ["tenant_id", "storage_locator"],
                "pii_fields": [],
            },
            "evidence.integrity_check": {
                "public": ["check_id", "evidence_id", "outcome",
                            "triggered_by", "started_at"],
                "owner": ["check_id", "evidence_id", "triggered_by",
                           "triggered_by_principal", "expected_hash",
                           "observed_hash", "outcome", "started_at",
                           "completed_at", "error_summary", "seq"],
                "privileged": ["check_id", "evidence_id", "tenant_id",
                                "country_code", "triggered_by",
                                "triggered_by_principal",
                                "expected_hash", "observed_hash",
                                "lock_status_observed", "outcome",
                                "started_at", "completed_at",
                                "error_summary", "seq", "prev_hash",
                                "entry_hash", "schema_version", "version"],
                "redacted_for_public": ["tenant_id", "observed_hash",
                                          "lock_status_observed",
                                          "prev_hash", "entry_hash"],
                "pii_fields": [],
            },
            "evidence.anchor_batch": {
                "public": ["batch_id", "provider_id", "state",
                            "merkle_root", "created_at",
                            "confirmed_at"],
                "owner": ["batch_id", "provider_id", "state",
                           "merkle_root", "seal_ids",
                           "attempts", "last_attempt_at", "next_attempt_at",
                           "provider_request_id", "inclusion_proofs",
                           "dlq_reason", "replayed_from",
                           "created_at", "confirmed_at", "version"],
                "privileged": ["batch_id", "provider_id", "state",
                                "merkle_root", "seal_ids", "seal_leaves",
                                "attempts", "last_attempt_at",
                                "next_attempt_at", "provider_request_id",
                                "provider_response", "inclusion_proofs",
                                "dlq_reason", "replayed_from",
                                "tenant_id", "country_code", "schema_version",
                                "created_at", "confirmed_at", "version"],
                "redacted_for_public": ["tenant_id", "seal_leaves",
                                          "provider_response", "seal_ids"],
                "pii_fields": [],
            },
            # Phase 4 — Workflow bounded context
            "workflow.instance": {
                "public": ["instance_id", "definition_name",
                            "definition_version", "business_state",
                            "lifecycle", "created_at"],
                "owner": ["instance_id", "definition_name",
                           "definition_version", "business_state",
                           "lifecycle", "initiator_id",
                           "correlation_id", "payload",
                           "last_command", "last_actor",
                           "last_transitioned_at", "terminated_at",
                           "created_at", "version"],
                "privileged": ["instance_id", "definition_name",
                                "definition_version", "business_state",
                                "lifecycle", "initiator_id",
                                "correlation_id", "payload",
                                "last_command", "last_actor",
                                "last_transitioned_at", "terminated_at",
                                "suspended_reason",
                                "tenant_id", "country_code",
                                "schema_version", "created_at", "version"],
                "redacted_for_public": ["tenant_id", "payload",
                                          "initiator_id", "correlation_id"],
                "pii_fields": [],
            },
            "workflow.task": {
                "public": ["task_id", "instance_id", "title",
                            "state", "assigned_to_role",
                            "created_at"],
                "owner": ["task_id", "instance_id", "definition_name",
                           "title", "state",
                           "assigned_to_role", "assigned_to_principal",
                           "claimed_by", "claimed_at",
                           "completed_by", "completed_at",
                           "completion_payload", "due_at",
                           "cancelled_reason",
                           "created_at", "version"],
                "privileged": ["task_id", "instance_id", "definition_name",
                                "title", "state",
                                "assigned_to_role", "assigned_to_principal",
                                "claimed_by", "claimed_at",
                                "completed_by", "completed_at",
                                "completion_payload", "due_at",
                                "cancelled_reason",
                                "tenant_id", "country_code",
                                "schema_version", "created_at", "version"],
                "redacted_for_public": ["tenant_id", "claimed_by",
                                          "completed_by", "completion_payload"],
                "pii_fields": [],
            },
            "workflow.timer": {
                "public": ["timer_id", "instance_id", "fire_at",
                            "state", "command_on_fire", "created_at"],
                "owner": ["timer_id", "instance_id", "definition_name",
                           "fire_at", "state",
                           "command_on_fire", "payload_on_fire",
                           "fired_at", "cancelled_at", "cancelled_reason",
                           "created_at", "version"],
                "privileged": ["timer_id", "instance_id", "definition_name",
                                "fire_at", "state",
                                "command_on_fire", "payload_on_fire",
                                "fired_at", "cancelled_at",
                                "cancelled_reason",
                                "tenant_id", "country_code",
                                "schema_version", "created_at", "version"],
                "redacted_for_public": ["tenant_id", "payload_on_fire"],
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

    # Phase 4 — Workflow definitions are frozen content. They are not
    # GENERATED here (they live as authored JSON on disk under
    # contracts/v1/workflow_definitions/*.json), but they ARE part of
    # the drift-detected freeze: the canonical bytes are normalized
    # through ``_dumps`` so the freeze gate catches any silent edit.
    wf_def_dir = V1_DIR / "workflow_definitions"
    if wf_def_dir.exists():
        for path in sorted(wf_def_dir.glob("*.json")):
            doc = json.loads(path.read_text())
            relpath = f"v1/workflow_definitions/{path.name}"
            out.append(Artifact(relpath, _dumps(doc)))

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
        "max_supported_contract": "2.x.x",
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
            "ADR-0002 — Canonical LandVault Registry",
            "ADR-0003 — Evidence bounded context",
            "ADR-0004 — Server-side hashing discipline",
            "ADR-0006 — Legal hold + remediation supersession",
            "ADR-0007 — Canonical Evidence Aggregate + Sealing",
            "ADR-0008 — Evidence Anchoring & Integrity Saga",
            "ADR-0009 — Timeline, Custody Chain, Legal Hold, Supersession (Phase 3.7)",
            "ADR-0023 — Workflow Engine Foundation (Phase 4 Slice 4.0)",
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


def _normalize_for_compare(relpath: str, content: str) -> str:
    """Strip fields that legitimately rotate between commits.

    The release manifest carries `git_commit` and `build_timestamp` —
    both are metadata, not contract. We want the drift gate to catch
    contract changes (paths, schemas, events, security), NOT commit
    rotation noise. Everything else is byte-exact.
    """
    if relpath != "release-manifest.json":
        return content
    try:
        doc = json.loads(content)
    except Exception:
        return content
    doc["git_commit"] = "<volatile>"
    doc["build_timestamp"] = "<volatile>"
    return _dumps(doc)


def diff_against_disk() -> tuple[list[Artifact], list[tuple[Artifact, str]]]:
    """Return (artifacts, mismatches). `mismatches` is a list of (artifact, on_disk_content)."""
    artifacts = build_full_package()
    mismatches: list[tuple[Artifact, str]] = []
    for a in artifacts:
        if not a.absolute.exists():
            mismatches.append((a, "<MISSING>"))
            continue
        on_disk = a.absolute.read_text()
        if (_normalize_for_compare(a.relpath, on_disk)
                != _normalize_for_compare(a.relpath, a.content)):
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
