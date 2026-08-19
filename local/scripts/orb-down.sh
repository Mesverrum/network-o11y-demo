#!/usr/bin/env bash
# Stop Orb agent sidecar.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ORB="${ROOT}/orb"
if [[ -f "${ORB}/compose.yaml" ]]; then
  ( cd "$ORB" && docker compose -f compose.yaml down ) || true
fi
docker rm -f orb-agent >/dev/null 2>&1 || true
echo "==> orb-agent stopped"
