#!/usr/bin/env bash
# Restart ktranslate receivers that read state/devices-*.yaml (catalog + pollers).
# Called after any group's device list changes so flow/sFlow/syslog and all SNMP
# pollers pick up the latest @-included device maps.
#
# Usage: ./scripts/reload-ktranslate-devices.sh
#
# Colocated (k3s): set COLLECTOR_RUNTIME=k3s to rollout k8s deployments instead
# of docker compose restart.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

_reload_k3s_collectors() {
  export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"
  # shellcheck source=snmp-group-utils.sh
  source "${REPO_ROOT}/scripts/snmp-group-utils.sh"
  if ! kubectl get namespace network-lab >/dev/null 2>&1; then
    echo "network-lab namespace not found; k3s reload skipped" >&2
    return 1
  fi
  bash "${REPO_ROOT}/scripts/refresh-flow-dns.sh"
  local dep restarted=0
  while IFS= read -r dep; do
    if kubectl -n network-lab get deployment "${dep}" >/dev/null 2>&1; then
      kubectl -n network-lab rollout restart "deployment/${dep}"
      restarted=1
    fi
  done < <(k8s_snmp_deployment_names "${REPO_ROOT}")
  for dep in ktranslate-flow ktranslate-sflow ktranslate-syslog; do
    if kubectl -n network-lab get deployment "${dep}" >/dev/null 2>&1; then
      kubectl -n network-lab rollout restart "deployment/${dep}"
      restarted=1
    fi
  done
  if [[ "${restarted}" -eq 0 ]]; then
    echo "no ktranslate deployments in network-lab; reload skipped" >&2
    return 1
  fi
  echo "restarted ktranslate-golden deployments in network-lab"
  return 0
}

if [[ "${COLLECTOR_RUNTIME:-}" == "k3s" ]]; then
  _reload_k3s_collectors
  exit $?
fi

COMPOSE_ARGS=(
  --env-file "${REPO_ROOT}/.env"
  --env-file "${REPO_ROOT}/compose-host.generated.env"
  -f "${REPO_ROOT}/compose-base.yaml"
  -f "${REPO_ROOT}/compose-groups.generated.yaml"
  -f "${REPO_ROOT}/compose-catalog.generated.yaml"
)

if [[ ! -f "${REPO_ROOT}/compose-groups.generated.yaml" ]]; then
  echo "missing compose-groups.generated.yaml — run: make generate" >&2
  exit 1
fi
if [[ ! -f "${REPO_ROOT}/compose-catalog.generated.yaml" ]]; then
  echo "missing compose-catalog.generated.yaml — run: make generate" >&2
  exit 1
fi

RELOAD_SERVICES=(ktranslate_flow ktranslate_sflow ktranslate_syslog)

shopt -s nullglob
for env_file in "${REPO_ROOT}/groups"/*.env; do
  group="$(awk -F= '/^GROUP=/{print $2; exit}' "${env_file}")"
  [[ -z "${group}" ]] && continue
  RELOAD_SERVICES+=("ktranslate_snmp_${group}")
done
shopt -u nullglob

RUNNING=()
for svc in "${RELOAD_SERVICES[@]}"; do
  if docker compose "${COMPOSE_ARGS[@]}" ps --status running --services 2>/dev/null \
       | grep -qx "${svc}"; then
    RUNNING+=("${svc}")
  fi
done

if [[ ${#RUNNING[@]} -eq 0 ]]; then
  echo "no ktranslate catalog/poller services running; reload skipped"
  exit 0
fi

bash "${REPO_ROOT}/scripts/refresh-flow-dns.sh"

docker compose "${COMPOSE_ARGS[@]}" restart "${RUNNING[@]}"
echo "reloaded ktranslate device catalog consumers: ${RUNNING[*]}"
