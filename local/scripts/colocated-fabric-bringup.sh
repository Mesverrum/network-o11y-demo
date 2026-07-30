#!/usr/bin/env bash
# Colocated reference: ContainerLab fabric only (no compose collectors).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export HOME="${HOME:-/root}"

log() { echo "$(date -Is) [colocated-fabric] $*"; }

log "deployment.host=$(bash scripts/host-id.sh)"
bash scripts/write-compose-host-env.sh
make generate bootstrap
mkdir -p config state
chown -R 1000:1000 config state 2>/dev/null || true

if ! make check; then
  log "make check failed"
  exit 1
fi

if docker ps --format '{{.Names}}' | grep -qE '^spine1$'; then
  log "fabric running — fabric-stabilize"
  make fabric-stabilize
else
  log "cold start — make fabric-up"
  make fabric-up
fi

make discover-all || log "discovery failed (non-fatal)"
log "fabric ready"
