#!/usr/bin/env bash
# Post-telemetry sanity for colocated k3s + fabric.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=fabric-nodes.sh
source "${ROOT}/scripts/fabric-nodes.sh"

export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"
MIN_DEVICES="${COLOCATED_MIN_SRL_DEVICES:-${#SRL_NODES[@]}}"

die()  { echo "ERROR: [telemetry-sanity] $*" >&2; exit 1; }
info() { echo "==> [telemetry-sanity] $*"; }

for dep in alloy ktranslate-snmp-srl ktranslate-flow ktranslate-sflow ktranslate-syslog gnmic; do
  kubectl -n network-lab rollout status "deployment/${dep}" --timeout=180s \
    || die "deployment/${dep} not ready"
done

bash "${ROOT}/scripts/verify-ktranslate-service-names.sh" \
  || die "ktranslate OTEL_SERVICE_NAME verification failed"

device_count="$(yq 'length' "${ROOT}/state/devices-srl.yaml" 2>/dev/null || echo 0)"
[[ "${device_count}" =~ ^[0-9]+$ ]] || device_count=0
[[ "${device_count}" -ge "${MIN_DEVICES}" ]] \
  || die "devices-srl.yaml has ${device_count} devices (need >=${MIN_DEVICES})"

info "k8s collectors ready; ${device_count} SNMP devices discovered"
info "telemetry sanity passed"
