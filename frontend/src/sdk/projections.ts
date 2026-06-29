/**
 * Aquasavannah LandVault SDK — Projection Admin client (Phase 3.8).
 * Super_admin only — see ADR-0010.
 */
import { SdkRuntime } from './runtime';
import type {
  ProjectionListResponse,
  ProjectionStatus,
} from './types';

export class ProjectionsAdminClient {
  constructor(private readonly rt: SdkRuntime) {}

  list(): Promise<ProjectionListResponse> {
    return this.rt.request('GET', '/api/v1/admin/projections');
  }
  get(name: string): Promise<ProjectionStatus> {
    return this.rt.request('GET', `/api/v1/admin/projections/${name}`);
  }
  replay(name: string): Promise<ProjectionStatus> {
    return this.rt.request(
      'POST',
      `/api/v1/admin/projections/${name}/replay`
    );
  }
  snapshot(name: string): Promise<ProjectionStatus> {
    return this.rt.request(
      'POST',
      `/api/v1/admin/projections/${name}/snapshot`
    );
  }
}
