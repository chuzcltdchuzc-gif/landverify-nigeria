#!/usr/bin/env bash
# AquaSavannah LandVault — Contract Drift CI Gate (Phase 1C).
#
# Fails the build when the live FastAPI surface (or any other contract
# input) deviates from the frozen artifacts under /app/contracts/v1.
#
# Usage:
#   bash contracts/ci_check_drift.sh
#
# Exit codes:
#   0  no drift
#   1  drift detected (review stderr for the list of files)
#   2  environment / invocation error
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v python >/dev/null 2>&1; then
    echo "[contract-drift] python not found on PATH" >&2
    exit 2
fi

if [[ ! -f contracts/VERSION ]]; then
    echo "[contract-drift] contracts/VERSION missing — package not bootstrapped" >&2
    exit 2
fi

VERSION="$(tr -d ' \n' < contracts/VERSION)"
echo "[contract-drift] contract version on disk: ${VERSION}"

# Regenerate in --check mode. The generator returns non-zero on any drift.
python -m contracts.generate --check
echo "[contract-drift] PASS — frozen contract matches live FastAPI surface."
