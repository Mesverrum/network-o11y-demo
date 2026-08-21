#!/usr/bin/env bash
# Post-telemetry sanity for colocated k3s + fabric.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=fabric-nodes.sh
source "${ROOT}/scripts/fabric-nodes.sh"
# shellcheck source=snmp-group-utils.sh
source "${ROOT}/scripts/snmp-group-utils.sh"

export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"
MIN_DEVICES="${COLOCATED_MIN_SRL_DEVICES:-${#SRL_NODES[@]}}"

die()  { echo "ERROR: [telemetry-sanity] $*" >&2; exit 1; }
info() { echo "==> [telemetry-sanity] $*"; }

kubectl -n network-lab rollout status deployment/alloy --timeout=180s \
  || die "deployment/alloy not ready"
kt_on=1
case "${LAB_KTRANSLATE:-1}" in
  0|false|FALSE|no|NO|off|OFF) kt_on=0 ;;
esac
if [[ "${kt_on}" == "1" ]]; then
  while IFS= read -r dep; do
    kubectl -n network-lab rollout status "deployment/${dep}" --timeout=180s \
      || die "deployment/${dep} not ready"
  done < <(k8s_snmp_deployment_names "${ROOT}")
  for dep in ktranslate-flow ktranslate-sflow ktranslate-syslog gnmic; do
    kubectl -n network-lab rollout status "deployment/${dep}" --timeout=180s \
      || die "deployment/${dep} not ready"
  done
  bash "${ROOT}/scripts/verify-ktranslate-service-names.sh" \
    || die "ktranslate OTEL_SERVICE_NAME verification failed"
else
  if kubectl -n network-lab get deployment gnmic >/dev/null 2>&1; then
    kubectl -n network-lab rollout status deployment/gnmic --timeout=180s \
      || die "deployment/gnmic not ready"
  fi
  info "LAB_KTRANSLATE=0 — skipped ktranslate rollout checks"
fi

device_count="$(snmp_total_discovered_devices "${ROOT}")"
[[ "${device_count}" =~ ^[0-9]+$ ]] || device_count=0
[[ "${device_count}" -ge "${MIN_DEVICES}" ]] \
  || die "SNMP device catalogs have ${device_count} devices total (need >=${MIN_DEVICES})"

info "k8s collectors ready; ${device_count} SNMP devices across site groups"
info "telemetry sanity passed"
