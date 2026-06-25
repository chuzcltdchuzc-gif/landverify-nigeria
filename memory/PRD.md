# Aquasavannah LandVault — Product Requirements Document (Living)

_Last updated: 2026-06-24_

## 1. Original problem statement
Build Aquasavannah LandVault — a subscription-based, production-ready web application that
serves as the **trusted evidence layer for land transactions and land history** in Nigeria.
It preserves, verifies, and makes land evidence transparent. It does NOT determine ownership.

Spec covered 13 production layers, 6 subscription tiers, role-based dashboards, credit wallet,
audit trail, trust validation, and admin command centre.

## 2. Architecture decisions (made together with user)
- **Auth:** Emergent-managed Google Auth (with a dev-login bypass for automated testing)
- **Payments:** Stripe (sandbox key already in env) **+** Paystack (sandbox stub)
- **Database:** MongoDB (in place of the spec's PostgreSQL). Equivalent RLS achieved by
  consistently filtering on `tenant_id` and using atomic `$inc` for credit ops.
- **AI/OCR:** Mocked for v1 — jobs run, return canned results
- **Stack:** React + FastAPI + MongoDB; Tailwind + shadcn/ui + lucide-react + sonner toast

## 3. User personas
1. **Citizen / Family** — primary uploader of family land evidence
2. **Community Validator** — village chairmen, family heads, traditional rulers
3. **Surveyor Partner** — registered surveyors uploading plans
4. **Legal / Due Diligence** *(routes ready, dashboard deferred)*
5. **Institutional (Bank/Corp)** *(routes ready, dashboard deferred)*
6. **Government Observer** *(routes ready, dashboard deferred)*
7. **Platform Admin** — operates the command centre

## 4. Implemented in v1 (2026-06-24)
### Backend (now modular under `/app/backend/`)
- **Phase 9 refactor complete** — monolithic 2 569-line `server.py` reduced to an 8-line shim. Full enterprise structure: `core/`, `schemas/`, `services/`, `routers/`, `webhooks/`. Zero API breaking changes. Backend version bumped 1.0.0 → 1.1.0. See `MIGRATION_REPORT.md`.
- Emergent Google Auth + `/api/auth/dev-login` test bypass
- `/api/auth/me`, `/api/auth/logout` with httpOnly session cookie + Bearer fallback
- Public: `/api/public/stats`, `/api/public/verify`, `/api/public/plans`, `/api/public/transparency`
- Parcels CRUD, evidence vault (SHA-256), community attestations (RBAC ≥ COMMUNITY_VALIDATOR)
- Surveyor assignments + survey plan upload (RBAC ≥ SURVEYOR)
- Credit wallet with atomic `$inc` deductions + idempotency keys
- **Payments (iteration 2 — env-driven):**
  - `/api/payments/config` returns `{stripe: {enabled, mode, publishable_key}, paystack: {enabled, mode, public_key}}` — secrets never leak
  - Stripe checkout via `emergentintegrations` (USD-equivalent NGN); status endpoint verifies local ledger FIRST (404 on unknown), enforces user isolation (admin override allowed)
  - **Real Paystack** integration: `POST /transaction/initialize` and `GET /transaction/verify/{ref}` via httpx with `Authorization: Bearer ${PAYSTACK_SECRET_KEY}`
  - `/api/webhook/stripe` — signature verified via `stripe.Webhook.construct_event` against `STRIPE_WEBHOOK_SECRET`
  - `/api/webhook/paystack` — HMAC-SHA512 verified against `PAYSTACK_WEBHOOK_SECRET` (or `PAYSTACK_SECRET_KEY` fallback)
  - All payment endpoints return **503 "Payment system not configured (Stripe|Paystack)"** when the provider's secret is missing — no crash, no silent failure
  - `_fulfill_payment()` idempotent (guarded by `credits_granted` flag + `idempotency_key` on credit transactions)
- Admin overview, users, parcels, evidence (approve), jobs (process), audit log
- Trust validation — **REAL sub-scores from DB counts** (no false 100s), graded A_PLUS … F
- Take-off readiness assessment
- Job queue (PENDING → PROCESSING → COMPLETED/FAILED) with mock OCR/duplicate/fraud
  and real confidence recalculation
- Audit log on every material action; timeline events per parcel
- Indexes on users.email, parcels.parcel_number, sessions.session_token, etc.

### Frontend (React)
- Landing (`/`) — split layout, hero, trust stats, six pricing cards, demo login
- Public verification (`/verify`)
- Trust architecture (`/trust`)
- Community transparency (`/community-transparency`)
- Citizen dashboard (`/dashboard`) — KPIs, parcels list, create-parcel dialog,
  evidence-upload dialog, wallet widget, activity timeline
- Validator dashboard (`/validator`) — queue + attestation form + my attestations
- Surveyor dashboard (`/surveyor`) — assignments + survey upload form + recent surveys
- Admin dashboard (`/admin`) — KPI row, trust panel, readiness panel, 13-layer health,
  tabs for users/parcels/evidence/jobs/audit, action buttons (run trust, process jobs, scan)
- Billing (`/billing`) — credit packs + plans + Stripe & Paystack checkout
- Stripe success/cancel + Paystack success polling pages

### Theme
- Green-to-blue gradient background, Plus Jakarta Sans + Inter + JetBrains Mono fonts
- Cards: `#fff` + soft green shadow, glass-morphism for stats panels
- Trust stamps and badges in custom monospace

## 5. Test coverage (iteration 1)
- Backend: **28/28** pytest tests passed (`/app/backend/tests/backend_test.py`)
- Frontend: **9/9** UI flows verified (landing, public verify, citizen/validator/surveyor/admin
  dashboards, plus form submissions and admin actions)
- Critical issues: **0**
- Minor issues: 1 (cosmetic key naming on `/api/public/stats`)

## 6. Deferred (P1)
- Phase 8 frontend dashboards for Legal / Institutional / Observer (**backend ready**, includes risk engine + real PDF report generation via job queue; only the React pages remain)
- Real Paystack integration ✅ DONE (iteration 2)
- Stripe webhook signature verification ✅ DONE (iteration 2)
- Enterprise backend refactor ✅ DONE (iteration 3 / Phase 9)
- Real OCR / fraud scoring (mocked)
- Cloudflare R2 file storage
- Rate limiting + Sentry instrumentation
- CI/CD pipeline scaffolding

## 7. Backlog (P2)
- Stripe Metered Billing for institutional plans
- Email notifications (Resend / Postmark)
- Mapbox parcel boundary visualisation
- Bulk verification API for institutional users
- Recovery test runner + scheduled backups
- Multi-region Neon read replicas (Lagos)

## 8. Known limitations
- Email/password sign-up flow not exposed in UI (Google + demo only)
- Apple / Microsoft / Facebook social buttons are visual-only placeholders
- AI/OCR is mocked (returns canned text). Replacement with Emergent integrations is P2.

## 9. P0 + P1 hardening (iteration 4 — 2026-06-25)
**P0 Tenant Isolation & Transaction Safety + P1 Worker + Reports — COMPLETE**

### Tenant Isolation (structural, RLS-equivalent)
- `core/tenant.py` — `ContextVar` carrying `tenant_id`, `bypass_tenant()` context manager
- `core/safe_db.py` — `SafeCollection` wrapper auto-injects `tenant_id` into
  every `find`/`find_one`/`count`/`update`/`delete`/`insert`/`aggregate`/`distinct`/
  `find_one_and_*` call. Unauthenticated context filters to `__NO_TENANT_CONTEXT__`
  (default-deny). Exposed as `tdb` singleton.
- `core/security.get_current_user` now calls `set_tenant(user.tenant_id)` so the
  context propagates through the entire request.
- Routers switched to `tdb`: `parcels`, `evidence`, `credits`, `notifications`,
  `dashboards.citizen`. Admin / Legal / Institution / Observer / Public routers
  continue to use the raw `db` collection for legitimate cross-tenant queries.
- 5 regression tests verify cross-tenant reads/writes/listings/dashboards/
  notifications/wallets are all blocked (`tests/test_tenant_isolation.py`).

### Transaction Safety (multi-doc ACID)
- MongoDB upgraded to a single-node replica set (`rs0`) so `start_session()` +
  `start_transaction()` engage at runtime. `mongod` supervisor command updated.
- `core/tx.py` — `atomic_transaction()` context + `run_in_transaction(coro_factory)`
  with **auto-retry on TransientTransactionError / WriteConflict** (5 retries,
  exponential backoff with jitter).
- `services/payments.deduct_credits` and `services/payments.fulfill_payment`
  now run inside `run_in_transaction()`. Conditional `balance >= amount` filter
  + idempotency-key guard prevent double spending under any race.
- 2 concurrency tests verify (a) 10 concurrent /api/parcels against a 25-credit
  wallet yields exactly 5×200 + 5×402, final balance 0 — never negative; and
  (b) idempotency-key replay does not double-charge.

### Background Worker (production async)
- `services/worker.py` — long-lived asyncio task started in FastAPI `startup`,
  stopped in `shutdown`. Polls `job_queue` every `WORKER_POLL_INTERVAL` (5s),
  claims jobs atomically via `find_one_and_update`, executes via
  `services.jobs._execute_job`. Exponential-backoff retries on failure
  (10s × 2^attempt with jitter), terminal `DEAD_LETTER` after `max_attempts`.
- Auto-routes all job types (OCR, duplicate detection, confidence recalc,
  fraud scoring, certificate generation, legal/institution reports, backup,
  audit, security scan, abuse detection, take-off, trust validation).

### Real PDF + CSV Reports (worker-generated)
- `services/trust.render_legal_report_csv` and `render_institution_report_csv`
  emit downloadable CSV artifacts alongside the existing reportlab PDFs.
- `LEGAL_REPORT` and `INSTITUTION_REPORT` job handlers store both URLs:
  `result_url` (PDF) + `csv_url` (CSV) on `db.reports`.
- `GET /api/legal/reports/{id}/download(.csv)` and
  `GET /api/institution/reports/{id}/download(.csv)` serve the artifacts
  through `FileResponse`, with role-scoped + owner-scoped access checks.

### Test coverage delta (iteration 4)
- Backend: **51 passed, 2 skipped, 0 failed** (was 38)
  - +5 tenant isolation tests
  - +2 concurrency tests
  - +6 worker + report E2E tests (`tests/test_worker_reports.py`)
- Pytest marker `tx_test` registered in `/app/backend/pytest.ini`.

### Operational notes
- `ENABLE_TEST_ENDPOINTS` env flag gates `POST /api/auth/test-bootstrap-citizen`
  and `POST /api/auth/test-set-balance` — defaults to true in dev, set to
  `false` for production deployments.
- Demo wallets are auto-topped-up to baseline (250 / 1000) on every backend
  startup, so drained-wallet flakes across pytest runs are eliminated.

## 10. Backlog (P2) — unchanged
- Scheduled automations (abuse 30m, fraud 15m, backup daily 02:00) — cron / APScheduler layer
- Real OCR / fraud scoring via Emergent integrations (awaiting user go-ahead)
- Stripe Metered Billing for institutional plans
- Email notifications (Resend / Postmark)
- Mapbox parcel boundary visualisation
- Bulk verification API for institutional users
- Cloudflare R2 file storage
- Rate limiting + Sentry instrumentation
