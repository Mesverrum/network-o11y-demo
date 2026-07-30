#!/usr/bin/env bash
# Shared guard: is the SNMP collector (trap sink) up — compose or k3s hostNetwork?
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

collector_snmp_ready() {
  if [[ "${COLLECTOR_RUNTIME:-}" == "k3s" ]]; then
    export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"
    kubectl -n network-lab get deployment ktranslate-snmp-srl >/dev/null 2>&1
    return $?
  fi
  if kubectl get namespace network-lab >/dev/null 2>&1 \
    && kubectl -n network-lab get deployment ktranslate-snmp-srl >/dev/null 2>&1; then
    return 0
  fi
  docker ps -qf name=ktranslate_snmp_srl | grep -q .
}

collector_syslog_ready() {
  if [[ "${COLLECTOR_RUNTIME:-}" == "k3s" ]]; then
    export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"
    kubectl -n network-lab get deployment ktranslate-syslog >/dev/null 2>&1
    return $?
  fi
  if kubectl get namespace network-lab >/dev/null 2>&1 \
    && kubectl -n network-lab get deployment ktranslate-syslog >/dev/null 2>&1; then
    return 0
  fi
  docker ps -qf name=ktranslate_syslog | grep -q .
}

# Default trap/syslog target on colocated k3s (hostNetwork listeners on the node).
export_colocated_clab_host() {
  if [[ -n "${KTRANSLATE_CLAB_HOST:-}" ]]; then
    return 0
  fi
  if collector_snmp_ready && ! docker ps -qf name=ktranslate_snmp_srl | grep -q .; then
    KTRANSLATE_CLAB_HOST="$(
      docker network inspect "${CLAB_NETWORK:-clab}" -f '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null || true
    )"
    [[ -n "$KTRANSLATE_CLAB_HOST" ]] || KTRANSLATE_CLAB_HOST="172.20.20.1"
    export KTRANSLATE_CLAB_HOST
  fi
}
