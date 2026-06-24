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
### Backend (`/app/backend/server.py`)
- Emergent Google Auth + `/api/auth/dev-login` test bypass
- `/api/auth/me`, `/api/auth/logout` with httpOnly session cookie + Bearer fallback
- Public: `/api/public/stats`, `/api/public/verify`, `/api/public/plans`, `/api/public/transparency`
- Parcels CRUD, evidence vault (SHA-256), community attestations (RBAC ≥ COMMUNITY_VALIDATOR)
- Surveyor assignments + survey plan upload (RBAC ≥ SURVEYOR)
- Credit wallet with atomic `$inc` deductions + idempotency keys
- Stripe Checkout via `emergentintegrations` (USD-equivalent NGN); polling status endpoint
- Paystack init/verify sandbox stub with idempotent credit grant
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
- Legal / Institutional / Observer dashboards (routes ready, currently fall through to Citizen)
- Real Paystack integration (requires merchant credentials)
- Stripe webhook signature verification (current flow uses status polling — works for sandbox)
- Real OCR / fraud scoring (mocked)
- Cloudflare R2 file storage (current evidence uses external URLs)
- PDF certificate rendering (currently flagged as ISSUED, no actual PDF asset)
- Rate limiting (Upstash) and Sentry instrumentation
- CI/CD pipeline scaffolding

## 7. Backlog (P2)
- Stripe Metered Billing for institutional plans
- Email notifications (Resend / Postmark)
- Mapbox parcel boundary visualisation
- Bulk verification API for institutional users
- Recovery test runner + scheduled backups
- Multi-region Neon read replicas (Lagos)

## 8. Known limitations
- Tenant isolation is enforced per-handler (no automatic global Mongoose-style pre-hook)
- Email/password sign-up flow not exposed in UI (Google + demo only)
- Apple / Microsoft / Facebook social buttons are visual-only placeholders
