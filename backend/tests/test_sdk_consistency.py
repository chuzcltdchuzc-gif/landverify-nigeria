"""Phase 3.9 — SDK consistency / drift gate.

Asserts that the TypeScript SDK at /app/frontend/src/sdk/ is in sync
with the frozen contract package at /app/contracts/v1/. Specifically:

* The SDK's pinned `contractVersion` + `sdkVersion` + `aggregateSha256`
  match the canonical `sdk/compatibility.json`.
* Every URL the SDK calls maps to a path in the frozen OpenAPI spec.
* The SDK exposes the four Phase 3.8 admin projection endpoints.

This is the constitutional Zero Contract Drift gate for Phase 3.9.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SDK_DIR = ROOT / "frontend" / "src" / "sdk"
COMPAT_PATH = ROOT / "contracts" / "v1" / "sdk" / "compatibility.json"
OPENAPI_PATH = ROOT / "contracts" / "v1" / "openapi.json"


def _load_json(p: Path) -> dict:
    return json.loads(p.read_text())


def _read(p: Path) -> str:
    return p.read_text()


# ---- 1. Meta pin matches contract package -------------------------------

def test_sdk_meta_matches_compatibility_manifest():
    compat = _load_json(COMPAT_PATH)
    meta = _read(SDK_DIR / "meta.ts")
    for field, key in (
        ("contractVersion", "contract_version"),
        ("sdkVersion", "sdk_version"),
        ("aggregateSha256", "aggregate_sha256"),
    ):
        m = re.search(rf"{field}:\s*'([^']+)'", meta)
        assert m, f"sdk/meta.ts missing {field}"
        assert m.group(1) == compat[key], (
            f"SDK drift: {field}={m.group(1)!r} vs contract {compat[key]!r}")


# ---- 2. SDK only calls /api/v1/* paths ---------------------------------

# A loose regex over every SDK client. Any string literal beginning with
# `/api` is treated as an HTTP path the SDK calls and MUST be in OpenAPI.
PATH_RE = re.compile(r"['`](/api/v1/[^'`$]+)")
QUOTE_RE = re.compile(r"'(/api/v1/[^']+)'")
TPL_RE = re.compile(r"`(/api/v1/[^`]+)`")


def _all_sdk_paths() -> set[str]:
    paths: set[str] = set()
    for f in ("auth.ts", "evidence.ts", "projections.ts"):
        src = _read(SDK_DIR / f)
        for regex in (QUOTE_RE, TPL_RE):
            for m in regex.finditer(src):
                raw = m.group(1)
                normalized = re.sub(r"\$\{[^}]+\}", "{x}", raw)
                normalized = normalized.split("?")[0].rstrip("/")
                if normalized:
                    paths.add(normalized)
    return paths


def _all_openapi_paths() -> set[str]:
    spec = _load_json(OPENAPI_PATH)
    return {re.sub(r"\{[^}]+\}", "{x}", p) for p in spec["paths"].keys()}


def test_every_sdk_path_exists_in_openapi():
    sdk_paths = _all_sdk_paths()
    openapi_paths = _all_openapi_paths()
    missing = sdk_paths - openapi_paths
    assert not missing, (
        f"SDK references paths that don't exist in OpenAPI: {sorted(missing)}\n"
        f"OpenAPI paths sample: {sorted(openapi_paths)[:5]}")


def test_sdk_covers_phase38_admin_projection_endpoints():
    sdk_paths = _all_sdk_paths()
    required = {
        "/api/v1/admin/projections",
        "/api/v1/admin/projections/{x}",
        "/api/v1/admin/projections/{x}/replay",
        "/api/v1/admin/projections/{x}/snapshot",
    }
    missing = required - sdk_paths
    assert not missing, f"SDK missing Phase 3.8 admin endpoints: {missing}"


def test_sdk_covers_evidence_projection_endpoints():
    """Phase 3.9 mandate: React UI consumes projection endpoints only.

    The SDK MUST expose every read-side projection surface for
    Evidence (timeline, custody, supersession-chain, legal-holds,
    integrity, locks)."""
    sdk_paths = _all_sdk_paths()
    required = {
        "/api/v1/evidence/items/{x}/timeline",
        "/api/v1/evidence/items/{x}/custody",
        "/api/v1/evidence/items/{x}/supersession-chain",
        "/api/v1/evidence/items/{x}/legal-holds",
        "/api/v1/evidence/locks/by-evidence/{x}",
        "/api/v1/evidence/integrity-checks/by-evidence/{x}",
    }
    missing = required - sdk_paths
    assert not missing, f"SDK missing Evidence projection endpoints: {missing}"


# ---- 3. React app consumes the SDK only --------------------------------

PAGES_DIR = ROOT / "frontend" / "src" / "pages" / "evidence"


def test_evidence_pages_never_call_fetch_or_axios_directly():
    """Constitutional rule: zero direct REST calls outside the SDK."""
    if not PAGES_DIR.exists():
        pytest.skip("evidence pages not yet implemented")
    offenders: list[str] = []
    forbidden_patterns = (
        r"\bfetch\s*\(", r"\baxios[\.\(]", r"new XMLHttpRequest",
        r"from\s+['\"]axios['\"]",
    )
    for p in PAGES_DIR.rglob("*.jsx"):
        src = p.read_text()
        for pat in forbidden_patterns:
            if re.search(pat, src):
                offenders.append(f"{p.relative_to(ROOT)}: matches {pat!r}")
    assert not offenders, (
        "Evidence UI pages contain direct REST calls (must go through SDK):\n"
        + "\n".join(offenders))


def test_evidence_pages_import_only_from_sdk_for_network():
    """The only allowed network import inside Evidence pages is from
    the local SDK (via the useSdk hook). Reject any import of api.js."""
    if not PAGES_DIR.exists():
        pytest.skip("evidence pages not yet implemented")
    offenders: list[str] = []
    for p in PAGES_DIR.rglob("*.jsx"):
        src = p.read_text()
        if re.search(r"from\s+['\"][^'\"]*lib/api['\"]", src):
            offenders.append(f"{p.relative_to(ROOT)} imports lib/api")
    assert not offenders, "\n".join(offenders)


# ---- 4. Smoke check that compatibility manifest still pins v1.5.0+ -----

def test_compatibility_manifest_at_or_above_v1_5_0():
    compat = _load_json(COMPAT_PATH)
    v = compat["contract_version"].split(".")
    assert int(v[0]) == 1 and int(v[1]) >= 5, (
        f"Compatibility manifest contract_version too old: {compat['contract_version']}")
