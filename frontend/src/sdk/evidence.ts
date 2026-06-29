/**
 * Aquasavannah LandVault SDK — Evidence client.
 * Wire-level mapping to /api/v1/evidence/* (Phases 3.4–3.7).
 */
import { SdkRuntime } from './runtime';
import type {
  AnchorBatch,
  ApplyLegalHoldRequest,
  ApplySealWormRequest,
  CompleteEvidenceUploadRequest,
  CreateSealRequest,
  CustodyChainResponse,
  EvidenceItem,
  EvidenceListResponse,
  EvidenceLock,
  EvidenceLockListResponse,
  InitiateEvidenceUploadRequest,
  InitiateEvidenceUploadResponse,
  IntegrityChainResponse,
  IntegrityCheck,
  LegalHold,
  LegalHoldListResponse,
  RecordCustodyRequest,
  ReleaseLegalHoldRequest,
  SealResponse,
  SignedUrlRequest,
  SignedUrlResponse,
  SupersessionChainResponse,
  TimelineChainResponse,
} from './types';

export class EvidenceClient {
  constructor(private readonly rt: SdkRuntime) {}

  // ---- items -----------------------------------------------------------
  list(params?: {
    registry_id?: string;
    status?: string;
    page?: number;
    page_size?: number;
  }): Promise<EvidenceListResponse> {
    const q = new URLSearchParams();
    if (params?.registry_id) q.set('registry_id', params.registry_id);
    if (params?.status) q.set('status', params.status);
    if (params?.page != null) q.set('page', String(params.page));
    if (params?.page_size != null)
      q.set('page_size', String(params.page_size));
    const qs = q.toString();
    const path = qs ? `/api/v1/evidence/items?${qs}` : '/api/v1/evidence/items';
    return this.rt.request('GET', path);
  }
  get(evidenceId: string): Promise<EvidenceItem> {
    return this.rt.request('GET', `/api/v1/evidence/items/${evidenceId}`);
  }
  initiateUpload(
    req: InitiateEvidenceUploadRequest
  ): Promise<InitiateEvidenceUploadResponse> {
    return this.rt.request('POST', '/api/v1/evidence/items', req);
  }
  uploadPart(
    evidenceId: string,
    partNo: number,
    bytes: ArrayBuffer | Blob | Uint8Array
  ): Promise<{ part_no: number; size_bytes: number; sha256: string }> {
    return this.rt.request(
      'PUT',
      `/api/v1/evidence/items/${evidenceId}/parts/${partNo}`,
      bytes,
      { 'Content-Type': 'application/octet-stream' },
      true
    );
  }
  completeUpload(
    evidenceId: string,
    req: CompleteEvidenceUploadRequest
  ): Promise<EvidenceItem> {
    return this.rt.request(
      'POST',
      `/api/v1/evidence/items/${evidenceId}/complete`,
      req
    );
  }
  verify(evidenceId: string): Promise<EvidenceItem> {
    return this.rt.request(
      'POST',
      `/api/v1/evidence/items/${evidenceId}/verify`
    );
  }
  signedUrl(
    evidenceId: string,
    req: SignedUrlRequest
  ): Promise<SignedUrlResponse> {
    return this.rt.request(
      'POST',
      `/api/v1/evidence/items/${evidenceId}/signed-url`,
      req
    );
  }

  // ---- seals -----------------------------------------------------------
  createSeal(req: CreateSealRequest): Promise<SealResponse> {
    return this.rt.request('POST', '/api/v1/evidence/seals', req);
  }
  getSeal(sealId: string): Promise<SealResponse> {
    return this.rt.request('GET', `/api/v1/evidence/seals/${sealId}`);
  }
  applyWorm(sealId: string, req: ApplySealWormRequest = {}): Promise<SealResponse> {
    return this.rt.request(
      'POST',
      `/api/v1/evidence/seals/${sealId}/apply-worm`,
      req
    );
  }

  // ---- read-side projections ------------------------------------------
  timeline(evidenceId: string): Promise<TimelineChainResponse> {
    return this.rt.request(
      'GET',
      `/api/v1/evidence/items/${evidenceId}/timeline`
    );
  }
  custody(evidenceId: string): Promise<CustodyChainResponse> {
    return this.rt.request(
      'GET',
      `/api/v1/evidence/items/${evidenceId}/custody`
    );
  }
  recordCustody(
    evidenceId: string,
    req: RecordCustodyRequest
  ): Promise<CustodyChainResponse['chain'][number]> {
    return this.rt.request(
      'POST',
      `/api/v1/evidence/items/${evidenceId}/custody`,
      req
    );
  }
  supersessionChain(evidenceId: string): Promise<SupersessionChainResponse> {
    return this.rt.request(
      'GET',
      `/api/v1/evidence/items/${evidenceId}/supersession-chain`
    );
  }

  // ---- legal holds ----------------------------------------------------
  listLegalHolds(evidenceId: string): Promise<LegalHoldListResponse> {
    return this.rt.request(
      'GET',
      `/api/v1/evidence/items/${evidenceId}/legal-holds`
    );
  }
  applyLegalHold(
    evidenceId: string,
    req: ApplyLegalHoldRequest
  ): Promise<LegalHold> {
    return this.rt.request(
      'POST',
      `/api/v1/evidence/items/${evidenceId}/legal-holds`,
      req
    );
  }
  getLegalHold(holdId: string): Promise<LegalHold> {
    return this.rt.request(
      'GET',
      `/api/v1/evidence/legal-holds/${holdId}`
    );
  }
  releaseLegalHold(
    holdId: string,
    req: ReleaseLegalHoldRequest
  ): Promise<LegalHold> {
    return this.rt.request(
      'POST',
      `/api/v1/evidence/legal-holds/${holdId}/release`,
      req
    );
  }

  // ---- locks ----------------------------------------------------------
  locksForEvidence(evidenceId: string): Promise<EvidenceLockListResponse> {
    return this.rt.request(
      'GET',
      `/api/v1/evidence/locks/by-evidence/${evidenceId}`
    );
  }
  getLock(lockId: string): Promise<EvidenceLock> {
    return this.rt.request('GET', `/api/v1/evidence/locks/${lockId}`);
  }

  // ---- integrity ------------------------------------------------------
  integrityForEvidence(
    evidenceId: string
  ): Promise<IntegrityChainResponse> {
    return this.rt.request(
      'GET',
      `/api/v1/evidence/integrity-checks/by-evidence/${evidenceId}`
    );
  }
  getIntegrityCheck(checkId: string): Promise<IntegrityCheck> {
    return this.rt.request(
      'GET',
      `/api/v1/evidence/integrity-checks/${checkId}`
    );
  }
  triggerIntegrityCheck(req: {
    evidence_id: string;
    reason?: string;
  }): Promise<IntegrityCheck> {
    return this.rt.request('POST', '/api/v1/evidence/integrity-checks', req);
  }

  // ---- anchoring ------------------------------------------------------
  listAnchorBatches(): Promise<{ batches: AnchorBatch[] }> {
    return this.rt.request('GET', '/api/v1/evidence/anchor-batches');
  }
  getAnchorBatch(batchId: string): Promise<AnchorBatch> {
    return this.rt.request(
      'GET',
      `/api/v1/evidence/anchor-batches/${batchId}`
    );
  }
  anchorBatchForSeal(sealId: string): Promise<AnchorBatch | null> {
    return this.rt.request(
      'GET',
      `/api/v1/evidence/anchor-batches/by-seal/${sealId}`
    );
  }
  ctlogLatestCheckpoint(): Promise<{
    checkpoint_id: string;
    tree_size: number;
    root_hash: string;
    signed_at: string;
  }> {
    return this.rt.request(
      'GET',
      '/api/v1/evidence/ctlog/checkpoints/latest'
    );
  }
}
