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

log "ensuring host dependencies"
bash scripts/colocated-host-deps.sh

log "waiting for fabric sanity (systemd should have finished fabric unit)"
bash scripts/colocated-fabric-sanity.sh

log "stopping stray compose collectors (k3s owns telemetry on this host)"
bash scripts/stop-compose-collectors.sh || true

log "deploying ktranslate-golden to k3s (regenerate manifests for this host)"
bash scripts/deploy-ktranslate-golden.sh

log "ensuring SNMP enabled on SRL nodes before discovery"
bash scripts/enable-snmp-srl.sh

log "SNMP discovery (per-device TARGETS → state/devices-*.yaml)"
bash scripts/update-snmp-targets.sh
MIN_DEVICES="${COLOCATED_MIN_SRL_DEVICES:-5}"
device_count="$(yq 'length' state/devices-srl.yaml 2>/dev/null || echo 0)"
[[ "${device_count}" =~ ^[0-9]+$ ]] || device_count=0
DISCOVERY_ATTEMPTS="${COLOCATED_DISCOVERY_ATTEMPTS:-3}"
disc_ok=0
if [[ "${device_count}" -ge "${MIN_DEVICES}" ]]; then
  log "devices-srl.yaml already has ${device_count} devices — syncing collectors"
  export COLLECTOR_RUNTIME=k3s
  bash scripts/reload-ktranslate-devices.sh || true
  disc_ok=1
else
  for attempt in $(seq 1 "${DISCOVERY_ATTEMPTS}"); do
    log "discovery attempt ${attempt}/${DISCOVERY_ATTEMPTS}"
    if COLLECTOR_RUNTIME=k3s bash scripts/run-discovery-all.sh; then
      disc_ok=1
      break
    fi
    log "discovery failed — retry in 30s"
    sleep 30
  done
fi
[[ "${disc_ok}" -eq 1 ]] || {
  log "SNMP discovery failed after ${DISCOVERY_ATTEMPTS} attempts"
  exit 1
}

export KTRANSLATE_CLAB_HOST="$(
  docker network inspect "${CLAB_NETWORK:-clab}" -f '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null || true
)"
[[ -n "$KTRANSLATE_CLAB_HOST" ]] || KTRANSLATE_CLAB_HOST="172.20.20.1"
log "collector clab host=${KTRANSLATE_CLAB_HOST}"

if ! bash scripts/post-telemetry-config.sh; then
  log "post-telemetry-config failed"
  exit 1
fi

bash scripts/colocated-telemetry-sanity.sh

make traffic || true
make status || true
log "telemetry ready"
