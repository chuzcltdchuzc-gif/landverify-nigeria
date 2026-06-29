# 10 · WORM Verification

> Cross-links: [03 ADR Compliance §ADR-0007](03-adr-compliance-matrix.md) ·
> [09 Security Review](09-security-review.md)

## 1. WORM model

Write-Once-Read-Many is enforced at TWO layers:

1. **Domain layer** — the `Seal` aggregate's `apply_worm()` method is
   one-shot; the FSM forbids a second call. `EvidenceItem` cannot
   transition out of `WORM_LOCKED` except into `ARCHIVED_REPLACED`
   (and only via the supersession path).
2. **Storage layer** — the `LocalFsWormStorage` and `R2Storage`
   adapters use Object-Lock semantics (R2) or filesystem chmod 0o444
   + immutable bit (local fallback) so the bytes themselves cannot
   be overwritten.

## 2. WORM application path

```
POST /api/v1/evidence/seals/{seal_id}/apply-worm
   ↓ enforce("evidence.seal", role super_admin / compliance_officer)
SealService.apply_worm(seal_id, retention_until?)
   ↓ Seal.apply_worm() → InvariantViolation if already applied
   ↓ Storage.lock_object(storage_uri, retention_until)
   ↓ Outbox.publish(evidence.seal.worm_applied.v1)
TimelineProjector → evidence_timeline row(kind="worm_applied")
```

## 3. Tests

| Test | Verifies | Status |
| --- | --- | --- |
| `test_phase36_aggregates::test_worm_applied_terminal` | Re-applying WORM raises `InvariantViolation`. | ✅ |
| `test_phase36_aggregates::test_sealed_evidence_cannot_re_upload` | After WORM, no `PUT /parts/*` accepted. | ✅ |
| `test_evidence_storage_foundation::test_worm_storage_blocks_overwrite` | The storage adapter rejects byte overwrite even with admin privileges. | ✅ |
| `test_phase36_e2e::test_worm_creates_timeline_row` | The projection records the worm_applied row. | ✅ |
| `test_phase37_timeline::test_supersession_requires_no_active_hold` | Supersession (only legal write-after-worm) is gated. | ✅ |

## 4. Production storage binding

- Local dev / tests use `LocalFsWormStorage` (writes to a temp dir,
  chmod 0o444 once committed; rejects any subsequent open in
  write mode).
- Production uses Cloudflare R2 with Object Lock enabled
  (`r2_storage.py`). The Object Lock retention is set from
  `retention_until` on the seal.

## 5. Retention horizon

`EvidenceLock` aggregates carry `retention_until > applied_at` and
can only be **extended forward** in time. Shortening a retention is
mechanically impossible — `evidence_lock.py::extend()` asserts
`new_until > current.retention_until`.

| Test | Status |
| --- | --- |
| `test_phase36_aggregates::test_lock_horizon_positive` | ✅ |
| `test_phase36_aggregates::test_lock_only_extends_forward` | ✅ |

## 6. Conclusion

Both layers of WORM enforcement are tested and live. **WORM
verification: PASS.**
