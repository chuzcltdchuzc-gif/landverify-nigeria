/**
 * Aquasavannah LandVault SDK — Evidence + Projections + Auth types.
 *
 * Hand-derived from /app/contracts/v1/openapi.json (frozen at v1.5.0).
 * Any drift here MUST be caught by the contract test
 * `tests/test_sdk_consistency.py`.
 *
 * All field names follow the OpenAPI camelCase/snake_case as emitted by
 * FastAPI's Pydantic models (snake_case). The SDK is wire-level only.
 */

// ---- Common --------------------------------------------------------------

export interface Problem {
  type: string;
  title: string;
  status: number;
  code?: string;
  detail?: string;
  instance?: string;
  correlation_id?: string;
}

// ---- Identity / Auth -----------------------------------------------------

export interface RegisterRequest {
  email: string;
  password: string;
  full_name?: string;
  country?: string;
}
export interface LoginLocalRequest {
  email: string;
  password: string;
}
export interface LoginGoogleRequest {
  session_id: string;
}
export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: {
    user_id: string;
    email: string;
    full_name?: string | null;
    roles: string[];
    country?: string | null;
    tenant_id?: string | null;
    organization_id?: string | null;
    account_status?: string | null;
  };
}

// ---- Evidence ------------------------------------------------------------

export interface EvidenceItem {
  evidence_id: string;
  registry_id: string;
  tenant_id: string;
  country_code: string;
  kind: string;
  media_type?: string | null;
  status: string;
  max_size: number;
  total_size?: number | null;
  storage_uri?: string | null;
  storage_provider?: string | null;
  composite_sha256?: string | null;
  parts_meta?: Array<{ part_no: number; size_bytes: number; sha256: string }>;
  verification?: {
    verified: boolean;
    verified_at?: string | null;
    mismatch_reason?: string | null;
  } | null;
  replaced_by?: string | null;
  replaced_at?: string | null;
  created_at: string;
  updated_at: string;
  version: number;
}

export interface EvidenceListResponse {
  items: EvidenceItem[];
  total: number;
  page?: number;
  page_size?: number;
}

export interface InitiateEvidenceUploadRequest {
  registry_id: string;
  kind: string;
  media_type: string;
  max_size: number;
}
export interface InitiateEvidenceUploadResponse {
  evidence_id: string;
  upload_url_template: string;
  max_parts: number;
  max_part_size: number;
  expires_at: string;
}
export interface UploadPartReceipt {
  part_no: number;
  size_bytes: number;
  streamed_sha256: string;
}
export interface CompleteEvidenceUploadRequest {
  parts: UploadPartReceipt[];
}

export interface SealResponse {
  seal_id: string;
  registry_id: string;
  evidence_ids: string[];
  merkle_root: string;
  status: string;
  worm_applied_at?: string | null;
  created_at: string;
}
export interface CreateSealRequest {
  registry_id: string;
  evidence_ids: string[];
}
export interface ApplySealWormRequest {
  retention_until?: string | null;
}

export interface SignedUrlRequest {
  action: 'read' | 'download';
  ttl_seconds: number;
}
export interface SignedUrlResponse {
  url: string;
  expires_at: string;
}

// ---- Timeline / Custody / Legal Hold / Supersession ----------------------

export interface TimelineEntry {
  timeline_id: string;
  evidence_id: string;
  tenant_id: string;
  country_code: string;
  kind: string;
  actor: string;
  occurred_at: string;
  seq: number;
  prev_hash: string | null;
  entry_hash: string;
  summary: string;
  payload: Record<string, unknown>;
  schema_version: number;
}
export interface TimelineChainResponse {
  evidence_id: string;
  chain: TimelineEntry[];
}

export interface CustodyEntry {
  custody_id: string;
  evidence_id: string;
  actor: string;
  role: string;
  action: string;
  occurred_at: string;
  justification: string;
  signature_kid: string | null;
  signature: string | null;
  previous_custody_id: string | null;
  seq: number;
  prev_hash: string | null;
  entry_hash: string;
}
export interface CustodyChainResponse {
  evidence_id: string;
  chain: CustodyEntry[];
}
export interface RecordCustodyRequest {
  role: string;
  action: string;
  justification: string;
  signature_kid?: string;
  signature?: string;
}

export interface LegalHold {
  hold_id: string;
  evidence_id: string;
  case_reference: string;
  issued_by: string;
  reason: string;
  status: 'active' | 'released';
  issued_at: string;
  released_at?: string | null;
  released_by?: string | null;
  release_reason?: string | null;
}
export interface LegalHoldListResponse {
  evidence_id: string;
  holds: LegalHold[];
}
export interface ApplyLegalHoldRequest {
  case_reference: string;
  reason: string;
}
export interface ReleaseLegalHoldRequest {
  release_reason: string;
}

export interface SupersessionLink {
  evidence_id: string;
  previous_version_id: string | null;
  superseded_by: string | null;
  superseded_at: string | null;
  superseded_reason: string | null;
}
export interface SupersessionChainResponse {
  evidence_id: string;
  chain: SupersessionLink[];
}

// ---- Anchoring / Integrity / Locks --------------------------------------

export interface AnchorBatch {
  batch_id: string;
  status: string;
  seal_ids: string[];
  merkle_root: string;
  ctlog_checkpoint_id?: string | null;
  ots_proof?: string | null;
  submitted_at?: string | null;
  confirmed_at?: string | null;
  created_at: string;
}
export interface IntegrityCheck {
  check_id: string;
  evidence_id: string;
  status: 'STARTED' | 'PASSED' | 'FAILED' | 'ERRORED';
  attempted_at: string;
  completed_at?: string | null;
  expected_sha256?: string | null;
  actual_sha256?: string | null;
  mismatch_reason?: string | null;
}
export interface IntegrityChainResponse {
  evidence_id: string;
  checks: IntegrityCheck[];
}
export interface EvidenceLock {
  lock_id: string;
  evidence_id: string;
  retention_until: string;
  reason: string;
  applied_at: string;
  applied_by: string;
}
export interface EvidenceLockListResponse {
  evidence_id: string;
  locks: EvidenceLock[];
}

// ---- Projection admin (Phase 3.8) ---------------------------------------

export interface ProjectionStatus {
  name: string;
  version: number;
  cursor_event_id: string | null;
  last_delivered_at: string | null;
  last_event_type: string | null;
  delivered_count: number;
  lag_events: number;
  rebuilding: boolean;
  last_snapshot_at: string | null;
}
export interface ProjectionListResponse {
  projections: ProjectionStatus[];
}
