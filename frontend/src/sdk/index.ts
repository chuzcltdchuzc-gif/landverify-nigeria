/**
 * Aquasavannah LandVault SDK — composed entry point.
 *
 * Phase 3.9 constitutional rule: the React app MUST consume this
 * module and NOTHING ELSE from the network. No axios. No fetch. No
 * hand-rolled DTOs. The default export `sdk` is the single client.
 */
import { AuthClient } from './auth';
import { EvidenceClient } from './evidence';
import { ProjectionsAdminClient } from './projections';
import { SdkRuntime } from './runtime';
import type { RuntimeOptions } from './runtime';

export { SdkRuntime, SdkError } from './runtime';
export { SDK_META, SUPPORTED_CONTRACT_MAJOR } from './meta';
export * from './types';

export interface LandVaultSdk {
  runtime: SdkRuntime;
  auth: AuthClient;
  evidence: EvidenceClient;
  projections: ProjectionsAdminClient;
}

export function createSdk(opts: RuntimeOptions): LandVaultSdk {
  const runtime = new SdkRuntime(opts);
  return {
    runtime,
    auth: new AuthClient(runtime),
    evidence: new EvidenceClient(runtime),
    projections: new ProjectionsAdminClient(runtime),
  };
}

// Default shared instance, configured for the running app. Consumers
// should prefer `useSdk()` from the React layer, but unit tests can
// instantiate their own runtime via `createSdk`.
const baseUrl: string =
  (typeof process !== 'undefined' &&
    (process as { env?: Record<string, string | undefined> }).env
      ?.REACT_APP_BACKEND_URL) ||
  '';

export const sdk: LandVaultSdk = createSdk({
  baseUrl,
  tokenProvider: () => {
    if (typeof window === 'undefined') return null;
    return window.localStorage.getItem('lv_session_token');
  },
  withCredentials: true,
});
