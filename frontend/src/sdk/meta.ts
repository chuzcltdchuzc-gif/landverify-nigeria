/**
 * Aquasavannah LandVault SDK — version + drift sentinel.
 *
 * Pinned to the frozen contract package at v2.0.0 (Phase 4 Slice 4.0
 * workflow engine foundation; major bump per ADR-0023). The Python
 * contract drift gate (`tests/test_sdk_consistency.py`) ensures these
 * constants match `/app/contracts/v1/sdk/compatibility.json`
 * byte-for-byte.
 */
export interface SdkMeta {
  contractVersion: string;
  sdkVersion: string;
  aggregateSha256: string;
  generatedFor: string;
}

export const SDK_META: SdkMeta = {
  contractVersion: '2.0.0',
  sdkVersion: '2.0.0+sdk.1',
  aggregateSha256:
    '027d9c2bfb3616511717fffc5ce4e04b48519399782a43812db1fc5285187f7b',
  generatedFor: 'aquasavannah-landvault',
};

/** Major version this SDK supports. Bumping the major in the contract
 *  invalidates this SDK and requires regeneration. */
export const SUPPORTED_CONTRACT_MAJOR = 2;
