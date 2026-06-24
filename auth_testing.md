# Auth Testing Playbook — Aquasavannah LandVault

Auth provider: **Emergent-managed Google Auth**

## Cookie / Session Model
- Successful Google OAuth callback drops `session_id` into URL fragment.
- Frontend `AuthCallback` route POSTs `session_id` to `POST /api/auth/session`.
- Backend exchanges with Emergent `/auth/v1/env/oauth/session-data`, stores session, sets `session_token` httpOnly cookie (7 days).
- All protected APIs accept `session_token` cookie OR `Authorization: Bearer <token>`.

## Dev / Test Login (no Google)
For the testing agent, use:
```
curl -X POST $BACKEND/api/auth/dev-login \
  -H 'Content-Type: application/json' \
  -d '{"role":"CITIZEN"}'
```
Response includes `session_token`. Use it as:
```
-H "Authorization: Bearer <session_token>"
```
or set as cookie:
```
session_token=<token>; path=/; HttpOnly; Secure; SameSite=None
```

## Test Identities
| Role | Email |
| --- | --- |
| CITIZEN | citizen.demo@landvault.test |
| COMMUNITY_VALIDATOR | validator.demo@landvault.test |
| SURVEYOR | surveyor.demo@landvault.test |
| ADMIN | admin.demo@landvault.test |

## Critical Endpoints to Verify
- `GET  /api/auth/me` → returns logged-in user (200) or 401
- `POST /api/auth/logout` → clears cookie and session
- `GET  /api/public/verify?parcel_number=...` → no auth required
- `GET  /api/dashboard/citizen` → CITIZEN+ required
- `GET  /api/dashboard/validator` → COMMUNITY_VALIDATOR+ required
- `GET  /api/dashboard/surveyor` → SURVEYOR+ required
- `GET  /api/admin/overview` → ADMIN required

## Logout Test
1. Login via dev-login → keep session_token
2. Hit `/api/auth/me` → 200
3. POST `/api/auth/logout` → 200
4. Hit `/api/auth/me` with same token → 401
