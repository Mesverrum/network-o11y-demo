#!/usr/bin/env bash
# Colocated reference: k3s telemetry from local/ golden path.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

log() { echo "$(date -Is) [colocated-telemetry] $*"; }

export HOME="${HOME:-/root}"
export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"
export COLLECTOR_RUNTIME=k3s
export LAB_FABRIC_PROFILE=colocated
export KTRANSLATE_OTEL_ENDPOINT="${KTRANSLATE_OTEL_ENDPOINT:-http://127.0.0.1:4317/}"

log "stopping stray compose collectors (k3s owns telemetry on this host)"
bash scripts/stop-compose-collectors.sh || true

log "deploying ktranslate-golden to k3s (regenerate manifests for this host)"
bash scripts/deploy-ktranslate-golden.sh

log "verifying collector service_name suffixes"
bash scripts/verify-ktranslate-service-names.sh --prometheus || {
  log "naming verification failed — check KTRANS_HOST in .env and regenerate"
  exit 1
}

log "SNMP discovery (CIDR scan from groups/*.env → state/devices-*.yaml)"
if ! bash scripts/run-discovery-all.sh; then
  log "SNMP discovery failed — check groups/srl.env TARGETS and fabric SNMP"
  exit 1
fi

export KTRANSLATE_CLAB_HOST="$(
  docker network inspect "${CLAB_NETWORK:-clab}" -f '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null || true
)"
[[ -n "$KTRANSLATE_CLAB_HOST" ]] || KTRANSLATE_CLAB_HOST="172.20.20.1"
log "collector clab host=${KTRANSLATE_CLAB_HOST}"

bash scripts/post-telemetry-config.sh || log "post-telemetry-config had warnings"
make traffic || true
make status || true
log "telemetry ready"
