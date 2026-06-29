# 11 · Merkle Anchor Verification

> Cross-links: [03 ADR Compliance §ADR-0005 / §ADR-0008](03-adr-compliance-matrix.md)

## 1. What gets anchored, where, and how

| Layer | Adapter | Determinism |
| --- | --- | --- |
| Seal merkle root | `domain/seal.py::compute_merkle_root` (over `(evidence_id, composite_sha256)` pairs, sorted, SHA-256 binary tree) | Yes |
| Anchor batch merkle root | `domain/anchor_batch.py::compute_root` (over seal merkle roots) | Yes |
| Internal CT-log | `adapters/ctlog_internal.py` — append-only signed log | Yes; signed by platform KMS |
| Public TSA | `adapters/ots_v1.py` — OpenTimestamps | External; verifiable any time |

## 2. Anchoring saga

```
AnchorSaga.tick():
  1. SELECT seals WHERE status=WORM_APPLIED AND NOT yet anchored.
  2. Compose AnchorBatch (merkle root over seal roots).
  3. POST batch root to ots_v1.submit() → receives raw proof bytes.
  4. ctlog_internal.append(batch_root) → checkpoint published.
  5. Publish evidence.anchor.confirmed.v1 → TimelineProjector.
  6. Mark batch CONFIRMED.
```

Every step is idempotent — re-running the saga re-uses the same
batch_id and skips already-finished steps. Failure at any step emits
`evidence.anchor.failed.v1` which feeds the RemediationSaga.

## 3. Tests

| Test | Verifies | Status |
| --- | --- | --- |
| `test_phase36_aggregates::test_seal_root_deterministic` | Permuting evidence id order yields same root. | ✅ |
| `test_phase36_aggregates::test_anchor_merkle_root_deterministic` | Anchor root reproducible. | ✅ |
| `test_phase36_aggregates::test_anchor_saga_resume_after_crash` | Saga resumes idempotently. | ✅ |
| `test_phase36_e2e::test_ots_and_ctlog_both_emit_proof` | Two adapters both produce a proof artifact. | ✅ |
| `test_phase36_e2e::test_ctlog_append_only` | CT-log rejects sub-tree-size append. | ✅ |
| `test_phase36_aggregates::test_anchor_replay_keeps_order` | Re-running over same input yields the same checkpoint. | ✅ |

## 4. Operational verification

The Phase 3.10 perf bench (`audit/perf/results.json`) included an
end-to-end anchor for one seal (composing 5 evidence items). The
batch transitioned to `CONFIRMED` within the seed phase before the
bench started measuring read latency, so the live anchoring path is
exercised on every bench run.

## 5. External verification path

Any third party who possesses:

- the original bytes,
- the seal merkle root,
- the OTS proof artifact,

can verify the timestamp independently without contacting LandVault.
The internal CT-log is **supplementary** — it lets the platform prove
inclusion order, but the OTS proof is the legally binding artifact.

## 6. Conclusion

Anchoring is deterministic, dual-rooted (OTS + internal CT-log),
idempotent, and tested. **Merkle anchor verification: PASS.**
