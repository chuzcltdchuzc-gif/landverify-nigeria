# 09 · Security Review

> Cross-links: [03 ADR Compliance](03-adr-compliance-matrix.md) ·
> [10 WORM Verification](10-worm-verification.md) ·
> [17 Production Readiness](17-production-readiness.md)

## 1. Authentication

| Surface | Mechanism | Test |
| --- | --- | --- |
| Bearer token | Asymmetric JWT, JWKS-discoverable via `/api/.well-known/jwks.json`. | `tests/test_phase1_identity.py::test_jwt_signed_and_verified` |
| Refresh | http-only secure same-site cookie, server-rotated. | `…::test_refresh_rotates` |
| Google OAuth | Emergent-managed; `/api/v1/auth/login/google` exchanges `session_id` for a platform JWT. | `…::test_google_login_session_exchange` |
| Local | bcrypt with platform salt, ≥8 chars + ≥1 digit + ≥1 letter. | `…::test_password_policy` |

## 2. Authorization (centralised PEP)

- Every router endpoint goes through `await enforce(action,
  resource=…)` from `kernel/authorization/pep.py`.
- Policies are registered in `kernel/authorization/policies.py` with
  priorities; first matching `permit`/`deny` wins.
- The Evidence and Projection admin policies are registered in
  context-local modules (`contexts/evidence/authorization.py`,
  `kernel/projections/authorization.py`).

| Action | Roles required | Source |
| --- | --- | --- |
| `evidence.read` | authenticated user OR signed-url consumer | `contexts/evidence/authorization.py` |
| `evidence.upload` | `field_agent`, `validator`, `super_admin` | same |
| `evidence.seal` | `super_admin`, `compliance_officer` | same |
| `evidence.legal_hold.apply` | `super_admin`, `compliance_officer` | same |
| `evidence.legal_hold.release` | `super_admin`, `compliance_officer` | same |
| `kernel.projections.admin` | `super_admin` only | `kernel/projections/authorization.py` |

`test_no_unscoped_admin_endpoint` asserts every `/admin/*` path
declares a privileged required role.

## 3. Input validation

- All request DTOs are Pydantic models with `extra="forbid"`.
- Request bodies that exceed `max_size` are rejected at the FastAPI
  layer before any byte reaches the storage adapter.
- Path params are typed (`str`, `int`); invalid ids surface as 422.

## 4. Tenant isolation

Every aggregate carries `tenant_id` and `country_code`. Every
repository query (`MongoEvidenceRepository`, `MongoTimelineRepository`,
…) scopes by tenant. Cross-tenant access is impossible by
construction — tested in
`tests/test_evidence_aggregate_invariants.py::test_tenant_scoped_query`.

## 5. Audit log

`kernel/audit/__init__.py::record_audit()` writes to `audit_log` on
every state-mutating action. Fields: `actor`, `action`, `aggregate`,
`correlation_id`, `before/after fingerprint`, `timestamp`. The
collection is **append-only** — no `update_*` or `delete_*` calls
exist anywhere in the kernel.

## 6. Crypto inventory

| Use | Algorithm | Key custody |
| --- | --- | --- |
| Composite SHA | SHA-256 | none (deterministic hash) |
| Chain entry hash | SHA-256 over canonical JSON | none |
| Merkle root (seal + anchor) | SHA-256 | none |
| Internal CT-log signature | Ed25519 (PyNaCl) | software KMS in `kernel/security/keys.py`; rotation TBD by ops |
| JWT | RS256 / ES256 | platform JWKS |
| Refresh cookie | HMAC-SHA-256 | platform secret in env |

The signing key for the CT-log is currently held in a software KMS.
A hardware-backed KMS migration is on the deferred backlog
([§16](16-deferred-backlog.md)).

## 7. Secrets handling

- All secrets sourced from environment (`backend/.env`).
- No secret string is hardcoded in the codebase
  (`grep -r "sk_live\|api_key=\|password=" backend` returns 0 hits).
- The `Emergent LLM Key` flows through the integration playbook
  pattern and is not committed.

## 8. Transport

- Production fronts the pod with TLS at the ingress.
- Backend listens on 0.0.0.0:8001 internal-only; never exposed.
- CORS allow-list driven by env (`REACT_APP_BACKEND_URL` is the only
  cross-origin entry).

## 9. Threat model — selected

| Threat | Mitigation | Status |
| --- | --- | --- |
| **Tamper with stored bytes after WORM** | WORM Object-Lock at the storage layer + periodic integrity checks recompute hash. | ✅ §10 + §08 |
| **Tamper with timeline rows** | Chain integrity (entry_hash links rows); replay catches divergence. | ✅ §07 |
| **Stolen short-lived JWT** | TTL 15 min, refresh requires cookie + matching JTI. | ✅ Phase 1 tests |
| **Replay attack on signed-url** | TTL ≤ 600 s, single-action, audit-logged. | ✅ Phase 3.6 tests |
| **Projection privilege escalation** | super_admin policy + 401/403 tests. | ✅ §08 |
| **Cross-tenant leak** | Tenant-scoped repository queries. | ✅ §4 |
| **CSP / XSS interception of upload** | Not yet hardened — tracked as [R-2](15-outstanding-risks.md). | ⚠ |

## 10. Conclusion

Authentication, authorization, audit, input validation, tenant
scoping, and key custody all meet the constitutional bar. The single
outstanding security concern is the CSP hardening (R-2). **Security
review: PASS, conditional on R-2 being scheduled.**
