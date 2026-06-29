/**
 * Aquasavannah LandVault SDK — version + drift sentinel.
 *
 * Pinned to the frozen contract package at v1.5.0 (Phase 3.8 contract
 * freeze; Phase 3.9 SDK regeneration). The Python contract drift gate
 * (`tests/test_sdk_consistency.py`) ensures these constants match
 * `/app/contracts/v1/sdk/compatibility.json` byte-for-byte.
 */
export interface SdkMeta {
  contractVersion: string;
  sdkVersion: string;
  aggregateSha256: string;
  generatedFor: string;
}

export const SDK_META: SdkMeta = {
  contractVersion: '1.5.0',
  sdkVersion: '1.5.0+sdk.1',
  aggregateSha256:
    'f5cfcbb5377714c3d00020aae369a3040728f55ea9daccd302ef83ca99121a95',
  generatedFor: 'aquasavannah-landvault',
};

/** Major version this SDK supports. Bumping the major in the contract
 *  invalidates this SDK and requires regeneration. */
export const SUPPORTED_CONTRACT_MAJOR = 1;
