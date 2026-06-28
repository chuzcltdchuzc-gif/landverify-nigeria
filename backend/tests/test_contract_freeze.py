"""Phase 1C — Platform Contract Freeze: strict drift detection.

This test is the CI gate that prevents silent API evolution. It re-runs
the contract generator in-memory and asserts the on-disk freeze matches
byte-for-byte.

If this test fails, the developer made a contract change without
regenerating the freeze. The fix is documented in the assertion message.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from contracts.generate import (
    CONTRACT_DIR,
    CONTRACT_VERSION,
    build_full_package,
    diff_against_disk,
)


def test_contract_version_pinned() -> None:
    """`contracts/VERSION` is the binding semver of the package."""
    version_file = CONTRACT_DIR / "VERSION"
    assert version_file.exists(), "contracts/VERSION missing — package not bootstrapped."
    text = version_file.read_text().strip()
    # MAJOR.MINOR.PATCH — refuse anything looser to keep semver discipline.
    parts = text.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts), (
        f"contracts/VERSION must be MAJOR.MINOR.PATCH semver; got {text!r}."
    )
    assert text == CONTRACT_VERSION


def test_contract_package_has_no_drift() -> None:
    """Live FastAPI surface MUST exactly match the frozen artifacts.

    If this fails, EITHER you changed an API/event/schema without bumping
    the contract OR you forgot to regenerate the freeze.

    To fix an intentional change:
        1. Decide on a semver bump in contracts/VERSION.
        2. Add an ADR under contracts/v1/adr/.
        3. Append a CHANGELOG entry referencing the ADR.
        4. Run: python -m contracts.generate
        5. Commit the updated contracts/ tree.
    """
    _, mismatches = diff_against_disk()
    if mismatches:
        paths = "\n  - ".join(a.relpath for a, _ in mismatches)
        pytest.fail(
            "Contract drift detected.\nFiles that differ:\n  - "
            f"{paths}\n\nRegenerate with `python -m contracts.generate` "
            "after bumping contracts/VERSION + adding an ADR + CHANGELOG "
            "entry."
        )


def test_every_artifact_is_committed() -> None:
    """The generator's artifact list MUST be exactly what's on disk —
    no orphan files, no missing files."""
    artifacts = build_full_package()
    expected = {a.relpath for a in artifacts}
    # Walk the contracts/v1 + contracts/release-manifest.json on disk.
    on_disk: set[str] = set()
    for p in (CONTRACT_DIR / "v1").rglob("*"):
        if p.is_file() and not p.name.startswith("."):
            rel = str(p.relative_to(CONTRACT_DIR))
            # ADRs, CHANGELOG, deprecation policy, and the placeholder
            # `examples/` directory are documentation, not generator output.
            if rel.startswith("v1/adr/") or rel.startswith("v1/examples/"):
                continue
            on_disk.add(rel)
    if (CONTRACT_DIR / "release-manifest.json").exists():
        on_disk.add("release-manifest.json")

    extra_on_disk = on_disk - expected
    missing_on_disk = expected - on_disk
    assert not extra_on_disk, (
        "Orphan artifacts present on disk (not produced by the generator). "
        f"Either delete them or add them to contracts/generate.py: {sorted(extra_on_disk)}"
    )
    assert not missing_on_disk, (
        "Generator declares artifacts that are not on disk. Run "
        f"`python -m contracts.generate`: {sorted(missing_on_disk)}"
    )


def test_canonical_v1_endpoints_present() -> None:
    """The frozen OpenAPI MUST contain every Phase 1 canonical endpoint.

    This is an explicit positive assertion against the contract — if any
    of these disappears, the freeze (and CI) catches the regression
    independently of the byte-equality check above.
    """
    import json
    openapi = json.loads((CONTRACT_DIR / "v1" / "openapi.json").read_text())
    paths = openapi.get("paths", {})

    required_v1 = {
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/login/google",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
        "/api/v1/identity/users",
        "/api/v1/identity/users/{user_id}/suspend",
        "/api/v1/identity/users/{user_id}/activate",
        "/api/v1/identity/users/{user_id}/role",
        "/api/v1/identity/service-accounts",
        "/api/v1/identity/service-accounts/{account_id}/revoke",
        "/api/v1/identity/delegations",
        "/api/v1/identity/delegations/{grant_id}/revoke",
        "/api/.well-known/jwks.json",
        # Phase 2A — Registry bounded context
        "/api/v1/registry/landvaults",
        "/api/v1/registry/landvaults/{registry_id}",
        "/api/v1/registry/landvaults/{registry_id}/location",
        "/api/v1/registry/landvaults/{registry_id}/geometry",
        "/api/v1/registry/landvaults/{registry_id}/ownership-contact",
        "/api/v1/registry/landvaults/{registry_id}/ownership-transfer",
        "/api/v1/registry/landvaults/{registry_id}/survey",
        "/api/v1/registry/landvaults/{registry_id}/community-data",
        "/api/v1/registry/landvaults/{registry_id}/archive",
    }
    missing = required_v1 - set(paths.keys())
    assert not missing, f"Frozen contract is missing canonical v1 endpoints: {missing}"


def test_every_legacy_endpoint_is_deprecated() -> None:
    """Every `/api/*` (non-v1) operation MUST be marked `deprecated: true`
    and tagged `legacy`."""
    import json
    openapi = json.loads((CONTRACT_DIR / "v1" / "openapi.json").read_text())
    paths = openapi.get("paths", {})
    methods = {"get", "post", "put", "patch", "delete", "options", "head"}
    failures: list[str] = []
    for path, ops in paths.items():
        is_v1 = "/v1/" in path or ".well-known" in path
        if is_v1:
            continue
        for method, op in ops.items():
            if method.lower() not in methods:
                continue
            if not op.get("deprecated"):
                failures.append(f"{method.upper()} {path}: missing deprecated:true")
            tags = op.get("tags") or []
            if "legacy" not in tags:
                failures.append(f"{method.upper()} {path}: missing 'legacy' tag")
    assert not failures, (
        "Legacy endpoints not properly tagged per deprecation-policy.md:\n  "
        + "\n  ".join(failures)
    )


def test_event_catalog_matches_outbox_event_types() -> None:
    """Every event in `kernel.events.outbox.EVENT_TYPES` MUST appear in the
    Event Catalog at the version declared by `kernel.events.envelope`.

    This ensures the runtime event producer and the published contract
    cannot drift apart — adding a new event_type without registering it
    in the catalog fails CI.
    """
    import json
    import sys
    backend = str(Path("/app/backend"))
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from kernel.events.outbox import EVENT_TYPES  # type: ignore

    catalog = json.loads((CONTRACT_DIR / "v1" / "events" / "catalog.json").read_text())
    cataloged = {entry["event_name"] for entry in catalog["events"]}
    runtime = set(EVENT_TYPES)
    only_runtime = runtime - cataloged
    only_catalog = cataloged - runtime
    assert not only_runtime, (
        f"Events emitted at runtime but not in the catalog: {sorted(only_runtime)}. "
        "Add them to contracts/generate.py EVENT_DEFINITIONS and regenerate."
    )
    assert not only_catalog, (
        f"Events in the catalog but not emitted at runtime: {sorted(only_catalog)}. "
        "Either restore the producer or remove them from EVENT_DEFINITIONS."
    )


def test_role_matrix_matches_canonical_roles() -> None:
    """The published role_matrix MUST list exactly the 10 canonical roles."""
    import json
    import sys
    backend = str(Path("/app/backend"))
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from contexts.identity.domain.value_objects import ALL_ROLES  # type: ignore

    matrix = json.loads(
        (CONTRACT_DIR / "v1" / "security" / "role_matrix.json").read_text()
    )
    published = {r["name"] for r in matrix["roles"]}
    assert published == set(ALL_ROLES), (
        f"role_matrix.json drift — published={sorted(published)}, "
        f"runtime={sorted(ALL_ROLES)}"
    )


def test_sdk_fingerprints_are_present_and_well_formed() -> None:
    """`contract.sha256` MUST list every artifact with a 64-hex digest."""
    sha_file = CONTRACT_DIR / "v1" / "sdk" / "contract.sha256"
    assert sha_file.exists()
    lines = [ln for ln in sha_file.read_text().splitlines() if ln.strip()]
    assert lines, "contract.sha256 is empty"
    for ln in lines:
        parts = ln.split("  ", 1)
        assert len(parts) == 2, f"Malformed line in contract.sha256: {ln!r}"
        digest, path = parts
        assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), (
            f"Bad SHA256 in {path}: {digest!r}"
        )
