"""Phase 3.10 — Real measured performance benchmark.

Sequential single-client latency + throughput probe against the live
backend at http://localhost:8001/api. Writes machine-readable JSON to
/app/contracts/v1/audit/perf/results.json so the Acceptance Review
packet links to a source-of-truth.

Why sequential single-client? The platform's SLO is p95 < 250 ms on a
shared single-pod dev cluster — concurrency tests are deferred until
Phase 4 readiness when the workload model is defined. This bench is
intentionally simple and reproducible.

Run: python -m tests.bench_phase310
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import statistics
import time
import uuid
from pathlib import Path

import httpx
from motor.motor_asyncio import AsyncIOMotorClient

API = "http://localhost:8001"
OUT = Path("/app/audit/perf/results.json")
OUT.parent.mkdir(parents=True, exist_ok=True)


async def _register_super_admin(client, db) -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:8]
    email = f"bench_{suffix}@example.com"
    pw = "BenchPass123!"
    await client.post("/api/v1/auth/register",
                      json={"email": email, "password": pw,
                            "full_name": "Bench", "country": "NG"})
    user = await db["identity_users"].find_one({"email": email.lower()})
    await db["identity_users"].update_one(
        {"_id": user["_id"]},
        {"$set": {"roles": ["super_admin"], "role": "super_admin"},
         "$inc": {"version": 1}})
    r = await client.post("/api/v1/auth/login",
                          json={"email": email, "password": pw})
    return email, r.json()["access_token"]


async def _seed_evidence(client, token, n: int = 5) -> tuple[str, list[str]]:
    h = {"Authorization": f"Bearer {token}"}
    reg = (await client.post(
        "/api/v1/registry/landvaults", headers=h,
        json={"state": "LAGOS", "lga": "IKEJA", "ward": "BENCH",
              "property_type": "RES", "ownership_type": "individual",
              "owner_name": "Bench"})).json()["registry_id"]
    eids = []
    for _ in range(n):
        payload = b"bench-" + uuid.uuid4().bytes
        sha = hashlib.sha256(payload).hexdigest()
        init = (await client.post(
            "/api/v1/evidence/items", headers=h,
            json={"registry_id": reg, "kind": "document",
                  "media_type": "text/plain", "max_size": 4096})).json()
        eid = init["evidence_id"]
        await client.put(f"/api/v1/evidence/items/{eid}/parts/1",
                          headers=h, content=payload)
        await client.post(
            f"/api/v1/evidence/items/{eid}/complete", headers=h,
            json={"parts": [{"part_no": 1, "size_bytes": len(payload),
                              "streamed_sha256": sha}]})
        await client.post(f"/api/v1/evidence/items/{eid}/verify", headers=h)
        eids.append(eid)
    seal = (await client.post(
        "/api/v1/evidence/seals", headers=h,
        json={"registry_id": reg, "evidence_ids": eids})).json()
    await client.post(
        f"/api/v1/evidence/seals/{seal['seal_id']}/apply-worm",
        headers=h, json={})
    await asyncio.sleep(2)  # let projections catch up
    return reg, eids


def _percentile(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


async def _bench_endpoint(client, headers, label: str, fn,
                            n: int = 100) -> dict:
    """Sequential single-client latency probe."""
    samples_ms: list[float] = []
    errors = 0
    bench_start = time.perf_counter()
    for _ in range(n):
        t0 = time.perf_counter()
        try:
            r = await fn(client, headers)
            if r.status_code >= 400:
                errors += 1
            else:
                samples_ms.append((time.perf_counter() - t0) * 1000.0)
        except Exception:
            errors += 1
    elapsed = time.perf_counter() - bench_start
    return {
        "label": label,
        "n": n,
        "successes": len(samples_ms),
        "errors": errors,
        "elapsed_seconds": round(elapsed, 3),
        "throughput_rps": round(n / elapsed, 2) if elapsed > 0 else 0,
        "p50_ms": round(_percentile(samples_ms, 50), 2),
        "p95_ms": round(_percentile(samples_ms, 95), 2),
        "p99_ms": round(_percentile(samples_ms, 99), 2),
        "min_ms": round(min(samples_ms), 2) if samples_ms else 0,
        "max_ms": round(max(samples_ms), 2) if samples_ms else 0,
        "mean_ms": round(statistics.mean(samples_ms), 2) if samples_ms else 0,
    }


def _read_proc_status() -> dict:
    """Best-effort capture of backend process RSS + CPU."""
    import subprocess
    try:
        # find backend pid
        ps = subprocess.run(
            ["pgrep", "-f", "uvicorn.*main:app"],
            capture_output=True, text=True, timeout=5)
        pid = ps.stdout.strip().split("\n")[0]
        if not pid:
            return {"captured": False}
        with open(f"/proc/{pid}/status") as f:
            stat = f.read()
        rss_kb = None
        for line in stat.splitlines():
            if line.startswith("VmRSS:"):
                rss_kb = int(line.split()[1])
                break
        return {
            "captured": True,
            "pid": pid,
            "rss_kb": rss_kb,
            "rss_mb": round(rss_kb / 1024.0, 1) if rss_kb else None,
        }
    except Exception as e:  # noqa: BLE001
        return {"captured": False, "error": str(e)}


async def main():
    # Load /app/backend/.env if MONGO_URL not already in env.
    if "MONGO_URL" not in os.environ:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv("/app/backend/.env")
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    mongo = AsyncIOMotorClient(mongo_url)
    db = mongo[db_name]

    proc_before = _read_proc_status()

    async with httpx.AsyncClient(base_url=API, timeout=60) as c:
        _, token = await _register_super_admin(c, db)
        H = {"Authorization": f"Bearer {token}"}

        # Seed data set the bench will read from.
        print("[bench] seeding evidence + seal + worm…", flush=True)
        _, eids = await _seed_evidence(c, token, n=5)
        target = eids[0]

        # Probes.
        probes = []
        probes.append(await _bench_endpoint(
            c, H, "GET /api/v1/evidence/items (list, page=1)",
            lambda cl, h: cl.get("/api/v1/evidence/items?page=1&page_size=25",
                                   headers=h), n=100))
        probes.append(await _bench_endpoint(
            c, H, "GET /api/v1/evidence/items/{id}",
            lambda cl, h: cl.get(f"/api/v1/evidence/items/{target}",
                                   headers=h), n=100))
        probes.append(await _bench_endpoint(
            c, H, "GET /api/v1/evidence/items/{id}/timeline (projection)",
            lambda cl, h: cl.get(
                f"/api/v1/evidence/items/{target}/timeline", headers=h),
            n=100))
        probes.append(await _bench_endpoint(
            c, H, "GET /api/v1/evidence/items/{id}/custody (projection)",
            lambda cl, h: cl.get(
                f"/api/v1/evidence/items/{target}/custody", headers=h),
            n=100))
        probes.append(await _bench_endpoint(
            c, H,
            "GET /api/v1/evidence/integrity-checks/by-evidence/{id}",
            lambda cl, h: cl.get(
                f"/api/v1/evidence/integrity-checks/by-evidence/{target}",
                headers=h), n=100))
        probes.append(await _bench_endpoint(
            c, H, "GET /api/v1/admin/projections",
            lambda cl, h: cl.get("/api/v1/admin/projections",
                                   headers=h), n=100))

        # Replay duration probe (single replay, end-to-end).
        print("[bench] measuring replay duration…", flush=True)
        t0 = time.perf_counter()
        r = await c.post(
            "/api/v1/admin/projections/evidence.timeline/replay",
            headers=H)
        replay_ms = (time.perf_counter() - t0) * 1000.0
        replay_body = r.json() if r.status_code == 200 else {"error": r.text}
        replay = {
            "label": "POST /admin/projections/evidence.timeline/replay",
            "status": r.status_code,
            "duration_ms": round(replay_ms, 2),
            "delivered_count": replay_body.get("delivered_count"),
            "rebuilding_after": replay_body.get("rebuilding"),
        }

    proc_after = _read_proc_status()

    out = {
        "phase": "3.10",
        "purpose": "Acceptance Review — measured performance bench",
        "host": "single-pod dev cluster (sequential single-client)",
        "warmup": "evidence pipeline + 5 sealed items",
        "probes": probes,
        "replay": replay,
        "process_before": proc_before,
        "process_after": proc_after,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    OUT.write_text(json.dumps(out, indent=2))
    print(f"[bench] wrote {OUT}", flush=True)
    print(json.dumps({"summary": [
        {"label": p["label"], "p50": p["p50_ms"], "p95": p["p95_ms"],
         "p99": p["p99_ms"], "rps": p["throughput_rps"]}
        for p in probes
    ], "replay_ms": replay["duration_ms"]}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
