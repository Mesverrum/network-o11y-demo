#!/usr/bin/env bash
# Colocated reference: ContainerLab fabric only (no compose collectors).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export HOME="${HOME:-/root}"
export LAB_FABRIC_PROFILE=colocated

log() { echo "$(date -Is) [colocated-fabric] $*"; }

log "ensuring host dependencies"
bash scripts/colocated-host-deps.sh

log "deployment.host=$(bash scripts/host-id.sh) fabric=${LAB_FABRIC_PROFILE}"
bash scripts/write-compose-host-env.sh
bash scripts/stage-fabric-profile.sh
make generate bootstrap
mkdir -p config state
chown -R 1000:1000 config state 2>/dev/null || true

if ! make check; then
  log "make check failed"
  exit 1
fi

if docker ps --format '{{.Names}}' | grep -qE '^spine1$'; then
  log "fabric already running — stabilize + sanity"
  make fabric-stabilize
  bash scripts/colocated-fabric-sanity.sh
else
  log "cold start — destroy stale lab then staggered colocated fabric-up"
  bash scripts/clab.sh destroy || true
  bash scripts/colocated-fabric-up.sh
fi

log "fabric ready"
