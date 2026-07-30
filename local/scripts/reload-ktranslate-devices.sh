#!/usr/bin/env bash
# Restart ktranslate receivers that read state/devices-*.yaml (catalog + pollers).
# Called after any group's device list changes so flow/sFlow/syslog and all SNMP
# pollers pick up the latest @-included device maps.
#
# Usage: ./scripts/reload-ktranslate-devices.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
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
