#!/usr/bin/env bash
# Idempotent heal for a running colocated EC2 (systemd telemetry failed, flow-dns stale, etc.).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export HOME="${HOME:-/root}"
export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"
export COLLECTOR_RUNTIME=k3s
export LAB_FABRIC_PROFILE=colocated
export KTRANSLATE_OTEL_ENDPOINT="${KTRANSLATE_OTEL_ENDPOINT:-http://127.0.0.1:4317/}"

log() { echo "$(date -Is) [colocated-heal] $*"; }

log "fabric sanity"
bash scripts/colocated-fabric-sanity.sh

log "sync flow-dns + ktranslate device consumers"
bash scripts/reload-ktranslate-devices.sh

log "post-telemetry sidecars (softflowd, sFlow, syslog, traps, traffic)"
bash scripts/post-telemetry-config.sh

log "telemetry sanity"
bash scripts/colocated-telemetry-sanity.sh

systemctl reset-failed network-o11y-telemetry 2>/dev/null || true
log "heal complete"
