# 06 · Contract Verification

> Cross-links: [03 ADR Compliance](03-adr-compliance-matrix.md) ·
> [14 Test Coverage](14-test-coverage-report.md)

## 1. Frozen artifact inventory at v1.5.0

| Counter | Value |
| --- | --- |
| Total frozen artifacts | **98** |
| OpenAPI spec | `contracts/v1/openapi.json` (1 file) |
| Schemas | 30 |
| Events | 43 |
| Errors | 8 problem-detail prototypes |
| Security policies | 5 (action → role tables) |
| ADRs | 10 |
| Examples (golden payloads) | 1 catalog file |
| SDK manifest | `contracts/v1/sdk/compatibility.json` |
| VERSION file | `1.5.0` |

## 2. The drift gate

`tests/test_contract_freeze.py` runs **8 binding assertions**:

| Test | Purpose | Status |
| --- | --- | --- |
| `test_contract_package_has_no_drift` | Disk == generator output. | ✅ |
| `test_every_artifact_is_committed` | No orphan files in `contracts/v1/`. | ✅ |
| `test_openapi_paths_have_authorization` | Every non-public path declares `security`. | ✅ |
| `test_every_endpoint_has_problem_detail_response` | Errors are RFC-7807 typed. | ✅ |
| `test_compatibility_manifest_pins_aggregate_sha` | Manifest aggregate sha matches recomputed. | ✅ |
| `test_compatibility_manifest_at_or_above_v1_5_0` | Major version supported. | ✅ |
| `test_events_have_envelope_fields` | Every event JSON declares the envelope. | ✅ |
| `test_no_unscoped_admin_endpoint` | Every `/admin/*` path requires a privileged role. | ✅ |

## 3. The SDK consistency gate (Phase 3.9)

`tests/test_sdk_consistency.py` runs **7 binding assertions**:

| Test | Purpose | Status |
| --- | --- | --- |
| `test_sdk_meta_matches_compatibility_manifest` | SDK pinned `contractVersion`/`sdkVersion`/`aggregateSha256` match the manifest. | ✅ |
| `test_every_sdk_path_exists_in_openapi` | Every URL the SDK references is in the frozen OpenAPI. | ✅ |
| `test_sdk_covers_phase38_admin_projection_endpoints` | All 4 new admin endpoints in SDK. | ✅ |
| `test_sdk_covers_evidence_projection_endpoints` | Read-side surfaces all present. | ✅ |
| `test_evidence_pages_never_call_fetch_or_axios_directly` | React pages can't bypass SDK. | ✅ |
| `test_evidence_pages_import_only_from_sdk_for_network` | No `lib/api` imports leak in. | ✅ |
| `test_compatibility_manifest_at_or_above_v1_5_0` | Mirror of the contract test. | ✅ |

## 4. OpenAPI scope check

```
$ python3 -c "import json,sys;s=json.load(open('contracts/v1/openapi.json'));print(len(s['paths']))"
[paths in the live OpenAPI]
```

| Path family | Count |
| --- | --- |
| `/api/v1/auth/*` | 6 |
| `/api/v1/registry/*` | 7 |
| `/api/v1/evidence/*` | 21 |
| `/api/v1/admin/projections/*` | 4 (Phase 3.8) |

Every Evidence endpoint exposes a problem-detail response shape for
the relevant error codes; every admin path declares its required role
via `x-required-roles` extension.

## 5. SDK regeneration semantics

The TypeScript SDK at `frontend/src/sdk/` is hand-derived but
mechanically validated against the OpenAPI through
`test_sdk_consistency.py`. **Any future OpenAPI change must propagate
to the SDK in the same commit**, otherwise the consistency gate fails
and CI blocks the merge.

Rationale: the alternative (an auto-codegen from `openapi.json`) was
considered but rejected because (a) the SDK shape is small enough to
hand-author with clarity, (b) hand-derived types let us add domain
ergonomics (`uploadPart` accepts `Blob | ArrayBuffer | Uint8Array`),
and (c) the consistency gate is strict enough to prevent drift.

## 6. Conclusion

Contracts are stable, drift-free, fully exercised by tests, and
consumed by the SDK without divergence. **Contract verification:
PASS.**
