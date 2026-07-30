#!/usr/bin/env bash
# Stop compose collector containers when k3s runs ktranslate-golden (colocated reference).
# Prevents duplicate OTLP streams with unsuffixed or laptop-stale service_name labels.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

warn() { echo "WARNING: $*" >&2; }
info() { echo "==> $*"; }

if [[ ! -f compose-groups.generated.yaml ]]; then
  info "compose not generated; nothing to stop"
  exit 0
fi

COMPOSE_ARGS=(
  --env-file "${ROOT}/.env"
  --env-file "${ROOT}/compose-host.generated.env"
  -f "${ROOT}/compose-base.yaml"
  -f "${ROOT}/compose-groups.generated.yaml"
  -f "${ROOT}/compose-catalog.generated.yaml"
)

COLLECTOR_SERVICES=(
  alloy
  flow_dns
  gnmic
  ktranslate_flow
  ktranslate_sflow
  ktranslate_syslog
  topology_exporter
)

shopt -s nullglob
for env_file in "${ROOT}/groups"/*.env; do
  group="$(awk -F= '/^GROUP=/{print $2; exit}' "${env_file}")"
  [[ -z "${group}" ]] && continue
  COLLECTOR_SERVICES+=("ktranslate_snmp_${group}")
done
shopt -u nullglob

RUNNING=()
for svc in "${COLLECTOR_SERVICES[@]}"; do
  if docker compose "${COMPOSE_ARGS[@]}" ps --status running --services 2>/dev/null \
    | grep -qx "${svc}"; then
    RUNNING+=("${svc}")
  fi
done

if [[ ${#RUNNING[@]} -eq 0 ]]; then
  info "no compose collector services running"
  exit 0
fi

info "stopping compose collectors (k3s owns telemetry): ${RUNNING[*]}"
docker compose "${COMPOSE_ARGS[@]}" stop "${RUNNING[@]}" 2>/dev/null \
  || warn "compose stop had errors (containers may already be gone)"
docker compose "${COMPOSE_ARGS[@]}" rm -f "${RUNNING[@]}" 2>/dev/null \
  || true
