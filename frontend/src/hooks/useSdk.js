/**
 * useSdk — React adapter for the LandVault TypeScript SDK.
 *
 * Phase 3.9 rule: every Evidence page MUST consume the sdk through
 * this hook. No direct fetch/axios. The hook returns the singleton
 * SDK configured with the running app's REACT_APP_BACKEND_URL.
 */
import { useMemo } from 'react';
import { sdk, SDK_META } from '../sdk';

export function useSdk() {
  return useMemo(() => sdk, []);
}

export function useSdkMeta() {
  return SDK_META;
}
