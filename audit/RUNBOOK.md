# Aquasavannah LandVault — Operational Runbook

> Generated: 2026-06-30 · Permanent operational documentation.
> Audience: Platform operators, on-call engineers, compliance leads.
> Cross-links: [Acceptance Packet](../audit/PHASE-3-ACCEPTANCE-PACKET.md) ·
> [Security Readiness Report](R-2-SECURITY-READINESS-REPORT.md) ·
> [Production Readiness Review](PRODUCTION-READINESS-REVIEW.md)

This runbook is the binding operational guide for the Aquasavannah
LandVault platform. Every procedure here is reproducible from the
codebase at HEAD of the `main` branch.

---

## Table of Contents

1. [Deployment](#1-deployment)
2. [Rollback](#2-rollback)
3. [Disaster Recovery](#3-disaster-recovery)
4. [Backup & Restore](#4-backup--restore)
5. [RPO / RTO targets](#5-rpo--rto-targets)
6. [Evidence Replay](#6-evidence-replay)
7. [Projection Replay](#7-projection-replay)
8. [Merkle / Anchor Replay](#8-merkle--anchor-replay)
9. [Legal Hold Operations](#9-legal-hold-operations)
10. [Break-Glass Procedures](#10-break-glass-procedures)
11. [Key Rotation](#11-key-rotation)
12. [Monitoring Dashboards](#12-monitoring-dashboards)
13. [Alert Handling](#13-alert-handling)
14. [Incident Response](#14-incident-response)
15. [Operational Responsibilities](#15-operational-responsibilities)
16. [Maintenance Procedures](#16-maintenance-procedures)

---

## 1. Deployment

**Topology.** Single-pod FastAPI worker (`backend/main.py`) +
React static bundle (`frontend/build/`) fronted by an HTTPS
ingress. MongoDB runs as a 3-node replica set named `rs0`. Storage
adapter: Cloudflare R2 in production.

**Pre-flight checklist (binding).**

- [ ] `contracts/VERSION == 1.5.0` (or later frozen).
- [ ] `python -m pytest backend/tests/test_contract_freeze.py` is green.
- [ ] `python -m pytest backend/tests/test_sdk_consistency.py` is green.
- [ ] `python -m pytest backend/tests/test_security_headers.py` is green.
- [ ] Env-vars present in the production manifest:
  - `MONGO_URL` (replica-set DSN)
  - `DB_NAME`
  - `JWT_PRIVATE_KEY` (RS256 PEM) + `JWT_PUBLIC_JWKS`
  - `KMS_MASTER_KEY` (Ed25519, base64)
  - `RATE_LIMIT_ENABLED=1`
  - `OTS_MODE=public` (binds the real public TSA submitter)
  - `STORAGE_PROVIDER=r2`, `R2_ENDPOINT`, `R2_ACCESS_KEY`, `R2_SECRET_KEY`, `R2_BUCKET`, `R2_OBJECT_LOCK_MODE=compliance`
- [ ] Cloudflare R2 bucket has Object Lock enabled in `compliance` mode.
- [ ] HSTS preload submission completed (`hstspreload.org`).

**Step-by-step.**

```bash
# 1. Build the container image from the verified commit.
git checkout <release-tag>
docker build -f deploy/Dockerfile -t landvault:<release-tag> .

# 2. Push and roll the deployment (zero-downtime; rolling).
kubectl set image deploy/landvault-api app=landvault:<release-tag>
kubectl rollout status deploy/landvault-api --timeout=5m

# 3. Smoke test (external).
curl -sf https://<host>/api/v1/admin/projections -o /dev/null -w "%{http_code}\n"
# expect 401 (proves the service is up + auth required)

# 4. Authenticated smoke (super_admin token).
TOKEN=...
curl -sf -H "Authorization: Bearer $TOKEN" \
     https://<host>/api/v1/admin/projections | jq '.projections | length'
# expect ≥ 1 (evidence.timeline projection)

# 5. Wait for the projection cursor to stabilise.
sleep 30
curl -sf -H "Authorization: Bearer $TOKEN" \
     https://<host>/api/v1/admin/projections | jq '.projections[] | .lag_events'
# expect 0 across the board.
```

If any check fails, **abort and roll back (§2)**.

---

## 2. Rollback

The platform's append-only design makes rollback safe.

```bash
# Re-deploy the previous image tag.
kubectl set image deploy/landvault-api app=landvault:<previous-tag>
kubectl rollout status deploy/landvault-api --timeout=5m
```

**Why this is safe.**

- Aggregates are immutable; old code cannot corrupt data.
- Projections rebuild from the outbox via Phase 3.8 replay; any
  schema drift can be fixed by a `POST /api/v1/admin/projections/<name>/replay`.
- WORM artifacts cannot be undone, so rollback never erases evidence.

**Cannot roll back?**

- If the contract version moved forward (e.g. an additive endpoint),
  rollback to a pre-bump image will return 404 on those endpoints
  but won't corrupt data. The SDK consistency gate prevents the SDK
  from referencing endpoints that don't exist.

---

## 3. Disaster Recovery

Three failure modes are pre-planned:

### 3.1 Pod loss

Kubernetes deployment is `replicas: ≥ 2`. Loss of one pod is
recovered by the scheduler in seconds. Mongo replica set re-elects
within 10 s.

### 3.2 Region loss

R2 bucket is multi-region; Mongo replica set spans 2 AZs. Restore
from the most recent BSON dump (§4) into the surviving region.

### 3.3 Data corruption

Append-only model + Merkle anchor proofs (§8) mean any tampering is
detectable. The OTS proof submitted at seal-apply-worm time is a
non-repudiable timestamp held externally. Restore steps:

1. Promote a fresh Mongo replica set from the last hourly BSON dump.
2. Replay every projection (`POST /api/v1/admin/projections/<name>/replay`).
3. Run the integrity-check sweep
   (`POST /api/v1/evidence/integrity-checks` per evidence_id).
4. Cross-verify the surviving Merkle root against the OTS proof.

---

## 4. Backup & Restore

### Backup policy

- **Hourly:** Mongo replica-set incremental oplog tail (15 s window).
- **Daily:** Full BSON dump (`mongodump`) → encrypted S3 bucket
  (`landvault-backups`), 30-day retention.
- **Weekly:** R2 bucket inventory snapshot — Object Lock retention
  means objects themselves cannot be deleted before the horizon, so
  the inventory snapshot suffices.
- **Quarterly:** Full restore drill into the staging cluster.

### Restore procedure

```bash
# 1. Provision a fresh Mongo replica set.
helm install rs0 bitnami/mongodb \
    --set architecture=replicaset \
    --set replicaCount=3

# 2. Load the most recent BSON dump.
aws s3 cp s3://landvault-backups/$(date +%F)/dump.tgz - | \
    mongorestore --archive --uri="$NEW_MONGO_URL"

# 3. Apply outstanding oplogs.
mongo --uri="$NEW_MONGO_URL" --eval \
    'db.oplog.rs.replayUntil("'$STOP_TS'")'

# 4. Point the API pod at the new Mongo and re-deploy.
kubectl set env deploy/landvault-api MONGO_URL="$NEW_MONGO_URL"

# 5. Replay all projections.
TOKEN=$(./scripts/issue-super-admin-token.sh)
for p in $(curl -sH "Authorization: Bearer $TOKEN" \
            https://<host>/api/v1/admin/projections | \
            jq -r '.projections[].name'); do
    curl -X POST -H "Authorization: Bearer $TOKEN" \
        https://<host>/api/v1/admin/projections/$p/replay
done
```

---

## 5. RPO / RTO targets

| Metric | Target | Rationale |
| --- | --- | --- |
| **RPO** (Recovery Point Objective) | ≤ 15 minutes | Hourly BSON dumps + 15-second oplog tail. |
| **RTO** (Recovery Time Objective) | ≤ 2 hours | Pre-warmed staging cluster; restore + replay is the bottleneck. |
| **Replay throughput** | ≥ 800 events/sec | Measured at 821 events/sec in [perf bench](../audit/perf/results.json). |
| **Hourly OTS anchor cadence** | ≤ 1 hour latency from seal-apply-worm to confirmed OTS proof | Anchoring saga ticks every 10 minutes. |

---

## 6. Evidence Replay

A read-side rebuild of every evidence projection from the immutable
event ledger.

```bash
TOKEN=$(./scripts/issue-super-admin-token.sh)
curl -X POST -H "Authorization: Bearer $TOKEN" \
     https://<host>/api/v1/admin/projections/evidence.timeline/replay | jq
```

**Expected response (excerpt).**

```jsonc
{
  "name": "evidence.timeline",
  "delivered_count": 1675,
  "rebuilding": false,
  "lag_events": 0
}
```

The replay is **byte-identical** to the pre-replay state — proven by
`test_phase38_projections.py::test_timeline_replay_is_byte_identical_end_to_end`.
Cleared cursors and dropped projection rows during the rebuild
window do **not** corrupt the read side; the publisher continues
delivering live events idempotently.

---

## 7. Projection Replay

The Evidence UI exposes a one-click replay button at
`https://<host>/evidence/admin/projections`. The CLI equivalent:

```bash
# List projections + cursor status.
curl -sH "Authorization: Bearer $TOKEN" \
     https://<host>/api/v1/admin/projections | jq

# Replay any single projection.
curl -X POST -H "Authorization: Bearer $TOKEN" \
     https://<host>/api/v1/admin/projections/<name>/replay

# Record a snapshot baseline.
curl -X POST -H "Authorization: Bearer $TOKEN" \
     https://<host>/api/v1/admin/projections/<name>/snapshot
```

---

## 8. Merkle / Anchor Replay

Anchoring is a saga that batches WORM-locked seals and submits the
root to OpenTimestamps + the internal CT-log. To force a replay (e.g.
after fixing the OTS adapter):

```bash
# Inspect anchor batches.
curl -sH "Authorization: Bearer $TOKEN" \
     https://<host>/api/v1/evidence/anchor-batches | jq

# Re-trigger anchoring for a specific seal (idempotent — re-uses batch).
curl -X POST -H "Authorization: Bearer $TOKEN" \
     https://<host>/api/v1/evidence/anchor-batches/<batch_id>/resume
```

The saga uses persistent state in `evidence_anchor_batches`; replay
re-uses identifiers, so duplicate OTS submissions are impossible.

---

## 9. Legal Hold Operations

### Applying a hold

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"case_reference":"FHC/L/2026/001","reason":"Subpoena dated 2026-06-15"}' \
    https://<host>/api/v1/evidence/items/<evidence_id>/legal-holds
```

Required role: `super_admin` or `compliance_officer`.

### Releasing a hold

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"release_reason":"Case dismissed per court order 2026-06-29"}' \
    https://<host>/api/v1/evidence/legal-holds/<hold_id>/release
```

Release is **terminal and immutable** — a released hold cannot be
re-activated. A second hold is a brand-new aggregate.

### Listing holds for an evidence item

```bash
curl -sH "Authorization: Bearer $TOKEN" \
     https://<host>/api/v1/evidence/items/<evidence_id>/legal-holds | jq
```

---

## 10. Break-Glass Procedures

Emergency operator access without the normal JWT flow.

**Trigger conditions** (operator must record one):

1. Catastrophic key compromise — issue a temporary key.
2. Compliance-mandated retrieval where the regular auth path is unavailable.
3. Data restoration after a regional disaster.

**Procedure.**

```bash
# 1. SSH to the bastion host with hardware-key 2FA.
ssh ops@bastion.aquasavannah.gov.ng

# 2. Mint a 15-minute super_admin token signed by the break-glass
#    KMS key (separate from the production signing key).
./scripts/breakglass-mint --reason "<text>" --ticket <ticket-id> --duration 15m

# 3. Every break-glass token is automatically:
#    - Logged to the immutable audit_log.
#    - Notified to the compliance pager channel.
#    - Expired ≤ 15 minutes (hard ceiling).
```

After every break-glass session, run `./scripts/breakglass-audit-report
--ticket <ticket-id>` and file the output with compliance.

---

## 11. Key Rotation

### JWT signing key (RS256)

```bash
# 1. Generate the next active key.
./scripts/rotate-jwt --generate-next

# 2. Switch the active kid.
./scripts/rotate-jwt --promote-next

# 3. Wait for the JWKS rotation grace window (15 minutes).
sleep 900

# 4. Revoke the previous kid.
./scripts/rotate-jwt --revoke <previous-kid>
```

Cadence: every **90 days**, OR immediately upon suspected compromise.

### Internal CT-log signing key (Ed25519)

Until R-4 (HSM migration) lands, this rotation requires manual KMS
intervention:

```bash
./scripts/rotate-ctlog-key --new-kid <new-kid>
```

Old checkpoints remain verifiable forever (the public key for each
kid is retained).

### Refresh-cookie HMAC secret

Rotated together with the JWT signing key.

---

## 12. Monitoring Dashboards

A read-only dashboard at `https://<host>/evidence/admin/projections`
shows:

| Metric | Where |
| --- | --- |
| Projection cursor + lag | `/evidence/admin/projections` |
| Last delivered event type | same |
| Last snapshot baseline | same |
| Anchor batch status | `/evidence/items/<id>/seal` tab on the Evidence Detail page |
| Integrity check history | `/evidence/items/<id>/integrity` tab |
| Authoritative composite hash | `/evidence/items/<id>` overview |

External:
- Mongo replica-set status (`rs.status()`).
- Pod CPU / memory / RSS via Kubernetes metrics.
- Cloudflare R2 request volume + 4xx rate.

---

## 13. Alert Handling

| Alarm | Threshold | Action |
| --- | --- | --- |
| `projection.lag_events > 1000 for 5m` | sustained | Replay the projection (§7). |
| `auth.login.failed > 50/min/IP` | sustained | Confirm Cloudflare edge rate limit is engaged. |
| `integrity.failed event` | any | Page compliance + open an incident (§14). |
| `anchor.batch.failed event` | 3 consecutive | Page on-call platform engineer. Verify OTS network reachability. |
| `kernel_outbox.PENDING > 10000` | sustained 10m | Inspect background publisher health. Restart pod if needed. |
| 5xx rate > 1% over 5m | sustained | Page on-call. |
| Mongo replica lag > 30s | sustained | Page DBA. |

---

## 14. Incident Response

### Severities

- **SEV-1 — Evidence integrity compromised.** Engage compliance lead + legal counsel within 1 hour.
- **SEV-2 — User-visible outage.** Engage platform on-call within 15 minutes.
- **SEV-3 — Degradation.** Open a ticket within 1 business day.

### Standard SEV-1 / SEV-2 runbook

1. **Acknowledge** the page within 5 minutes.
2. **Triangulate** using §12 dashboards and the timeline projection.
3. **Stabilise** — favour the simplest mitigation:
   - Pause the publisher (`kernel.outbox.publisher.pause`) to halt event flow.
   - Roll the deployment (§2).
   - Replay affected projections (§7).
4. **Communicate** — broadcast on the status page every 30 minutes.
5. **Post-mortem** — within 5 business days, public for SEV-1, internal for SEV-2.

### Forensic snapshot

For SEV-1, immediately snapshot the entire `kernel_outbox` collection
to S3 (`./scripts/forensic-snapshot --collection kernel_outbox`).
This is the immutable source of truth that must survive any
remediation.

---

## 15. Operational Responsibilities

| Role | Responsibility |
| --- | --- |
| Platform on-call | First responder for SEV-1/2. Deploys, rollbacks, projection replays. |
| Database on-call | Mongo replica-set health, backups, point-in-time restore. |
| Security on-call | Key rotation, suspected compromise, break-glass approvals. |
| Compliance lead | Legal hold approvals, SEV-1 disclosures, retention policy. |
| Operator (super_admin) | Final authorization for break-glass, anchoring saga changes, projection schema changes. |

A single PagerDuty escalation policy covers all four. Rotation cadence: weekly.

---

## 16. Maintenance Procedures

### 16.1 Patching

- OS / runtime: monthly base-image rebuild + rolling deploy.
- Python deps: monthly `pip freeze` regen + smoke test in staging.
- Frontend deps: monthly `yarn upgrade --latest --interactive` with CI.

### 16.2 Index hygiene

```bash
# Each repository ensures its indexes at boot (idempotent). To force:
./scripts/ensure-indexes
```

### 16.3 Contract bumps

A contract bump (e.g. v1.5.0 → v1.6.0) follows the binding workflow:

1. Edit `contracts/generate.py` + bump `contracts/VERSION`.
2. Run `python -m contracts.generate`.
3. Confirm `tests/test_contract_freeze.py` is green.
4. Regenerate the SDK consistency check (the hand-derived TS SDK
   needs the new endpoints added before `tests/test_sdk_consistency.py`
   will pass).
5. Update the CHANGELOG at `contracts/CHANGELOG.md`.
6. Commit + deploy.

### 16.4 Soak test before a public launch

Run the perf harness at the largest realistic data size:

```bash
cd /app/backend && python -m tests.bench_phase310
```

Confirm p95 ≤ 250 ms across all read probes. The results JSON is
the artifact to attach to the launch ticket.

---

## End of Runbook

Last edited: 2026-06-30. The next edit MUST bump the date at the top
of this document and be cross-referenced from the PRD changelog.
