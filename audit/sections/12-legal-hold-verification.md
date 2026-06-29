# 12 · Legal Hold Verification

> Cross-links: [03 ADR Compliance §ADR-0006](03-adr-compliance-matrix.md)

## 1. Lifecycle

```
[no hold] ──apply──▶ active ──release──▶ released   (terminal)
                       ▲                  │
                       └──── cannot ──────┘
```

A released hold cannot be re-activated; a second hold is a brand-new
aggregate. The release itself is immutable — `release_reason`,
`released_by`, `released_at` are recorded once.

## 2. Domain rules (`contexts/evidence/domain/timeline.py::LegalHold`)

| Rule | Test |
| --- | --- |
| `case_reference` must be non-empty (≥ 1 char). | `test_legal_hold_requires_fields` |
| `reason` must be ≥ 5 chars. | `test_legal_hold_requires_fields` |
| `release_reason` must be ≥ 3 chars when releasing. | `test_legal_hold_release_requires_reason` |
| Apply emits `evidence.legal_hold.applied.v1`. | `test_legal_hold_event_emitted` |
| Release emits `evidence.legal_hold.released.v1`. | `test_legal_hold_release_event_emitted` |
| Active hold blocks `SupersessionService.record_supersession`. | `test_supersession_blocked_during_hold` |
| Active hold blocks any deletion path. | `test_no_delete_path_exists_for_active_hold` |

## 3. Endpoints

| Endpoint | Authorization | Test |
| --- | --- | --- |
| `POST /api/v1/evidence/items/{id}/legal-holds` | `super_admin` or `compliance_officer` | `test_apply_hold_authorization` |
| `GET  /api/v1/evidence/items/{id}/legal-holds` | authenticated | `test_list_holds` |
| `GET  /api/v1/evidence/legal-holds/{id}` | authenticated | `test_get_hold_by_id` |
| `POST /api/v1/evidence/legal-holds/{id}/release` | `super_admin` or `compliance_officer` | `test_release_authorization` |

## 4. UX surface (Phase 3.9)

The "Legal Hold" tab on the Evidence Detail page lets privileged
operators apply / release through the SDK. Non-privileged users see
read-only history. Releases prompt for reason text.

## 5. Constitutional invariant — "no hidden state"

A release is recorded but the hold row is **never** deleted. Status
flips from `active` to `released`. Querying the hold's history
returns the full timeline (issued_at, issued_by, released_at,
released_by, release_reason). The Custody projection records every
hold transition as a chain row, so an external auditor can replay
the legal-hold history from events alone.

## 6. Tests summary

| Suite | Count of legal-hold tests | Status |
| --- | --- | --- |
| `test_phase37_timeline.py` | 6 | ✅ |

## 7. Conclusion

Legal Hold is mechanically tamper-evident, dual-attribute (case + reason),
gated by role, and feeds the immutable timeline. **Legal Hold
verification: PASS.**
